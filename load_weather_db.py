"""Load the cleaned weather CSVs into a SQLite database.

Reads data/processed/cities.csv and data/processed/forecast.csv - the output of
clean_weather.py - and stores them as two tables in data/weather.db.

The two CSVs both carry the city and the country in every row, which is exactly
the duplication a relational schema is meant to remove. So the city becomes a
row of its own in "cities", and every forecast row points at it through the
foreign key city_id.

    cities 1 --- many forecast        forecast.city_id -> cities.city_id

Rerunning the script reloads the current snapshot: both tables are emptied
first, so the data always matches the CSVs and no rows are duplicated.
"""

import os
import sqlite3
from time import time

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
PROCESSED_DIR = os.path.join(HERE, "data", "processed")
DB_PATH = os.path.join(HERE, "data", "weather.db")

# Columns of the cities table, in schema order, so the frame written by pandas
# lines up with the table that was created by hand.
CITY_COLUMNS = [
    "city", "country", "url", "location",
    "temp_f", "temp_c", "condition", "feels_like_f",
    "forecast_high_f", "forecast_low_f",
    "wind_mph", "wind_from",
    "humidity_pct", "pressure_hg", "visibility_mi", "dew_point_f",
    "current_time_local", "latest_report_local", "scraped_at",
]

# The forecast keeps city_id instead of the city and country names.
FORECAST_COLUMNS = [
    "city_id", "forecast_date", "day_of_week",
    "temp_high_f", "temp_low_f", "temp_high_c", "temp_low_c", "temp_range_f",
    "condition", "feels_like_f",
    "wind_mph", "wind_bearing_deg", "wind_from",
    "humidity_pct", "precip_chance_pct", "precip_amount_in",
    "uv_index", "uv_category",
    "sunrise", "sunset", "scraped_at",
]

CREATE_CITIES = """
CREATE TABLE IF NOT EXISTS cities (
    city_id INTEGER PRIMARY KEY,
    city TEXT NOT NULL,
    country TEXT NOT NULL,
    url TEXT,
    location TEXT,
    temp_f REAL,
    temp_c REAL,
    condition TEXT,
    feels_like_f REAL,
    forecast_high_f REAL,
    forecast_low_f REAL,
    wind_mph REAL,
    wind_from TEXT,
    humidity_pct REAL,
    pressure_hg REAL,
    visibility_mi REAL,
    dew_point_f REAL,
    current_time_local TEXT,
    latest_report_local TEXT,
    scraped_at TEXT,
    UNIQUE (city, country)
)
"""

CREATE_FORECAST = """
CREATE TABLE IF NOT EXISTS forecast (
    forecast_id INTEGER PRIMARY KEY,
    city_id INTEGER NOT NULL,
    forecast_date TEXT NOT NULL,
    day_of_week TEXT,
    temp_high_f REAL,
    temp_low_f REAL,
    temp_high_c REAL,
    temp_low_c REAL,
    temp_range_f REAL,
    condition TEXT,
    feels_like_f REAL,
    wind_mph REAL,
    wind_bearing_deg REAL,
    wind_from TEXT,
    humidity_pct REAL,
    precip_chance_pct REAL,
    precip_amount_in REAL,
    uv_index REAL,
    uv_category TEXT,
    sunrise TEXT,
    sunset TEXT,
    scraped_at TEXT,
    UNIQUE (city_id, forecast_date),
    FOREIGN KEY (city_id) REFERENCES cities (city_id)
)
"""

START_TIME = time()


def log(step, message):
    """Print a progress line stamped with seconds since the run started."""
    print(f"[{time() - START_TIME:6.1f}s] {step:<9} {message}", flush=True)


def report(stage, name, frame):
    """Print the shape and the null counts of a frame."""
    nulls = frame.isna().sum()
    nulls = nulls[nulls > 0].sort_values(ascending=False)
    null_text = ", ".join(f"{c} {n}" for c, n in nulls.items()) or "none"
    log(stage, f"{name} {frame.shape} | nulls: {null_text}")


def read_processed(file_name):
    """Read one of the cleaned CSVs written by clean_weather.py."""
    path = os.path.join(PROCESSED_DIR, file_name)
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} is missing, run clean_weather.py first")

    log("LOAD", file_name)
    return pd.read_csv(path)


def load_table(conn, table, frame, columns):
    """Replace the contents of a table with the rows of the frame.

    The table itself is created by the CREATE statements above rather than by
    pandas, so the primary key, the foreign key and the UNIQUE constraints
    survive. to_sql only appends the rows.
    """
    conn.execute(f"DELETE FROM {table}")
    frame[columns].to_sql(table, conn, if_exists="append", index=False)
    log("WRITE", f"{table}: {len(frame)} rows")


def attach_city_ids(conn, forecast):
    """Swap the city and country names of the forecast for the city_id key.

    The ids are read back from the database, because SQLite assigns them, and
    the pair of city and country is what identifies a city in both CSVs.
    """
    cities = pd.read_sql_query("SELECT city_id, city, country FROM cities", conn)

    merged = forecast.merge(cities, on=["city", "country"], how="left")

    unmatched = int(merged["city_id"].isna().sum())
    if unmatched > 0:
        log("CLEAN", f"forecast: {unmatched} rows without a matching city dropped")
        merged = merged[merged["city_id"].notna()]

    merged["city_id"] = merged["city_id"].astype(int)
    return merged


def print_query(conn, title, sql_statement):
    """Run a query and print the rows it returns."""
    print(f"\n--- {title} ---")
    print(pd.read_sql_query(sql_statement, conn).to_string(index=False))
    print()


def main():
    log("SETUP", f"Input:  {PROCESSED_DIR}")
    log("SETUP", f"Output: {DB_PATH}")

    cities = read_processed("cities.csv")
    forecast = read_processed("forecast.csv")
    report("BEFORE", "cities", cities)
    report("BEFORE", "forecast", forecast)

    conn = None
    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Without this pragma SQLite would accept forecast rows pointing at
            # a city that does not exist.
            conn.execute("PRAGMA foreign_keys = 1")

            conn.execute(CREATE_CITIES)
            conn.execute(CREATE_FORECAST)
            log("SCHEMA", "cities and forecast are in place")

            # The forecast is emptied first: its rows reference the cities, so
            # they cannot outlive them.
            conn.execute("DELETE FROM forecast")
            load_table(conn, "cities", cities, CITY_COLUMNS)

            forecast = attach_city_ids(conn, forecast)
            report("AFTER", "forecast keyed by city_id", forecast[FORECAST_COLUMNS])
            load_table(conn, "forecast", forecast, FORECAST_COLUMNS)

            conn.commit()

            city_count = conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0]
            forecast_count = conn.execute("SELECT COUNT(*) FROM forecast").fetchone()[0]
            log("CHECK", f"cities: {city_count} rows, forecast: {forecast_count} rows")

            orphans = conn.execute("""
                SELECT COUNT(*)
                FROM forecast
                LEFT JOIN cities ON forecast.city_id = cities.city_id
                WHERE cities.city_id IS NULL
            """).fetchone()[0]
            log("CHECK", f"forecast rows without a city: {orphans}")

            # The join is what the schema was built for: the country lives in
            # cities only, and the forecast borrows it through city_id.
            print_query(conn, "Five hottest days in the forecast", """
                SELECT cities.city, cities.country,
                       forecast.forecast_date, forecast.temp_high_f
                FROM forecast
                JOIN cities ON forecast.city_id = cities.city_id
                ORDER BY forecast.temp_high_f DESC
                LIMIT 5
            """)
    except sqlite3.Error as e:
        # Any SQL statement can raise, and a failed load should say why.
        log("ERROR", f"{type(e).__name__} {e}")
    finally:
        # The "with" statement commits or rolls back, but does not close.
        if conn is not None:
            conn.close()

    log("DONE", f"Total run time: {time() - START_TIME:.1f}s")


if __name__ == "__main__":
    main()
