# NZ Diesel Monitor

NZ diesel pump prices against Brent crude, in NZ cents per litre, monthly from March 2025.

**View it:** https://henry-ahm.github.io/diesel-monitor/

Refreshes every Thursday morning (NZ time) from public data:
- MBIE weekly fuel price monitoring, via data.govt.nz
- FRED: Brent spot (DCOILBRENTEU) and US$ per NZ$ (DEXUSNZ)

No login or API key. `refresh_diesel.py` downloads the data, writes `data.json`, and builds the page from `template.html`.

Henry Martin
