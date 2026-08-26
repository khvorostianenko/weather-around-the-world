"""Scrape current conditions and 14-day forecasts from timeanddate.com."""

import csv
import os
from datetime import datetime, timezone
from time import sleep, time

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

HERE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(HERE, "data", "raw")

INDEX_URL = "https://www.timeanddate.com/weather/"
CITY_LIMIT = int(os.environ.get("CITY_LIMIT", 50))
REQUEST_DELAY = 2
PAGE_TIMEOUT = 40
RENDER_DELAY = 2

# The site sits behind Cloudflare and rejects default automation user agents.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)

INDEX_TABLE = "table.zebra.fw.tb-theme"
QUICK_LOOK = "#qlook"
DETAIL_TABLE = "table.table--left"
FORECAST_TABLE = "table#wt-ext"

CITY_FIELDS = [
    "city", "country", "url", "temp", "condition", "feels_like",
    "forecast_hi_lo", "wind", "location", "current_time", "latest_report",
    "visibility", "pressure", "humidity", "dew_point", "scraped_at",
]
FORECAST_FIELDS = [
    "city", "country", "day_of_week", "date_label", "temp_hi_lo", "condition",
    "feels_like", "wind", "wind_dir", "humidity", "precip_chance",
    "precip_amount", "uv", "sunrise", "sunset", "scraped_at",
]

START_TIME = time()


def log(step, message):
    """Print a progress line stamped with seconds since the run started."""
    print(f"[{time() - START_TIME:6.1f}s] {step:<8} {message}", flush=True)


def text_or_none(parent, css_selector):
    """Return the first matching descendant's text, or None if absent."""
    found = parent.find_elements(By.CSS_SELECTOR, css_selector)
    return found[0].text.strip() if found else None


def cell(cells, index):
    """Return the text of cells[index], or None if the row is short."""
    return cells[index].text.strip() if index < len(cells) else None


def cell_title(cells, index):
    """Return the title attribute of a span inside cells[index], or None.

    The wind direction cell renders as an arrow glyph; the compass bearing only
    exists in the span's title.
    """
    if index >= len(cells):
        return None
    spans = cells[index].find_elements(By.CSS_SELECTOR, "span[title]")
    return spans[0].get_attribute("title") if spans else None


def build_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920x1080")
    options.add_argument(f"user-agent={USER_AGENT}")
    # With the default "normal" strategy driver.get() never returns on this
    # site - some resource keeps the load event pending forever.
    options.page_load_strategy = "eager"

    log("DRIVER", "Installing / locating the Chrome driver...")
    driver_path = ChromeDriverManager().install()
    log("DRIVER", "Starting headless Chrome...")
    driver = webdriver.Chrome(service=ChromeService(driver_path), options=options)
    driver.set_page_load_timeout(PAGE_TIMEOUT)
    log("DRIVER", "Browser ready.")
    return driver


def fetch(driver, url):
    """Load a page, tolerating the page-load timeout. False if nothing loaded."""
    log("FETCH", f"GET {url}")
    sleep(REQUEST_DELAY)
    try:
        driver.get(url)
    except Exception as e:
        log("FETCH", f"page load timed out ({type(e).__name__}), using what rendered")
    sleep(RENDER_DELAY)
    if "Just a moment" in driver.title:
        log("SKIP", f"Cloudflare challenge on {url}")
        return False
    return True


def parse_city_index(driver):
    """Return [{city, country, url}] from the world temperatures table."""
    tables = driver.find_elements(By.CSS_SELECTOR, INDEX_TABLE)
    if not tables:
        log("SKIP", "index table not found")
        return []

    cities = []
    for link in tables[0].find_elements(By.CSS_SELECTOR, "a"):
        href = link.get_attribute("href") or ""
        name = link.text.strip()
        parts = [p for p in href.split("/weather/")[-1].split("/") if p]
        if not name or len(parts) < 2:
            continue
        cities.append({"city": name, "country": parts[0], "url": href})
    return cities


def parse_current(driver, city, scraped_at):
    """Return one row of current conditions for a city."""
    row = {
        "city": city["city"], "country": city["country"], "url": city["url"],
        "scraped_at": scraped_at,
    }
    for field in CITY_FIELDS:
        row.setdefault(field, None)

    # #qlook is a stack of lines: temperature, condition, then labelled values.
    quick = driver.find_elements(By.CSS_SELECTOR, QUICK_LOOK)
    if quick:
        lines = [ln.strip() for ln in quick[0].text.split("\n") if ln.strip()]
        values = [ln for ln in lines if ln.lower() != "now"]
        if values:
            row["temp"] = values[0]
        if len(values) > 1:
            row["condition"] = values[1]
        for line in values[2:]:
            if ":" not in line:
                continue
            label, _, value = line.partition(":")
            key = label.strip().lower().replace(" ", "_")
            if key == "feels_like":
                row["feels_like"] = value.strip()
            elif key == "forecast":
                row["forecast_hi_lo"] = value.strip()
            elif key == "wind":
                row["wind"] = value.strip()
    else:
        log("SKIP", f"{city['city']}: no {QUICK_LOOK} block")

    # The detail table is a list of "Label: value" rows.
    detail = driver.find_elements(By.CSS_SELECTOR, DETAIL_TABLE)
    if detail:
        for line in detail[0].text.split("\n"):
            if ":" not in line:
                continue
            label, _, value = line.partition(":")
            key = label.strip().lower().replace(" ", "_")
            if key in row:
                row[key] = value.strip()
    else:
        log("SKIP", f"{city['city']}: no detail table")

    return row


def parse_forecast(driver, city, scraped_at):
    """Return one row per forecast day for a city."""
    tables = driver.find_elements(By.CSS_SELECTOR, FORECAST_TABLE)
    if not tables:
        log("SKIP", f"{city['city']}: no forecast table")
        return []

    rows = []
    for tr in tables[0].find_elements(By.CSS_SELECTOR, "tbody tr"):
        header = text_or_none(tr, "th")
        if not header:
            continue
        # The th holds "Wed\nAug 26".
        header_lines = [ln.strip() for ln in header.split("\n") if ln.strip()]
        cells = tr.find_elements(By.CSS_SELECTOR, "td")
        rows.append({
            "city": city["city"],
            "country": city["country"],
            "day_of_week": header_lines[0] if header_lines else None,
            "date_label": header_lines[1] if len(header_lines) > 1 else None,
            "temp_hi_lo": cell(cells, 1),
            "condition": cell(cells, 2),
            "feels_like": cell(cells, 3),
            "wind": cell(cells, 4),
            "wind_dir": cell_title(cells, 5),
            "humidity": cell(cells, 6),
            "precip_chance": cell(cells, 7),
            "precip_amount": cell(cells, 8),
            "uv": cell(cells, 9),
            "sunrise": cell(cells, 10),
            "sunset": cell(cells, 11),
            "scraped_at": scraped_at,
        })
    return rows


def write_csv(path, fieldnames, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    log("WRITE", f"{os.path.basename(path)}: {len(rows)} rows, "
                 f"{os.path.getsize(path)} bytes")


def main():
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log("SETUP", f"Source: {INDEX_URL}")
    log("SETUP", f"City limit: {CITY_LIMIT}, delay: {REQUEST_DELAY}s, "
                 f"timeout: {PAGE_TIMEOUT}s")
    log("SETUP", f"Scrape timestamp: {scraped_at}")

    driver = build_driver()
    city_rows, forecast_rows = [], []

    try:
        # One request for the whole city list - no per-city discovery requests.
        log("INDEX", "Fetching the world temperatures index...")
        if not fetch(driver, INDEX_URL):
            raise RuntimeError("could not load the index page")
        all_cities = parse_city_index(driver)
        log("INDEX", f"Found {len(all_cities)} cities, taking the first {CITY_LIMIT}.")
        cities = all_cities[:CITY_LIMIT]

        for position, city in enumerate(cities, start=1):
            label = f"{position}/{len(cities)} {city['city']} ({city['country']})"
            log("CITY", f"{label} ...")
            try:
                if fetch(driver, city["url"]):
                    current = parse_current(driver, city, scraped_at)
                    city_rows.append(current)
                    log("PARSE", f"current: {current['temp']} {current['condition']} "
                                 f"| humidity {current['humidity']} "
                                 f"| dew point {current['dew_point']}")

                if fetch(driver, city["url"].rstrip("/") + "/ext"):
                    days = parse_forecast(driver, city, scraped_at)
                    forecast_rows.extend(days)
                    log("PARSE", f"forecast rows: {len(days)}")
            except Exception as e:
                log("ERROR", f"{city['city']}: {type(e).__name__} {e}")

            log("CITY", f"{label} done | totals: {len(city_rows)} cities, "
                        f"{len(forecast_rows)} forecast rows")
    except Exception as e:
        log("ERROR", f"{type(e).__name__} {e}")
    finally:
        log("DRIVER", "Closing the browser.")
        driver.quit()

    write_csv(os.path.join(RAW_DIR, "cities_raw.csv"), CITY_FIELDS, city_rows)
    write_csv(os.path.join(RAW_DIR, "forecast_raw.csv"), FORECAST_FIELDS, forecast_rows)
    log("DONE", f"Total run time: {time() - START_TIME:.1f}s")


if __name__ == "__main__":
    main()
