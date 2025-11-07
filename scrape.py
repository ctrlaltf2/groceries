"""
Pulls down raw grocery data for later analysis
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
import json

import pyzstd  # TODO(3.14): Add zstd, currently we're on 3.13 but 3.14 hits soon once curl-cffi moves up

from aldi.resource import GrocerySearchAPI

def write_json_zstd(data: dict[str, Any], path: Path):
    with open(path, "wb") as f:
        as_str = json.dumps(data, separators=(",", ":"), sort_keys=True)
        as_bytes = as_str.encode("utf-8")
        as_compressed_str = pyzstd.compress(as_bytes, 10)
        f.write(as_compressed_str)


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

    api = GrocerySearchAPI(args.api_host, args.api_root)

    this_job_id = uuid4()
    scrape_start = datetime.now(timezone.utc)
    scrape_meta = {
        "id": str(this_job_id),
        "region": args.region,
        "store": args.store,
        "start": scrape_start.isoformat(),
    }

    job_data_path =Path(args.output_path) / str(this_job_id)
    job_data_path.mkdir(parents=True, exist_ok=True)

    write_json_zstd(scrape_meta, job_data_path / "meta.json.zst")

    for page in api.crawl_store(args.region, args.store):
        write_json_zstd(page.response_data, job_data_path / f'{page.response_time.isoformat()}.json.zst')
