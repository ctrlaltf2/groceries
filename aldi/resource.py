"""
Give a clean sane API over the grocery search API
"""
import itertools
import json
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, NamedTuple, Callable, Generator, reveal_type
from urllib.parse import quote

import backoff
import curl_cffi
import pydantic

from aldi.models import SearchAPIResponse
from aldi.exceptions import FailedButRetrying, ScraperNeedsHumanIntervention
from aldi.utilities import exp_collision_avoidance, perturb

# TODO: pull this from the API directly, no hardcode
class SortBy(StrEnum):
    Relevance = 'relevance'
    AToZ = 'name_asc'
    ZToA = 'name_desc'
    PriceLowToHigh = 'price_asc'
    PriceHighToLow = 'price_desc'

# Sortby options that have duals
SORTBY_DUALS = {
    SortBy.AToZ: SortBy.ZToA,
    SortBy.ZToA: SortBy.AToZ,
    SortBy.PriceLowToHigh: SortBy.PriceHighToLow,
    SortBy.PriceHighToLow: SortBy.PriceLowToHigh,
}


# Reuse data models from API response
type Facet = SearchAPIResponse.Meta.Facet
type FacetValue = SearchAPIResponse.Meta.Facet.Value


@dataclass
class FacetFlat:
    type Id = str

    # e.g. usaSnapEligible
    key: str
    # e.g. true
    value: str
    # number of items for this filter
    n_items: int
    # list of children by id
    children: set[Id]

    # uniquely identifies a facet
    def id(self) -> Id:
        return f'{self.key}={self.value}'


def flatten_facet_value(facet_value: FacetValue) -> list[FacetValue]:
    ret = [facet_value]

    for child in facet_value.children:
        ret += flatten_facet_value(child)

    return ret


def flatten_facet(facet: Facet) -> list[FacetFlat]:
    key = facet.config.parameterName

    all_values: list[FacetValue] = []
    for value in facet.values:
        all_values += flatten_facet_value(value)

    return [
        FacetFlat(
            key=key,
            value=value.key,
            n_items=value.docCount,
            children={child.key for child in value.children}
        )
        for value in all_values
    ]


# Helper tuple, facets (filters) classified by their ability to reach all products
# given the scraping limitations
class ClassifiedFacets(NamedTuple):
    # able to scrape all things given our limits
    scrapes_all: list[Facet]
    # only able to scrape part of things, given our limits
    scrapes_partial: list[Facet]


@dataclass
class PageCrawlResult:
    skus: set[str]
    response_data: dict[str, Any]
    response_time: datetime


@dataclass
class GrocerySearchAPI:
    # hostname of the grocery search API
    api_hostname: str
    # path to the API call for the grocery search API
    api_path: str

    # Max items to page through
    max_page_items: int = 1000
    # max number of items to request in a page
    # TODO: this can be automatically pulled from .meta.pagination.limit
    items_per_page: int = 60

    @staticmethod
    @backoff.on_exception(
        wait_gen=exp_collision_avoidance,
        exception=(curl_cffi.exceptions.HTTPError, FailedButRetrying),
        max_time=4 * 60 * 60,
        max_tries=15
    )
    def _get(url: str) -> curl_cffi.requests.models.Response:
        print(f"GET {url}")
        time.sleep(random.randrange(7200, 12000) / 1000)
        response = curl_cffi.get(url, impersonate="chrome", headers={"Accept": "*/*"})

        # Dispatch on the possible exceptions
        if response.status_code != 200:
            print(f"{response.status_code}")
            # backoff
            if response.status_code == 429:
                raise FailedButRetrying()

            # 5xx -> backoff, maybe the server will fix itself soon
            if 500 <= response.status_code < 600:
                raise FailedButRetrying()

            if response.status_code in {400, 401, 402, 404, 405, 406, 410}:
                raise ScraperNeedsHumanIntervention(
                    f"We may have been blocked... {response.status_code}"
                )

            if response.status_code == 403:
                print('WARN: got 403, backing off')
                raise FailedButRetrying()

            # Everything not covered probably needs looked at
            raise ScraperNeedsHumanIntervention(
                f"Something happened :(, Unexpected status code {response.status_code}."
            )

        print('ok')
        return response


    def _build_url(self, parameters: dict[str, str]):
        # match the order the webapp uses
        params_order = [
            'currency',
            'serviceType',
            'q',
            'limit',
            'offset',
            'brandName',
            'categoryTree',
            'usaSnapEligible',
            'sort',
            'testVariant',
            'servicePoint',
        ]

        params_known = set(params_order)

        params_used = set(parameters.keys())
        params_used_known = params_used & params_known
        params_used_unknown = params_used - params_known

        params_ordered: list[tuple[str, str]] = []

        # add known-order parameters first
        for param_key in params_order:
            if param_key in params_used_known:
                params_ordered.append((param_key, parameters[param_key]))

        # add unknown-order parameters last
        for param_key in params_used_unknown:
            params_ordered.append((param_key, parameters[param_key]))

        # create query string
        query_str: str = ''
        if len(params_ordered) > 0:
            query_str = '?'
            for key, value in params_ordered:
                if len(key) > 0:
                    query_str += quote(key, encoding=None, errors=None)
                    query_str += '='
                    query_str += quote(value, encoding=None, errors=None)
                    query_str += '&'

        query_str = query_str.strip('&')

        # with that out of the way...
        return f'https://{self.api_hostname}{self.api_path}{query_str}'


    @staticmethod
    def _format_service_point(region_id: int, store_id: int) -> str:
        return f'{region_id:03}-{store_id:03}'


    def _crawl_results(
        self,
        region_id: int,
        store_id: int,
        sort_by: SortBy = SortBy.Relevance,
        additional_parameters: dict[str, str] | None = None
    ) -> Generator[PageCrawlResult]:
        params = {
            'currency': 'USD',
            'testVariant': 'A',
            'servicePoint': f'{region_id:03}-{store_id:03}',
            'q': '',
        }

        if sort_by != SortBy.Relevance:
            params['sort'] = str(sort_by)

        if additional_parameters is not None:
            params.update(additional_parameters)

        end_index = None
        current_index = 0

        def is_done_paging(
            current_index: int,
            end_index: int | None,
            page_size: int,
            max_base_index: int,
        ) -> bool:
            unknown_end: bool = (end_index is None)
            past_end: bool = not unknown_end and (current_index >= end_index)

            past_reachable = current_index > (max_base_index + page_size)

            return past_reachable or past_end

        while not is_done_paging(current_index, end_index, self.items_per_page, self.max_page_items):
            params_this_page = params.copy()
            params_this_page['limit'] = str(self.items_per_page)
            params_this_page['offset'] = str(min(current_index, self.max_page_items))

            this_page_url = self._build_url(params_this_page)
            response = self._get(this_page_url)
            response_time = datetime.now(timezone.utc)

            # Check for JSON
            if response.headers.get("content-type") != "application/json":
                raise ScraperNeedsHumanIntervention(
                    f"Did not get json, got {response.headers.get('content-type')} instead."
                )

            # Try to parse JSON response
            response_data: dict[str, Any] = {}
            try:
                response_data = json.loads(response.text)
            except json.JSONDecodeError:
                raise ScraperNeedsHumanIntervention(
                    f"Endpoint sent back JSON, but it wasn't JSON...\n{response.text}"
                )

            page_count_reported = int(response_data["meta"]["pagination"]["totalCount"])
            if end_index is None:
                end_index = page_count_reported

            # pull out SKUs
            skus = {data['sku'] for data in response_data['data']}

            yield PageCrawlResult(
                skus=skus,
                response_data=response_data,
                response_time=response_time
            )

            #write_json_zstd(js, job_data_path / f'{response_time.isoformat()}.json.zst')

            # Restart if the external products db updated while we were paging
            if page_count_reported != end_index:
                end_index = None
                continue

            current_index += self.items_per_page


    def _get_all_facets(self, region_id: int, store_id: int) -> list[Facet]:
        url = self._build_url({
            'currency': 'USD',
            'testVariant': 'A',
            'servicePoint': f'{region_id:03}-{store_id:03}',
            'q': ''
        })

        response = self._get(url)

        # Check for JSON
        if response.headers.get("content-type") != "application/json":
            raise ScraperNeedsHumanIntervention(
                f"Did not get json, got {response.headers.get('content-type')} instead."
            )

        # Try to parse JSON response
        # TODO: partial Pydantic validate here. Allow anything outside of .meta.facets to have changed.
        response_data: dict[str, Any] = {}
        try:
            response_data = json.loads(response.text)
        except json.JSONDecodeError:
            raise ScraperNeedsHumanIntervention(
                f"Endpoint sent back JSON, but it wasn't JSON...\n{response.text}"
            )

        # Try to model validate the facets
        try:
            return [
                SearchAPIResponse.Meta.Facet.model_validate(facet)
                for facet in response_data['meta']['facets']
            ]
        except pydantic.ValidationError as e:
            raise ScraperNeedsHumanIntervention(f"Response body data model for facets changed, unable to continue ('{e}')")


    def get_total_number_of_products(self, region_id: int, store_id: int) -> int:
        url = self._build_url({
            'currency': 'USD',
            'testVariant': 'A',
            'servicePoint': f'{region_id:03}-{store_id:03}',
            'q': ''
        })

        response = self._get(url)

        # Check for JSON
        if response.headers.get("content-type") != "application/json":
            raise ScraperNeedsHumanIntervention(
                f"Did not get json, got {response.headers.get('content-type')} instead."
            )

        # Try to parse JSON response
        # TODO: partial Pydantic validate here. Allow anything outside of .meta.pagination to have changed.
        response_data: dict[str, Any] = {}
        try:
            response_data = json.loads(response.text)
        except json.JSONDecodeError:
            raise ScraperNeedsHumanIntervention(
                f"Endpoint sent back JSON, but it wasn't JSON...\n{response.text}"
            )

        return int(response_data["meta"]["pagination"]["totalCount"])


    def crawl_store(self, region_id: int, store_id: int) -> Generator[PageCrawlResult]:
        # First, get the number of products at this store
        print('Getting initial number of products')
        n_products = self.get_total_number_of_products(region_id, store_id)
        print(f'{n_products=}')

        # `max_page_items` limits us to page through that many items.
        # By sorting one way (e.g. price_asc), then sorting on its dual (e.g. price_desc), we can scroll
        # through 2*`max_page_items`.
        if n_products <= 2*self.max_page_items:
            print('Possible to do this without filtering...')
            if n_products <= self.max_page_items:
                print('Possible to do this without dual mode...')
                # Straight-through mode
                for page in self._crawl_results(region_id, store_id):
                    yield page
            else:
                print('Doing dual mode...')
                # dual mode- crawl forwards one way (e.g. price ascending) then flip it (e.g. price descending)
                # which lets us crawl 2*max_page_items :)
                # we'll stop crawling as soon as `n_products` is hit
                skus_seen: set[str] = set()

                sort_by = random.choice(list(SORTBY_DUALS.keys()))
                print(f'First sortby {sort_by}')
                for page in self._crawl_results(region_id, store_id, sort_by):
                    skus_seen.update(page.skus)
                    print(f"Yielded {len(page.skus)}, at {len(skus_seen)} and want {n_products}")

                    if len(skus_seen) >= n_products:
                        return

                    yield page

                inverse_sort_by = SORTBY_DUALS[sort_by]
                print(f'Second sortby {inverse_sort_by}')
                for page in self._crawl_results(region_id, store_id, inverse_sort_by):
                    skus_seen.update(page.skus)
                    print(f"Yielded {len(page.skus)}, at {len(skus_seen)} and want {n_products}")

                    if len(skus_seen) >= n_products:
                        return

                    yield page

        else:
            print('Advanced mode')
            # Requires generating a more advanced crawling strategy
            # Get potential filters
            facets: list[Facet] = self._get_all_facets(region_id, store_id)

            # Flatten the facets into one big list
            all_possible_filters: list[FacetFlat] = list(itertools.chain.from_iterable([
                flatten_facet(facet) for facet in facets
            ]))

            # Rank filters
            # Ones more than what we can page through are deprioritized, but not removed/filtered- they're still useful
            def ranker(ff: FacetFlat):
                max_reachable = 2*self.max_page_items
                return ff.n_items
                if ff.n_items >= max_reachable:
                    n_unreachable = ff.n_items - max_reachable
                    # penalize a bit because of the unreachability
                    return ff.n_items - 2*n_unreachable
                else:
                    return ff.n_items

            # Null facet is no filters, e.g. return everything
            null_facet = FacetFlat(
                key='',
                value='',
                n_items=n_products,
                children=set(),
            )
            all_possible_filters.append(null_facet)

            all_possible_filters = sorted(all_possible_filters, key=ranker)[::-1]

            # perturb the list a bit to further make runs less consistent
            all_possible_filters = perturb(all_possible_filters, radius=2, prob=0.3)
            print(all_possible_filters[0:10])

            # start tracking SKUs we've seen
            skus_seen: set[str] = set()
            # also track filters we've used- useful for ensuring we don't crawl child facets we didn't need to
            filters_exhausted: set[str] = set()

            # start the crawl
            for flter in all_possible_filters:
                if flter.id() not in filters_exhausted:
                    print(f'filter {flter.id()} yielding {flter.n_items}')
                    dual_mode_necessary = (flter.n_items >= self.max_page_items)

                    if dual_mode_necessary:
                        print('Requires dual mode')
                        sort_by = random.choice(list(SORTBY_DUALS.keys()))
                        for page in self._crawl_results(region_id, store_id, sort_by, {flter.key: flter.value}):
                            skus_seen.update(page.skus)
                            print(f"Yielded {len(page.skus)}, at {len(skus_seen)} and want {n_products}")

                            if len(skus_seen) >= n_products:
                                return

                            yield page

                        inverse_sort_by = SORTBY_DUALS[sort_by]
                        for page in self._crawl_results(region_id, store_id, inverse_sort_by, {flter.key: flter.value}):
                            skus_seen.update(page.skus)
                            print(f"Yielded {len(page.skus)}, at {len(skus_seen)} and want {n_products}")

                            if len(skus_seen) >= n_products:
                                return

                            yield page

                    else:
                        print('no dual mode')
                        weights = {
                            # These two are pretty likely most of the time for typical person browsing
                            SortBy.Relevance: 0.7,
                            SortBy.PriceLowToHigh: 0.2,
                            # These... not so much
                            SortBy.PriceHighToLow: 0.033,
                            SortBy.AToZ: 0.033,
                            SortBy.ZToA: 0.033
                        }

                        sort_by = random.choices(
                            population=list(weights.keys()),
                            weights=list(weights.values()),
                            k=1
                        )
                        print(f'Sorting by {sort_by}')

                        for page in self._crawl_results(region_id, store_id, sort_by[0], {flter.key: flter.value}):
                            skus_seen.update(page.skus)
                            print(f"Yielded {len(page.skus)}, at {len(skus_seen)} and want {n_products}")

                            if len(skus_seen) >= n_products:
                                return

                            yield page

                # update exhausted
                filters_exhausted.add(flter.id())
                filters_exhausted.update(flter.children)
