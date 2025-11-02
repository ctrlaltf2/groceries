"""
Pulls down raw grocery data for later analysis
"""

from datetime import datetime, timezone
from pathlib import Path
from string import Template
from typing import Any
from uuid import uuid4
import json
import random
import time

import curl_cffi
import backoff
import pyzstd  # TODO(3.14): Add zstd, currently we're on 3.13 but 3.14 hits soon once curl-cffi moves up

from utilities import exp_collision_avoidance


class FailedButRetrying(BaseException):
    pass


class ScraperNeedsHumanIntervention(BaseException):
    pass


def write_json_zstd(data: dict[str, Any], path: Path):
    with open(path, "wb") as f:
        as_str = json.dumps(data, separators=(",", ":"), sort_keys=True)
        as_bytes = as_str.encode("utf-8")
        as_compressed_str = pyzstd.compress(as_bytes, 10)
        f.write(as_compressed_str)

@backoff.on_exception(
    wait_gen=exp_collision_avoidance,
    exception=(curl_cffi.exceptions.HTTPError, FailedButRetrying),
    max_time=4 * 60 * 60,
)
def get(url: str) -> curl_cffi.requests.models.Response:
    print(f"GET {url}")
    response = curl_cffi.get(url, impersonate="chrome", headers={"Accept": "*/*"})
    time.sleep(random.randrange(7200, 12000) / 1000)

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

    return response


def scrape(
    api_hostname: str,
    api_path: str,
    region_id: str,
    store_id: str,
    page_limit: int,
    data_root: Path,
):
    this_job_id = uuid4()
    scrape_start = datetime.now(timezone.utc)
    scrape_meta = {
        "id": str(this_job_id),
        "region": region_id,
        "store": store_id,
        "start": scrape_start.isoformat(),
    }

    job_data_path = data_root / str(this_job_id)
    job_data_path.mkdir(parents=True, exist_ok=True)

    write_json_zstd(scrape_meta, job_data_path / "meta.json.zst")

    url = Template(
        f"https://{api_hostname}{api_path}?currency=USD&q=&limit=$limit&offset=$offset&sort=name_asc&servicePoint=$region-$store"
    )

    end_index = None
    current_index = 0
    while (not end_index) or (current_index < end_index):
        this_page_url = url.substitute(
            {
                "limit": page_limit,
                "offset": current_index,
                "region": region_id,
                "store": store_id,
            }
        )

        response = get(this_page_url)
        response_time = datetime.now(timezone.utc)

        # Check for JSON
        if response.headers.get("content-type") != "application/json":
            raise ScraperNeedsHumanIntervention(
                f"Did not get json, got {response.headers.get('content-type')} instead."
            )

        # Try to parse JSON response
        js: dict[str, Any] = {}
        try:
            js = json.loads(response.text)
        except json.JSONDecodeError:
            raise ScraperNeedsHumanIntervention(
                f"Endpoint sent back JSON, but it wasn't JSON...\n{response.text}"
            )

        page_count_reported = int(js["meta"]["pagination"]["totalCount"])
        if end_index is None:
            end_index = page_count_reported

        write_json_zstd(js, job_data_path / f'{response_time.isoformat()}.json.zst')

        # Restart if the external products db updated while we were paging
        if page_count_reported != end_index:
            end_index = None
            continue

        current_index += page_limit


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="groceries-scraper",
        description="Pull down current prices at a specific store",
    )

    # store region, found by choosing a store for pickup near you, and looking at the store code in cookies.
    # An example total store identifier on the West coast might be 479-030, with 479 being the region code
    _ = parser.add_argument(
        "-r", "--region", type=int, required=True, help="Region number (e.g. 479)"
    )
    # See above. If your specific store doesn't show up in the search,
    # check your physical receipt for the store number.
    _ = parser.add_argument(
        "-s", "--store", type=int, required=True, help="Store number (e.g. 40)"
    )
    # Root path to output the raw data to
    _ = parser.add_argument(
        "-o", "--output-path", type=str, required=True, help="Output data path"
    )

    # Play around with the website and you'll see what I mean here :)
    _ = parser.add_argument(
        "-H", "--api-host", type=str, required=True, help="Search API hostname"
    )
    _ = parser.add_argument(
        "-R", "--api-root", type=str, required=True, help="Search API path"
    )
    args = parser.parse_args()

    # Shut pyright up
    assert isinstance(args.store, int)
    assert isinstance(args.region, int)
    assert isinstance(args.output_path, str)
    assert isinstance(args.api_host, str)
    assert isinstance(args.api_root, str)

    scrape(
        args.api_host,
        args.api_root,
        f"{args.region:03}",
        f"{args.store:03}",
        60,
        Path(args.output_path),
    )
