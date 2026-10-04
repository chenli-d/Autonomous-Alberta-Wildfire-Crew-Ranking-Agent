"""Folium map presentation, independent of Streamlit."""
from html import escape

import folium
from shapely.geometry import mapping


def create_map(fire_id, latitude, longitude, nearby):
    view = folium.Map(location=[latitude, longitude], zoom_start=8, scroll_wheel_zoom=False)
    folium.Marker([latitude, longitude], tooltip=f"Wildfire: {escape(fire_id)}",
                  icon=folium.Icon(color="red", icon="fire", prefix="fa")).add_to(view)
    for community in nearby:
        popup = (f"<b>{escape(community['name'])}</b><br>{escape(community['type'])}"
                 f"<br>Straight-line distance: {community['distance_km']:.2f} km")
        folium.Marker([community["latitude"], community["longitude"]],
                      popup=folium.Popup(popup, min_width=220, max_width=300), tooltip=popup,
                      icon=folium.Icon(color="blue", icon="info-sign")).add_to(view)
        lon, lat = community["nearest_point"]
        folium.PolyLine([[latitude, longitude], [lat, lon]], color="#d95f02", weight=2).add_to(view)
        if community["geometry"].geom_type != "Point":
            folium.GeoJson(mapping(community["geometry"]), tooltip=popup,
                           style_function=lambda _: {"color": "#2878b5", "weight": 2, "fillOpacity": 0.08}).add_to(view)
    view.get_root().html.add_child(folium.Element(
        '<div style="position:absolute;bottom:25px;left:10px;z-index:1000;background:white;padding:4px">'
        'Community data: <a href="https://geospatial.alberta.ca/titan/rest/services/boundaries/municipal_communities_public/MapServer" target="_blank">Alberta Government</a></div>'))
    return view
