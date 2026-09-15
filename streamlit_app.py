"""Weather Around The World - a dashboard over the scraped weather database.

Reads data/weather.db, the database built by load_weather_db.py from the
cleaned CSVs, and lets the reader explore it: which cities are hot right now,
how the next two weeks look for one of them, how humidity relates to
temperature, and where rain is expected.

The database is a derived file and is not kept in git, so on a fresh checkout -
which is what Streamlit Community Cloud runs - it is rebuilt from the committed
CSVs on the first load.
"""

import os
import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st

import load_weather_db

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "data", "weather.db")

st.set_page_config(page_title="Weather Around The World", page_icon="🌦", layout="wide")


@st.cache_resource
def get_connection():
    """Open the database, building it from the CSVs when the file is missing.

    cache_resource keeps one connection for the whole app: Streamlit reruns the
    script on every interaction, and reconnecting each time would be wasteful.
    Those reruns happen on different threads, hence check_same_thread=False.
    """
    if not os.path.exists(DB_PATH):
        load_weather_db.main()

    return sqlite3.connect(DB_PATH, check_same_thread=False)


@st.cache_data
def load_cities():
    """Current conditions, one row per city."""
    return pd.read_sql_query(
        """
        SELECT city, country, temp_c, temp_f, condition, humidity_pct,
               wind_mph, wind_from, pressure_hg, scraped_at
        FROM cities
        ORDER BY city
        """,
        get_connection(),
    )


@st.cache_data
def load_forecast():
    """The daily forecast of every city, with the city name joined in."""
    return pd.read_sql_query(
        """
        SELECT cities.city, cities.country, forecast.forecast_date,
               forecast.temp_high_f, forecast.temp_low_f,
               forecast.precip_chance_pct, forecast.condition
        FROM forecast
        JOIN cities ON forecast.city_id = cities.city_id
        ORDER BY cities.city, forecast.forecast_date
        """,
        get_connection(),
    )


cities = load_cities()
forecast = load_forecast()

st.title("🌦 Weather Around The World")
st.markdown(
    "Current conditions and two-week forecasts for 50 cities, scraped from "
    "[timeanddate.com](https://www.timeanddate.com/weather/) and stored in SQLite. "
    "**Use the sidebar** to narrow the selection down: every chart on this page "
    "reacts to it."
)

# --- Sidebar: the filters every chart below reads from ---
st.sidebar.header("Filters")

countries = sorted(cities["country"].unique())
selected_countries = st.sidebar.multiselect(
    "Countries", countries, default=countries,
    help="Empty means no city is left to show.",
)

temp_min = float(cities["temp_c"].min())
temp_max = float(cities["temp_c"].max())
selected_temp = st.sidebar.slider(
    "Current temperature (°C)", temp_min, temp_max, (temp_min, temp_max), step=0.5
)

selection = cities[
    cities["country"].isin(selected_countries)
    & cities["temp_c"].between(*selected_temp)
]

if selection.empty:
    st.warning("No city matches the filters. Widen the country list or the temperature range.")
    st.stop()

forecast_city = st.sidebar.selectbox("City for the forecast chart", sorted(selection["city"]))

city_forecast = forecast[forecast["city"] == forecast_city]
forecast_days = sorted(city_forecast["forecast_date"].unique())
first_day, last_day = st.sidebar.select_slider(
    "Forecast days", options=forecast_days, value=(forecast_days[0], forecast_days[-1])
)
city_forecast = city_forecast[city_forecast["forecast_date"].between(first_day, last_day)]

# --- Headline numbers for the current selection ---
hottest = selection.loc[selection["temp_c"].idxmax()]
coldest = selection.loc[selection["temp_c"].idxmin()]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Cities shown", len(selection))
col2.metric("Countries", selection["country"].nunique())
col3.metric("Hottest now", f"{hottest['temp_c']:.1f} °C", hottest["city"])
col4.metric("Coldest now", f"{coldest['temp_c']:.1f} °C", coldest["city"])

st.divider()

# --- Chart 1: where it is hot right now ---
st.subheader("Current temperature by city")
st.caption("One bar per city in the selection, warmest at the top.")

ranked = selection.sort_values("temp_c")
temperature_bar = px.bar(
    ranked,
    x="temp_c",
    y="city",
    orientation="h",
    color="temp_c",
    color_continuous_scale="RdYlBu_r",
    labels={"temp_c": "Temperature (°C)", "city": "", "country": "Country"},
    hover_data=["country", "condition", "humidity_pct"],
    height=max(400, 18 * len(ranked)),
)
temperature_bar.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0, t=10, b=0))
st.plotly_chart(temperature_bar, use_container_width=True)

# --- Chart 2: the next two weeks for one city ---
st.subheader(f"Forecast for {forecast_city}")
st.caption("Daily high and low. Pick another city or shorten the range in the sidebar.")

forecast_line = px.line(
    city_forecast,
    x="forecast_date",
    y=["temp_high_f", "temp_low_f"],
    markers=True,
    labels={"forecast_date": "Date", "value": "Temperature (°F)", "variable": ""},
    color_discrete_map={"temp_high_f": "indianred", "temp_low_f": "steelblue"},
)
forecast_line.for_each_trace(
    lambda trace: trace.update(name="Daily high" if "high" in trace.name else "Daily low")
)
forecast_line.update_layout(hovermode="x unified", margin=dict(l=0, r=0, t=10, b=0))
st.plotly_chart(forecast_line, use_container_width=True)

# --- Chart 3: how humidity and temperature sit together ---
st.subheader("Humidity against temperature")
st.caption(
    "Each point is a city. Hot and dry sits bottom right, cool and damp top left; "
    "the legend filters countries in and out."
)

humidity_scatter = px.scatter(
    selection,
    x="temp_c",
    y="humidity_pct",
    color="country",
    size="wind_mph",
    hover_name="city",
    hover_data=["condition", "wind_from"],
    labels={
        "temp_c": "Temperature (°C)",
        "humidity_pct": "Humidity (%)",
        "country": "Country",
        "wind_mph": "Wind (mph)",
    },
)
humidity_scatter.update_layout(margin=dict(l=0, r=0, t=10, b=0))
st.plotly_chart(humidity_scatter, use_container_width=True)

# --- Chart 4: where rain is expected, city by day ---
st.subheader("Chance of precipitation, city by day")
st.caption("Darker means a higher chance of rain on that day. Rows follow the selection.")

precip = forecast[forecast["city"].isin(selection["city"])]
precip_matrix = precip.pivot_table(
    index="city", columns="forecast_date", values="precip_chance_pct", aggfunc="mean"
)
precip_heatmap = px.imshow(
    precip_matrix,
    color_continuous_scale="Blues",
    aspect="auto",
    labels=dict(x="Date", y="", color="Chance (%)"),
    height=max(400, 18 * len(precip_matrix)),
)
precip_heatmap.update_layout(margin=dict(l=0, r=0, t=10, b=0))
st.plotly_chart(precip_heatmap, use_container_width=True)

with st.expander("The rows behind these charts"):
    st.dataframe(selection, use_container_width=True, hide_index=True)

st.caption(f"Data scraped {cities['scraped_at'].max()} · {len(cities)} cities, {len(forecast)} forecast rows.")
