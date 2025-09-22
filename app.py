import os
import streamlit as st
import pandas as pd
import numpy as np
from google.cloud import bigquery
from google.oauth2 import service_account
import pydeck as pdk

st.set_page_config(page_title="Fuel Prices Map", layout="wide")
st.title("Fuel Prices Map")

# BigQuery Setup
credentials = service_account.Credentials.from_service_account_info(
    st.secrets["gcp_service_account"]
)
client = bigquery.Client(credentials=credentials, project=credentials.project_id)

# SQL Query
query = """
SELECT 
  last_updated, site_id, brand, address, postcode, latitude, longitude, fuel_type, fuel_price
FROM `ferrous-store-465117-h0.prod.mart_latest_prices`
WHERE latitude IS NOT NULL AND longitude IS NOT NULL
"""

# Fetch Data
@st.cache_data(ttl=600)
def load_data():
    df = client.query(query).to_dataframe()
    return df

df = load_data()

# Create two columns for the filters
col1, col2 = st.columns(2)

# Fuel Type Filter
with col1:
    fuel_types = df["fuel_type"].unique()
    selected_fuel = st.selectbox("Choose Fuel Type", sorted(fuel_types))

# Brand Filter
with col2:
    brands = df["brand"].unique()
    # Add "All Brands" option
    brand_options = ["All Brands"] + sorted([brand for brand in brands if pd.notna(brand)])
    selected_brand = st.selectbox("Choose Brand", brand_options)

# Apply filters
filtered_df = df[df["fuel_type"] == selected_fuel].copy()

if selected_brand != "All Brands":
    filtered_df = filtered_df[filtered_df["brand"] == selected_brand].copy()

# Check if we have data after filtering
if len(filtered_df) == 0:
    st.warning("No data available for the selected combination of fuel type and brand.")
    st.stop()

# Normalise price and calculate colour
min_price = filtered_df["fuel_price"].min()
max_price = filtered_df["fuel_price"].max()
price_range = max(max_price - min_price, 1e-3)  # Avoid divide by zero

# Normalise to [0, 1]
filtered_df["colour_value"] = (filtered_df["fuel_price"] - min_price) / price_range

# Convert to colour: Green → Red
def price_to_colour(val):
    r = int(255 * val)
    g = int(255 * (1 - val))
    return [r, g, 0, 160]

filtered_df["colour"] = filtered_df["colour_value"].apply(price_to_colour)

# Map
brand_text = f" from {selected_brand}" if selected_brand != "All Brands" else ""
st.subheader(f"Showing {selected_fuel} prices{brand_text} at {len(filtered_df)} locations")

st.pydeck_chart(pdk.Deck(
    initial_view_state=pdk.ViewState(
        latitude=filtered_df["latitude"].mean(),
        longitude=filtered_df["longitude"].mean(),
        zoom=6,
        pitch=0,
    ),
    layers=[
        pdk.Layer(
            "ScatterplotLayer",
            data=filtered_df,
            get_position="[longitude, latitude]",
            get_color="colour",
            get_radius=200,  # base radius in meters
            radius_min_pixels=4,  # always visible
            radius_max_pixels=20,
            pickable=True,
        )
    ],
    tooltip={
        "html": "<b>{brand}</b><br />{address}<br /><b>£{fuel_price}</b>",
        "style": {"color": "white"}
    }
))
