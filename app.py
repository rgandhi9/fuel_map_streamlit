import os
import streamlit as st
import pandas as pd
import numpy as np
from google.cloud import bigquery
from google.oauth2 import service_account
import pydeck as pdk

st.set_page_config(
    page_title="FleetFuel — Live UK Fuel Price Intelligence",
    page_icon="⛽",
    layout="wide"
)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
    <div style="padding: 1rem 0 0.5rem 0;">
        <h1 style="margin: 0; font-size: 2rem; font-weight: 800; letter-spacing: -0.5px;">
            ⛽ FleetFuel
        </h1>
        <p style="margin: 0.25rem 0 0 0; font-size: 1.05rem; color: #888;">
            Live UK fuel price intelligence for fleet operators
        </p>
    </div>
    <hr style="margin: 0.75rem 0 1.5rem 0; border: none; border-top: 1px solid #e0e0e0;" />
""", unsafe_allow_html=True)

# ── BigQuery Setup ─────────────────────────────────────────────────────────────
credentials = service_account.Credentials.from_service_account_info(
    st.secrets["gcp_service_account"]
)
client = bigquery.Client(credentials=credentials, project=credentials.project_id)

query = """
SELECT 
  last_updated, site_id, brand, address, postcode, latitude, longitude, fuel_type, fuel_price
FROM `ferrous-store-465117-h0.prod.mart_latest_prices`
WHERE latitude IS NOT NULL AND longitude IS NOT NULL
"""

@st.cache_data(ttl=600)
def load_data():
    df = client.query(query).to_dataframe()
    return df

df = load_data()

# ── Sidebar Filters ────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🔧 Filters")

    fuel_types = df["fuel_type"].unique()
    selected_fuel = st.selectbox("Fuel Type", sorted(fuel_types))

    brands = df["brand"].unique()
    brand_options = ["All Brands"] + sorted([b for b in brands if pd.notna(b)])
    selected_brand = st.selectbox("Brand", brand_options)

    st.markdown("---")
    st.markdown("### 📍 Route Cost Calculator")

    start_location = st.text_input("Start Location", placeholder="e.g., London, UK")
    end_location = st.text_input("End Location", placeholder="e.g., Manchester, UK")
    mpg = st.number_input("Vehicle MPG", min_value=1.0, max_value=50.0, value=10.0, step=0.1)
    current_range = st.number_input(
        "Current fuel range (miles)", min_value=0, value=10,
        help="How many miles can you drive on your current fuel? Enter 0 if the tank is empty."
    )

    st.markdown("---")

    # Data freshness (compact, in sidebar)
    brand_updates = df.groupby('brand')['last_updated'].max().reset_index()
    brand_updates['last_updated'] = pd.to_datetime(brand_updates['last_updated'])
    now = pd.Timestamp.now(tz=brand_updates['last_updated'].dt.tz)
    brand_updates['hours_ago'] = (now - brand_updates['last_updated']).dt.total_seconds() / 3600

    statuses = []
    for _, row in brand_updates.iterrows():
        h = row['hours_ago']
        icon = '🟢' if h < 24 else '🟡' if h < 48 else '🔴'
        time_str = f"{int(h)}h ago" if h < 24 else f"{int(h/24)}d ago"
        statuses.append(f"{icon} **{row['brand']}** — {time_str}")

    st.markdown("**Data Freshness**")
    for s in statuses:
        st.markdown(s)

# ── Apply Filters ──────────────────────────────────────────────────────────────
filtered_df = df[df["fuel_type"] == selected_fuel].copy()

if selected_brand != "All Brands":
    filtered_df = filtered_df[filtered_df["brand"] == selected_brand].copy()

filtered_df = filtered_df.dropna(subset=['fuel_price']).copy()

if len(filtered_df) == 0:
    st.warning("No data available for the selected combination of fuel type and brand.")
    st.stop()

# ── Summary Metrics ────────────────────────────────────────────────────────────
brand_text = f" · {selected_brand}" if selected_brand != "All Brands" else ""
st.markdown(f"#### {selected_fuel}{brand_text} — Price Overview across {len(filtered_df):,} stations")

col1, col2, col3, col4 = st.columns(4)

avg_price = filtered_df["fuel_price"].mean()
min_price = filtered_df["fuel_price"].min()
max_price = filtered_df["fuel_price"].max()
cheapest_station = filtered_df.loc[filtered_df["fuel_price"].idxmin()]

with col1:
    st.metric("Average Price", f"{avg_price:.2f}p/L")
with col2:
    st.metric("Cheapest", f"{min_price:.2f}p/L", delta=f"{min_price - avg_price:.2f}p vs avg", delta_color="inverse")
with col3:
    st.metric("Most Expensive", f"{max_price:.2f}p/L", delta=f"{max_price - avg_price:.2f}p vs avg", delta_color="inverse")
with col4:
    st.metric("Potential saving (100L)", f"£{(max_price - min_price):.2f}", help="Difference between cheapest and most expensive for a 100 litre fill")

st.markdown(f"📍 Cheapest station: **{cheapest_station['brand']}** — {cheapest_station['address']} ({cheapest_station['postcode']})")

st.divider()

# ── Route Cost Calculator (main area output) ───────────────────────────────────
if start_location and end_location:
    try:
        from mapbox import Geocoder, Directions
        from math import radians, sin, cos, sqrt, atan2

        geocoder = Geocoder(access_token=st.secrets["mapbox_access_token"])
        directions_service = Directions(access_token=st.secrets["mapbox_access_token"])

        start_response = geocoder.forward(start_location, limit=1)
        end_response = geocoder.forward(end_location, limit=1)

        if start_response.status_code == 200 and end_response.status_code == 200:
            start_coords = start_response.geojson()['features'][0]['geometry']['coordinates']
            end_coords = end_response.geojson()['features'][0]['geometry']['coordinates']

            origin = {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': start_coords}}
            destination = {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': end_coords}}

            route_response = directions_service.directions([origin, destination], 'mapbox/driving')

            if route_response.status_code == 200:
                route_data = route_response.json()
                distance_miles = route_data['routes'][0]['distance'] * 0.000621371
                duration_minutes = route_data['routes'][0]['duration'] / 60

                st.subheader(f"🗺️ Route: {start_location} → {end_location}")

                rc1, rc2 = st.columns(2)
                with rc1:
                    st.metric("Distance", f"{distance_miles:.1f} miles")
                with rc2:
                    st.metric("Est. Drive Time", f"{duration_minutes:.0f} mins")

                if current_range >= distance_miles:
                    st.success(f"✅ Your current range ({current_range} miles) is sufficient — no refuel needed.")
                else:
                    miles_needing_fuel = distance_miles - current_range
                    fuel_needed_litres = (miles_needing_fuel / mpg) * 4.54609

                    st.info(f"⛽ Estimated refuel needed: **{fuel_needed_litres:.1f} litres** (after your current {current_range} mile range)")

                    def haversine_distance(lon1, lat1, lon2, lat2):
                        R = 3959
                        lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
                        dlon, dlat = lon2 - lon1, lat2 - lat1
                        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
                        return R * 2 * atan2(sqrt(a), sqrt(1-a))

                    def distance_to_route(station_lon, station_lat, start_lon, start_lat, end_lon, end_lat):
                        dist_from_start = haversine_distance(start_lon, start_lat, station_lon, station_lat)
                        dist_from_end = haversine_distance(end_lon, end_lat, station_lon, station_lat)
                        route_dist = haversine_distance(start_lon, start_lat, end_lon, end_lat)
                        detour = (dist_from_start + dist_from_end) - route_dist
                        return dist_from_start, detour

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

                    reachable_stations = filtered_df[
                        (filtered_df['detour_miles'] <= 5) &
                        (filtered_df['dist_from_start'] <= current_range)
                    ].copy()

                    if len(reachable_stations) > 0:
                        reachable_stations['total_fuel_cost'] = (reachable_stations['fuel_price'] * fuel_needed_litres) / 100
                        reachable_stations = reachable_stations.sort_values('total_fuel_cost')
                        top_stations = reachable_stations.head(10)

                        st.subheader("🏆 Cheapest Fuel Stops Along Your Route")

                        # Summary saving callout
                        cheapest_cost = top_stations.iloc[0]['total_fuel_cost']
                        priciest_cost = top_stations.iloc[-1]['total_fuel_cost']
                        savings = priciest_cost - cheapest_cost
                        if savings > 0.5:
                            st.success(f"💰 Choosing the cheapest stop could save you **£{savings:.2f}** on this journey.")

                        # Table-style output
                        display_cols = ['brand', 'address', 'dist_from_start', 'fuel_price', 'total_fuel_cost']
                        display_df = top_stations[display_cols].copy()
                        display_df.columns = ['Brand', 'Address', 'Miles from Start', 'Price (p/L)', 'Total Cost (£)']
                        display_df['Miles from Start'] = display_df['Miles from Start'].round(1)
                        display_df['Price (p/L)'] = display_df['Price (p/L)'].round(3)
                        display_df['Total Cost (£)'] = display_df['Total Cost (£)'].round(2)
                        st.dataframe(display_df, use_container_width=True, hide_index=True)
                    else:
                        st.error(f"⚠️ No {selected_fuel} stations found within your current range and along this route.")
            else:
                st.error("Could not calculate route. Please try different locations.")
        else:
            st.error("Could not find one or both locations. Please check your addresses.")

    except Exception as e:
        st.error(f"Error calculating route: {str(e)}")

    st.divider()

# ── Map ────────────────────────────────────────────────────────────────────────
st.subheader("🗺️ Live Price Map")
st.caption("Green = cheapest · Red = most expensive · Based on current filtered selection")

p5 = filtered_df["fuel_price"].quantile(0.05)
p95 = filtered_df["fuel_price"].quantile(0.95)
filtered_df["clipped_price"] = filtered_df["fuel_price"].clip(p5, p95)
price_range = max(p95 - p5, 1e-3)
filtered_df["colour_value"] = (filtered_df["clipped_price"] - p5) / price_range

def price_to_colour(val):
    return [int(255 * val), int(255 * (1 - val)), 0, 160]

filtered_df["colour"] = filtered_df["colour_value"].apply(price_to_colour)

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
            get_radius=200,
            radius_min_pixels=4,
            radius_max_pixels=20,
            pickable=True,
        )
    ],
    tooltip={
        "html": "<b>{brand}</b><br/>{address}, {postcode}<br/><b>{fuel_price}p/L</b>",
        "style": {"color": "white"}
    }
))
