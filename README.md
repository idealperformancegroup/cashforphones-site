# CashForPhones.us

Single-page site for Cash for Phones Louisiana, served by GitHub Pages at https://cashforphones.us.

- `index.html` holds the whole site. Pricing rules (margin, financed and blacklist handling) sit in the config block at the top of the script.
- `prices.js` holds the buyer prices. It's generated, so don't edit it by hand.

## Weekly price update

1. Export the text of the Device Buyers and BestDealPhones sheets (Google Drive file metadata `contentSnippet`).
2. `python3 tools/build_prices.py device-buyers.txt bestdealphones.txt prices.js`
   This also rebuilds `offers/index.html` and `offers.txt`, the offer sheet the GoHighLevel chat bot reads (open > counter > max per condition, no buyer prices).
3. Commit and push. GitHub Pages redeploys in about a minute.

Offer = the higher buyer price for the grade the answers map to, minus cracked-back deductions, minus our margin (20% of the Grade B price, kept between $50 and $100), rounded down to $5.
- `TEXT_TO` is the number that leads text. `LEAD_WEBHOOK` can be set to a GoHighLevel inbound webhook URL.
- `CNAME` sets the custom domain.
