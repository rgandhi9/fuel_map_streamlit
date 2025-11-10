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

col1, col2 = st.columns(2)

with col1:
    start_location = st.text_input("Start Location", placeholder="e.g., London, UK")

with col2:
    end_location = st.text_input("End Location", placeholder="e.g., Manchester, UK")

col3, col4 = st.columns(2)

with col3:
    mpg = st.number_input("Vehicle MPG", min_value=1, max_value=50, value=10, step=0.1)

with col4:
    current_range = st.number_input("Current fuel range (miles)", min_value=0, value=0, 
                                    help="How many miles can you drive with current fuel? Leave at 0 if tank is empty")

if start_location and end_location:
    try:
        from mapbox import Geocoder, Directions
        from math import radians, sin, cos, sqrt, atan2
        
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
                distance_miles = distance_meters * 0.000621371
                duration_seconds = route_data['routes'][0]['duration']
                duration_minutes = duration_seconds / 60
                
                st.success(f"✓ Route found: {distance_miles:.1f} miles ({duration_minutes:.0f} minutes)")
                
                # Check if refueling is needed
                if current_range >= distance_miles:
                    st.info(f"🎉 Good news! Your current range ({current_range} miles) is enough to complete this journey without refueling.")
                else:
                    # Calculate fuel needed
                    miles_needing_fuel = distance_miles - current_range
                    fuel_needed_gallons = miles_needing_fuel / mpg
                    fuel_needed_litres = fuel_needed_gallons * 4.54609
                    
                    st.warning(f"⛽ You'll need to refuel: {fuel_needed_litres:.1f} litres needed (after your current {current_range} mile range)")
                    
                    # Function to calculate distance between two points (Haversine formula)
                    def haversine_distance(lon1, lat1, lon2, lat2):
                        R = 3959  # Earth's radius in miles
                        lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
                        dlon = lon2 - lon1
                        dlat = lat2 - lat1
                        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
                        c = 2 * atan2(sqrt(a), sqrt(1-a))
                        return R * c
                    
                    # Function to calculate perpendicular distance from point to line segment
                    def distance_to_route(station_lon, station_lat, start_lon, start_lat, end_lon, end_lat):
                        # Distance from start
                        dist_from_start = haversine_distance(start_lon, start_lat, station_lon, station_lat)
                        
                        # Distance from end
                        dist_from_end = haversine_distance(end_lon, end_lat, station_lon, station_lat)
                        
                        # Distance of the route
                        route_dist = haversine_distance(start_lon, start_lat, end_lon, end_lat)
                        
                        # If station is roughly along the route (triangle inequality check)
                        # The sum of distances shouldn't be much more than the route distance
                        detour = (dist_from_start + dist_from_end) - route_dist
                        
                        return dist_from_start, detour
                    
                    # Find stations along the route
                    filtered_df['dist_from_start'] = filtered_df.apply(
                        lambda row: distance_to_route(
                            row['longitude'], row['latitude'],
                            start_coords[0], start_coords[1],
                            end_coords[0], end_coords[1]
                        )[0], axis=1
                    )
                    
                    filtered_df['detour_miles'] = filtered_df.apply(
                        lambda row: distance_to_route(
                            row['longitude'], row['latitude'],
                            start_coords[0], start_coords[1],
                            end_coords[0], end_coords[1]
                        )[1], axis=1
                    )
                    
                    # Filter stations:
                    # 1. Within reasonable detour distance (5 miles)
                    # 2. Reachable with current range
                    # 3. That can get us to destination after refueling
                    reachable_stations = filtered_df[
                        (filtered_df['detour_miles'] <= 5) &  # Not too far off route
                        (filtered_df['dist_from_start'] <= current_range)  # Can reach with current fuel
                    ].copy()
                    
                    if len(reachable_stations) > 0:
                        # Calculate total cost for fuel needed
                        reachable_stations['total_fuel_cost'] = reachable_stations['fuel_price'] * fuel_needed_litres
                        
                        # Sort by total cost
                        reachable_stations = reachable_stations.sort_values('total_fuel_cost')
                        
                        # Show top 10 cheapest options
                        st.subheader("💰 Cheapest Fuel Stops Along Your Route")
                        
                        top_stations = reachable_stations.head(10)
                        
                        for idx, station in top_stations.iterrows():
                            col_a, col_b, col_c, col_d = st.columns([3, 2, 2, 2])
                            
                            with col_a:
                                st.write(f"**{station['brand']}** - {station['address']}")
                            with col_b:
                                st.write(f"{station['dist_from_start']:.1f} miles from start")
                            with col_c:
                                st.write(f"£{station['fuel_price']:.3f}/L")
                            with col_d:
                                st.write(f"**£{station['total_fuel_cost']:.2f}** total")
                        
                        # Show savings
                        cheapest = top_stations.iloc[0]['total_fuel_cost']
                        most_expensive = top_stations.iloc[-1]['total_fuel_cost']
                        savings = most_expensive - cheapest
                        
                        if savings > 0.5:
                            st.success(f"💡 You could save £{savings:.2f} by choosing the cheapest option!")
                    
                    else:
                        st.error(f"⚠️ No {selected_fuel} stations found within your current range ({current_range} miles) and along your route. You may need to refuel before starting this journey.")
                
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
