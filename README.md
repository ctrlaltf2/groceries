# Grocery Price Scrapers
Simple grocery price scraper to allow for open and democratic analysis of everyday grocery price trends over time.

# Usage
 - Install deps: `uv pip install -r requirements.txt`
 - Run the thing: `uv run scrape.py -r $REGION -s $STORE -o /tmp/aldi-test -H $HOSTNAME -R $SEARCH_API`
     - Your `$HOSTNAME` and `$SEARCH_API` can be easily found on the product pickup page.
     - `$REGION` is probably not actually a region, but it is a value locally relevant to your nearby stores. Find your store on the pickup website, or one near it, and set it to the store you're shopping. Check your cookies or localstorage and you should see an ID somewhere like 499-030. 499 would be the region.
     - `$STORE` is easier, either use above or check your receipt for the store #.

# Roadmap
 - [x] initial implementation
 - [x] mass rewrite to store raw responses to handle schema changes and more (medallion architecture)
 - [ ] load scraped data json.zst and validate their data models
 - [ ] design a usable type 2 SCD schema for storing everything
 - [ ] write script to load raw validated data into db, handling arbitrarily new data points beung added even out of order
 - [ ] attempt to migrate old schema over
 - [ ] Automated publishing of historical data for a store representative of median US COL
 - [ ] Price diffs
 - [ ] Unit prices (requires mini parser)

# Remarks
This scrapes the product pickup API, and products are around 10-15% more than the in-person prices. Most of the time, the markup is about 10% but not exactly 10%, and there's some cases of 15% markup for cheaper items. Currently there's no obvious pattern but it's a work in progress for finding a way back to the true prices.

# Disclaimer
This repository and its author(s) are not affiliated, associated, authorized, endorsed by, or in any way officially connected with Aldi, or any of its subsidiaries or its affiliates. This program access only information and facts that are publicly and readily accessible.
