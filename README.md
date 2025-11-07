# Aldi Price Scraper
Simple Aldi price scraper to allow for open and democratic analysis of everyday grocery price trends over time.

# Usage
This is a self-contained [uv](https://github.com/astral-sh/uv) script, so have uv installed then simply run the script from the shell.

# Roadmap
 - [ ] Automated publishing of historical data for a store representative of median US COL
 - [ ] Price diffs
 - [ ] Unit prices (requires mini parser)

# Remarks
This scrapes the product pickup API, and products are around 10-15% more than the in-person prices. Most of the time, the markup is about 10% but not exactly 10%, and there's some cases of 15% markup for cheaper items. Currently there's no obvious pattern but it's a work in progress for finding a way back to the true prices.

# Disclaimer
This repository and its author(s) are not affiliated, associated, authorized, endorsed by, or in any way officially connected with Aldi, or any of its subsidiaries or its affiliates. This program access only information and facts that are publicly and readily accessible.
