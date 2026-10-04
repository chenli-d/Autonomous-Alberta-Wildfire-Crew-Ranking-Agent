"""Folium map presentation, independent of Streamlit."""
from html import escape

import folium
from shapely.geometry import mapping


def _fire_marker(view, fire_id, latitude, longitude, hazard_score=None):
    label = f"Wildfire: {escape(fire_id)}"
    if hazard_score is not None:
        label += f"<br>Hazard score: {hazard_score}"
    folium.Marker([latitude, longitude], tooltip=label,
                  popup=folium.Popup(label, min_width=220, max_width=300),
                  icon=folium.Icon(color="red", icon="fire", prefix="fa")).add_to(view)


def create_overview_map(fires):
    """All valid daily fires, without community geometry or distance lines."""
    first = fires[0]
    view = folium.Map(location=[first["latitude"], first["longitude"]], zoom_start=8,
                      scroll_wheel_zoom=False)
    for fire in fires:
        _fire_marker(view, fire["fire_id"], fire["latitude"], fire["longitude"], fire["hazard_score"])
    view.fit_bounds([[f["latitude"], f["longitude"]] for f in fires], padding=(30, 30), max_zoom=10)
    return view


def create_map(fire_id, latitude, longitude, nearby, hazard_score=None):
    view = folium.Map(location=[latitude, longitude], zoom_start=8, scroll_wheel_zoom=False)
    _fire_marker(view, fire_id, latitude, longitude, hazard_score)
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
