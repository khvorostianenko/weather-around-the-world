"""Clean the raw scraped CSVs into analysis-ready tables."""

import os
from time import time

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(HERE, "data", "raw")
PROCESSED_DIR = os.path.join(HERE, "data", "processed")

MISSING = {"N/A", "n/a", "", "-", "--"}

START_TIME = time()


def log(step, message):
    """Print a progress line stamped with seconds since the run started."""
    print(f"[{time() - START_TIME:6.1f}s] {step:<9} {message}", flush=True)


def report(stage, name, frame):
    """Print the shape, dtypes and null counts of a frame."""
    numeric = frame.select_dtypes(include="number").shape[1]
    datetime_cols = frame.select_dtypes(include="datetime").shape[1]
    objects = frame.shape[1] - numeric - datetime_cols
    nulls = frame.isna().sum()
    nulls = nulls[nulls > 0].sort_values(ascending=False)
    null_text = ", ".join(f"{c} {n}" for c, n in nulls.items()) or "none"
    log(stage, f"{name} {frame.shape} | {objects} object, {numeric} numeric, "
               f"{datetime_cols} datetime | nulls: {null_text}")


def sample(name, frame, columns):
    """Print three example rows of the given columns."""
    available = [c for c in columns if c in frame.columns]
    print(f"\n--- {name} sample ---")
    print(frame[available].head(3).to_string(index=False))
    print()


def blank_missing(series):
    """Replace the site's placeholder strings with NaN."""
    return series.astype("string").str.strip().replace(list(MISSING), pd.NA)


def first_number(series):
    """Extract the first number in each value as a float."""
    return pd.to_numeric(
        series.astype("string").str.extract(r"(-?\d+(?:\.\d+)?)", expand=False),
        errors="coerce",
    )


def split_hi_lo(series):
    """Split "82 / 76 °F" into two float columns."""
    pair = series.astype("string").str.extract(
        r"(-?\d+(?:\.\d+)?)\s*/\s*(-?\d+(?:\.\d+)?)"
    )
    return (
        pd.to_numeric(pair[0], errors="coerce"),
        pd.to_numeric(pair[1], errors="coerce"),
    )


def to_celsius(fahrenheit):
    return ((fahrenheit - 32) * 5 / 9).round(1)


def numeric_from(frame, source, target, counter):
    """Turn a units-bearing text column into a float column."""
    if source not in frame.columns:
        return
    values = first_number(blank_missing(frame[source]))
    frame[target] = values
    counter[target] = int(values.notna().sum())


def clean_cities(frame):
    log("CLEAN", "cities: normalising placeholder values to NaN")
    for column in ["visibility", "pressure", "humidity", "dew_point",
                   "temp", "feels_like", "wind", "forecast_hi_lo"]:
        if column in frame.columns:
            frame[column] = blank_missing(frame[column])

    converted = {}
    numeric_from(frame, "temp", "temp_f", converted)
    numeric_from(frame, "feels_like", "feels_like_f", converted)
    numeric_from(frame, "humidity", "humidity_pct", converted)
    numeric_from(frame, "dew_point", "dew_point_f", converted)
    numeric_from(frame, "visibility", "visibility_mi", converted)
    # Pressure reads like '30.15 "Hg (27.85 "Hg at 692m altitude)' - the first
    # number is the sea-level value.
    numeric_from(frame, "pressure", "pressure_hg", converted)
    numeric_from(frame, "wind", "wind_mph", converted)
    log("CLEAN", "cities: units stripped -> " +
                 ", ".join(f"{k} ({v})" for k, v in converted.items()))

    # "No wind" is a measurement of zero, not a missing value.
    calm = frame["wind"].astype("string").str.contains("No wind", na=False)
    frame.loc[calm, "wind_mph"] = 0.0
    log("CLEAN", f"cities: 'No wind' read as 0 mph ({int(calm.sum())} rows)")

    high, low = split_hi_lo(frame["forecast_hi_lo"])
    frame["forecast_high_f"] = high
    frame["forecast_low_f"] = low
    log("CLEAN", f"cities: forecast_hi_lo split into high/low "
                 f"({int(high.notna().sum())} rows)")

    # "7 mph ↑ from Southwest" -> "Southwest"
    frame["wind_from"] = frame["wind"].astype("string").str.extract(
        r"from\s+(.+)$", expand=False
    ).str.strip()
    log("CLEAN", f"cities: wind bearing extracted "
                 f"({int(frame['wind_from'].notna().sum())} rows)")

    for source, target in [("current_time", "current_time_local"),
                           ("latest_report", "latest_report_local")]:
        frame[target] = pd.to_datetime(
            frame[source].astype("string").str.replace(" at ", " ", regex=False),
            format="%b %d, %Y %I:%M:%S %p", errors="coerce",
        )
        if frame[target].isna().all():
            frame[target] = pd.to_datetime(
                frame[source].astype("string").str.replace(" at ", " ", regex=False),
                format="%b %d, %Y %I:%M %p", errors="coerce",
            )
        log("CLEAN", f"cities: {source} parsed "
                     f"({int(frame[target].notna().sum())} rows)")

    frame["temp_c"] = to_celsius(frame["temp_f"])
    frame["country"] = frame["country"].astype("string").str.replace(
        "-", " ", regex=False).str.title()
    frame["scraped_at"] = pd.to_datetime(frame["scraped_at"], format="ISO8601")

    before = len(frame)
    frame = frame.drop_duplicates(subset=["city", "country"], keep="first")
    log("CLEAN", f"cities: duplicates dropped on (city, country): "
                 f"{before - len(frame)}")

    columns = [
        "city", "country", "url", "location", "temp_f", "temp_c", "condition",
        "feels_like_f", "forecast_high_f", "forecast_low_f", "wind_mph",
        "wind_from", "humidity_pct", "pressure_hg", "visibility_mi",
        "dew_point_f", "current_time_local", "latest_report_local", "scraped_at",
    ]
    return frame[[c for c in columns if c in frame.columns]]


def clean_forecast(frame):
    log("CLEAN", "forecast: normalising placeholder values to NaN")
    for column in ["temp_hi_lo", "feels_like", "wind", "humidity",
                   "precip_chance", "precip_amount", "uv"]:
        if column in frame.columns:
            frame[column] = blank_missing(frame[column])

    high, low = split_hi_lo(frame["temp_hi_lo"])
    frame["temp_high_f"] = high
    frame["temp_low_f"] = low
    log("CLEAN", f"forecast: temp_hi_lo split into high/low "
                 f"({int(high.notna().sum())} rows)")

    converted = {}
    numeric_from(frame, "feels_like", "feels_like_f", converted)
    numeric_from(frame, "wind", "wind_mph", converted)
    numeric_from(frame, "humidity", "humidity_pct", converted)
    numeric_from(frame, "precip_chance", "precip_chance_pct", converted)
    numeric_from(frame, "precip_amount", "precip_amount_in", converted)
    log("CLEAN", "forecast: units stripped -> " +
                 ", ".join(f"{k} ({v})" for k, v in converted.items()))

    # "7 (High)" -> 7 and "High"
    uv = frame["uv"].astype("string").str.extract(r"(\d+)\s*\((.+)\)")
    frame["uv_index"] = pd.to_numeric(uv[0], errors="coerce")
    frame["uv_category"] = uv[1].str.strip()
    log("CLEAN", f"forecast: uv split into index/category "
                 f"({int(frame['uv_index'].notna().sum())} rows)")

    # "Wind blowing from 210° South-southwest to North-northeast"
    bearing = frame["wind_dir"].astype("string").str.extract(
        r"from\s+(\d+)°\s+([A-Za-z-]+)"
    )
    frame["wind_bearing_deg"] = pd.to_numeric(bearing[0], errors="coerce")
    frame["wind_from"] = bearing[1]
    log("CLEAN", f"forecast: wind bearing parsed "
                 f"({int(frame['wind_bearing_deg'].notna().sum())} rows)")

    # "Aug 26" carries no year. Anchor on the scrape date and roll the year
    # forward when the forecast crosses into January.
    scraped = pd.to_datetime(frame["scraped_at"], format="ISO8601", utc=True)
    frame["scraped_at"] = scraped
    parsed = pd.to_datetime(
        frame["date_label"].astype("string") + " " + scraped.dt.year.astype(str),
        format="%b %d %Y", errors="coerce",
    )
    rolled = (parsed.dt.month < scraped.dt.month.values)
    parsed = parsed.where(~rolled, parsed + pd.offsets.DateOffset(years=1))
    frame["forecast_date"] = parsed
    log("CLEAN", f"forecast: dates parsed ({int(parsed.notna().sum())} rows), "
                 f"{int(rolled.sum())} rolled into the next year")

    frame["temp_high_c"] = to_celsius(frame["temp_high_f"])
    frame["temp_low_c"] = to_celsius(frame["temp_low_f"])
    frame["temp_range_f"] = (frame["temp_high_f"] - frame["temp_low_f"]).round(1)
    frame["country"] = frame["country"].astype("string").str.replace(
        "-", " ", regex=False).str.title()

    before = len(frame)
    frame = frame.drop_duplicates(
        subset=["city", "country", "forecast_date"], keep="first"
    )
    log("CLEAN", f"forecast: duplicates dropped on (city, country, date): "
                 f"{before - len(frame)}")

    frame = frame.sort_values(["country", "city", "forecast_date"])

    columns = [
        "city", "country", "forecast_date", "day_of_week", "temp_high_f",
        "temp_low_f", "temp_high_c", "temp_low_c", "temp_range_f", "condition",
        "feels_like_f", "wind_mph", "wind_bearing_deg", "wind_from",
        "humidity_pct", "precip_chance_pct", "precip_amount_in", "uv_index",
        "uv_category", "sunrise", "sunset", "scraped_at",
    ]
    return frame[[c for c in columns if c in frame.columns]]


def run(name, raw_file, processed_file, cleaner, sample_columns):
    raw_path = os.path.join(RAW_DIR, raw_file)
    log("LOAD", f"{raw_file}")
    raw = pd.read_csv(raw_path, dtype=str)
    report("BEFORE", name, raw)
    sample(f"{name} BEFORE", raw, sample_columns["before"])

    cleaned = cleaner(raw.copy())

    report("AFTER", name, cleaned)
    sample(f"{name} AFTER", cleaned, sample_columns["after"])

    os.makedirs(PROCESSED_DIR, exist_ok=True)
    out_path = os.path.join(PROCESSED_DIR, processed_file)
    cleaned.to_csv(out_path, index=False)
    log("WRITE", f"{processed_file}: {len(cleaned)} rows, "
                 f"{os.path.getsize(out_path)} bytes")
    return cleaned


def main():
    log("SETUP", f"Raw input:  {RAW_DIR}")
    log("SETUP", f"Output:     {PROCESSED_DIR}")

    print("\n" + "=" * 78)
    print("CITIES")
    print("=" * 78)
    cities = run(
        "cities", "cities_raw.csv", "cities.csv", clean_cities,
        {"before": ["city", "temp", "humidity", "pressure", "visibility", "wind"],
         "after": ["city", "temp_f", "temp_c", "humidity_pct", "pressure_hg",
                   "visibility_mi", "wind_mph", "wind_from"]},
    )

    print("\n" + "=" * 78)
    print("FORECAST")
    print("=" * 78)
    forecast = run(
        "forecast", "forecast_raw.csv", "forecast.csv", clean_forecast,
        {"before": ["city", "date_label", "temp_hi_lo", "uv", "precip_amount"],
         "after": ["city", "forecast_date", "temp_high_f", "temp_low_f",
                   "temp_range_f", "uv_index", "uv_category",
                   "precip_amount_in"]},
    )

    log("CHECK", f"cities: {len(cities)} rows, "
                 f"{cities['country'].nunique()} countries")
    log("CHECK", f"forecast: {len(forecast)} rows, "
                 f"{forecast['city'].nunique()} cities, "
                 f"{forecast['forecast_date'].min().date()} .. "
                 f"{forecast['forecast_date'].max().date()}")
    bad = int((forecast["temp_high_f"] < forecast["temp_low_f"]).sum())
    log("CHECK", f"forecast rows where high < low: {bad}")
    log("DONE", f"Total run time: {time() - START_TIME:.1f}s")


if __name__ == "__main__":
    main()
