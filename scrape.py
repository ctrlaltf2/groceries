#!/usr/bin/env -S uv run
# /// script
# requires-python = "==3.13"
# dependencies = [
#     "duckdb",
#     "fsspec",
#     "httpx",
#     "curl_cffi==0.13.0",
# ]
# ///
from datetime import datetime, timezone
from pathlib import Path
from string import Template
import argparse
import duckdb
import fsspec
import httpx
import json
import random
import time

parser = argparse.ArgumentParser(
    prog="aldi-scraper", description="Pull down current prices at a specific ALDI store"
)

# store region, found by choosing a store for pickup near you, and looking at the store code in cookies.
# An example total store identifier on the West coast might be 479-030, with 479 being the region code
parser.add_argument(
    "-r", "--region", type=int, required=True, help="Region number (e.g. 479)"
)
# See above. If your specific store doesn't show up in the search,
# check your physical receipt for the store number.
parser.add_argument(
    "-s", "--store", type=int, required=True, help="Store number (e.g. 40)"
)
parser.add_argument(
    "-d", "--db", type=str, required=True, help="Path to output prices database"
)
args = parser.parse_args()

output_db_path = Path(args.db)

# --- Store config
region_number = f"{args.region:03}"
store_number = f"{args.store:03}"
# This is the usual max page limit
page_limit = 60
# ---

# on max timeout, just give up
max_timeout = 4 * 60 * 60 * 1000 # ms, or 4 hours

# --- Scraper config
min_sleep = 7433  # ms
max_sleep = 10151  # ms
headers ={
    'accept': '*/*',
    'accept-language': 'en-US',
    #'origin': 'https://www.aldi.us',
    'priority': 'u=1, i',
    'sec-ch-ua': '"Chromium";v="141", "Not?A_Brand";v="8"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-site',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
}
url = Template(
    "https://api.aldi.us/v3/product-search?currency=USD&q=&limit=$limit&offset=$offset&sort=name_asc&servicePoint=$region-$store"
)
# ---

end_index = None
current_index = 0


# track ephemeral failures and do exponential backoff random retry
def gen_time(failures: int, min_sleep: float, max_sleep: float) -> float:
    sleep_time = 0.0
    for i in range(2**failures):
        sleep_time += random.randrange(min_sleep, max_sleep) / 1000

    return sleep_time


with duckdb.connect(output_db_path) as conn:
    create_table_products = (
        "CREATE TABLE IF NOT EXISTS products ("
        "timestamp TIMESTAMPTZ, "
        "storeCode VARCHAR, "
        "sku VARCHAR, "
        "name VARCHAR, "
        "brandName VARCHAR, "
        "urlSlugText VARCHAR, "
        "discontinued BOOLEAN, "
        "discontinuedNote VARCHAR, "
        "notForSale BOOLEAN, "
        "notForSaleReason VARCHAR, "
        "quantityMin FLOAT, "
        "quantityMax FLOAT, "
        "quantityInterval FLOAT, "
        "quantityDefault FLOAT, "
        "quantityUnit VARCHAR, "
        "weightType VARCHAR, "
        "sellingSize VARCHAR, "
        "priceAmount INTEGER, "
        "priceAmountRelevant INTEGER, "
        "priceComparison INTEGER, "
        "priceCurrencyCode VARCHAR, "
        "pricePerUnit FLOAT, "
        "pricePerUnitDisplay VARCHAR, "
        ");"
    )

    conn.sql(create_table_products)

    failures = 0
    while (not end_index) or (current_index < end_index):
        max_given_failures = 2**failures
        if max_given_failures > max_timeout:
            # give up at this point
            break

        sleep_time = gen_time(failures, min_sleep, max_sleep)
        print(f"Sleeping for {sleep_time}s...")
        time.sleep(sleep_time)
        this_url = url.substitute(
            {
                "limit": page_limit,
                "offset": current_index,
                "region": region_number,
                "store": store_number,
            }
        )
        print(f"GET {this_url}")

        failed = False

        try:
            response = httpx.get(this_url, headers=headers)
            if response.status_code != 200:
                print(f'{response.status_code} from {this_url}')
                failed = True
        except httpx.ConnectTimeout:
            print('Timed out')
            failed = True

        # Exp retry last request if error
        if failed:
            if failures == 15:
                break

            print("Failed, retrying.")
            failures += 1
            continue
        else:
            failures = 0

        js = response.json()

        if end_index is None:
            end_index = int(js["meta"]["pagination"]["totalCount"])
        else:
            latest_end_index = int(js["meta"]["pagination"]["totalCount"])

            # Restart if the external db updated while we were paging
            if latest_end_index != end_index:
                end_index = None
                continue

        if len(js["data"]) == 0:
            break

        # Hacky way to get the json readable from duckdb read_json
        with fsspec.filesystem("memory").open(f"{str(current_index)}.json", "w") as f:
            json.dump(js, f)

        conn.register_filesystem(fsspec.filesystem("memory"))

        insert = f"""
            INSERT INTO products WITH actual_table AS (
                WITH rows_packed AS (
                    SELECT unnest(data) AS data
                        FROM read_json('memory://{str(current_index)}.json')
                ) SELECT unnest(data) FROM rows_packed
            ) SELECT
                TIMESTAMPTZ '{datetime.now(timezone.utc).isoformat()}' as timestamp,
                '{region_number}-{store_number}' as storeCode,
                sku,
                name,
                brandName,
                urlSlugText,
                discontinued,
                discontinuedNote,
                notForSale,
                notForSaleReason,
                quantityMin,
                quantityMax,
                quantityInterval,
                quantityDefault,
                quantityUnit,
                weightType,
                sellingSize,
                price.amount as priceAmount,
                price.amountRelevant as priceAmountRelevant,
                price.comparison as priceComparison,
                price.currencyCode as currencyCode,
                price.perUnit as pricePerUnit,
                price.perUnitDisplay as pricePerUnitDisplay,
            FROM actual_table;
        """

        conn.sql(insert)
        current_index += page_limit

    conn.table("products").show()
