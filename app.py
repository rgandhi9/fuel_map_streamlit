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

# Remove rows with NaN fuel prices
filtered_df = filtered_df.dropna(subset=['fuel_price']).copy()

# Check if we have data after filtering
if len(filtered_df) == 0:
    st.warning("No data available for the selected combination of fuel type and brand.")
    st.stop()

# Route Cost Calculator
st.subheader("Route Cost Calculator")

col1, col2, col3 = st.columns(3)

with col1:
    start_location = st.text_input("Start Location", placeholder="e.g., London, UK")

with col2:
    end_location = st.text_input("End Location", placeholder="e.g., Manchester, UK")

with col3:
    mpg = st.number_input("Vehicle MPG", min_value=1, max_value=150, value=40, step=1)

if start_location and end_location:
    try:
        from mapbox import Geocoder, Directions
        
        # Initialise Mapbox services
        geocoder = Geocoder(access_token=st.secrets["mapbox_access_token"])
        directions_service = Directions(access_token=st.secrets["mapbox_access_token"])
        
        # Geocode start and end locations
        start_response = geocoder.forward(start_location, limit=1)
        end_response = geocoder.forward(end_location, limit=1)
        
        if start_response.status_code == 200 and end_response.status_code == 200:
            start_coords = start_response.geojson()['features'][0]['geometry']['coordinates']
            end_coords = end_response.geojson()['features'][0]['geometry']['coordinates']
            
            # Get route
            origin = {
                'type': 'Feature',
                'geometry': {'type': 'Point', 'coordinates': start_coords}
            }
            destination = {
                'type': 'Feature',
                'geometry': {'type': 'Point', 'coordinates': end_coords}
            }
            
            route_response = directions_service.directions([origin, destination], 'mapbox/driving')
            
            if route_response.status_code == 200:
                route_data = route_response.json()
                distance_meters = route_data['routes'][0]['distance']
                distance_miles = distance_meters * 0.000621371  # Convert to miles
                duration_seconds = route_data['routes'][0]['duration']
                duration_minutes = duration_seconds / 60
                
                # Calculate fuel needed
                fuel_needed_gallons = distance_miles / mpg
                
                st.success(f"✓ Route found: {distance_miles:.1f} miles ({duration_minutes:.0f} minutes)")
                st.info(f"Fuel needed: {fuel_needed_gallons:.2f} gallons at {mpg} MPG")
                
            else:
                st.error("Could not calculate route. Please try different locations.")
        else:
            st.error("Could not find one or both locations. Please check your addresses.")
            
    except Exception as e:
        st.error(f"Error: {str(e)}")

st.divider()

# Show last update time by brand
brand_updates = df.groupby('brand')['last_updated'].max().reset_index()
brand_updates['last_updated'] = pd.to_datetime(brand_updates['last_updated'])
now = pd.Timestamp.now(tz=brand_updates['last_updated'].dt.tz)
brand_updates['hours_ago'] = (now - brand_updates['last_updated']).dt.total_seconds() / 3600

# Create compact status string
statuses = []
for _, row in brand_updates.iterrows():
    h = row['hours_ago']
    status = '✓' if h < 24 else '⚠' if h < 48 else '✗'
    time = f"{int(h)}h" if h < 24 else f"{int(h/24)}d"
    statuses.append(f"{status} {row['brand']} ({time})")

st.caption("**Data freshness:** " + " | ".join(statuses))

# Use percentiles to handle outliers better
p5 = filtered_df["fuel_price"].quantile(0.05)  # 5th percentile
p95 = filtered_df["fuel_price"].quantile(0.95)  # 95th percentile

# Clip extreme values and normalise
filtered_df["clipped_price"] = filtered_df["fuel_price"].clip(p5, p95)
price_range = max(p95 - p5, 1e-3)
filtered_df["colour_value"] = (filtered_df["clipped_price"] - p5) / price_range

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
