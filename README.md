# Weather Around The World

Scrapes current conditions and 14-day forecasts for cities worldwide from
[timeanddate.com/weather](https://www.timeanddate.com/weather/), cleans the data with
pandas, and stores it as CSV. Capstone project for Code the Dream Python 100.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Chrome must be installed; the matching driver is downloaded automatically.

## Usage

```bash
python scrape_weather.py     # writes data/raw/*.csv        (~8 min for 50 cities)
python clean_weather.py      # writes data/processed/*.csv
```

Scrape fewer cities while testing:

```bash
CITY_LIMIT=5 python scrape_weather.py
```

Both scripts log every step with elapsed time.

## Data

`data/processed/cities.csv` — one row per city, current conditions.

| Column | Notes |
| --- | --- |
| `city`, `country`, `url`, `location` | `location` is the reporting station |
| `temp_f`, `temp_c`, `feels_like_f` | |
| `condition` | e.g. `Passing clouds.` |
| `forecast_high_f`, `forecast_low_f` | today's range |
| `wind_mph`, `wind_from` | `wind_from` is a compass name |
| `humidity_pct`, `pressure_hg`, `visibility_mi`, `dew_point_f` | `NaN` where the station reports `N/A` |
| `current_time_local`, `latest_report_local`, `scraped_at` | |

`data/processed/forecast.csv` — one row per city per day, ~15 days ahead.

| Column | Notes |
| --- | --- |
| `city`, `country`, `forecast_date`, `day_of_week` | |
| `temp_high_f`, `temp_low_f`, `temp_high_c`, `temp_low_c`, `temp_range_f` | |
| `condition`, `feels_like_f` | |
| `wind_mph`, `wind_bearing_deg`, `wind_from` | bearing in degrees, 0 = North |
| `humidity_pct`, `precip_chance_pct`, `precip_amount_in` | |
| `uv_index`, `uv_category` | split from `7 (High)` |
| `sunrise`, `sunset`, `scraped_at` | |

`data/raw/` holds the unparsed values (`"82 / 76 °F"`, `"89%"`) so the cleaning step is
reproducible and auditable.

## Scraping policy

`timeanddate.com/robots.txt` allows `/weather/`. The disallowed paths
(`/weather/*?hd=*`, `/weather/*/historic?hd=*`, `/weather/*/hourly?hd=*`,
`/weather/*sort*`) are not used. The scraper pauses 2 seconds between requests, reads the
city list in a single request rather than one per city, and runs on demand only.

## Roadmap

- [x] Week 1 — scraping and data cleaning
- [ ] Week 2 — load into SQLite
- [ ] Week 3 — command line query tool
- [ ] Week 4 — Streamlit dashboard
