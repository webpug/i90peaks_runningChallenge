"""Interactive folium map of first-row vs occluded peaks along I-90."""
from __future__ import annotations

import folium

from . import config


def make_map(classified, highway, out_path=config.RESULT_MAP):
    fr = classified[classified.frontrow]
    occ = classified[~classified.frontrow]
    center = [classified.lat.mean(), classified.lon.mean()]
    m = folium.Map(location=center, zoom_start=10, tiles="CartoDB positron")

    folium.GeoJson(highway.to_crs(4326).__geo_interface__,
                   name="I-90",
                   style_function=lambda _: {"color": "#1f77b4", "weight": 3}).add_to(m)

    fg_fr = folium.FeatureGroup(name=f"First row ({len(fr)})").add_to(m)
    for _, p in fr.iterrows():
        folium.CircleMarker(
            [p.lat, p.lon], radius=4, color="#2ca02c", fill=True, fill_opacity=0.9,
            popup=folium.Popup(
                f"<b>FIRST ROW</b><br>elev {p.elev_ft:.0f} ft<br>"
                f"prom {p.prom_ft:.0f} ft", max_width=220),
        ).add_to(fg_fr)

    fg_occ = folium.FeatureGroup(name=f"Occluded ({len(occ)})", show=False).add_to(m)
    for _, p in occ.iterrows():
        barrier = p.get("barrier_above_m", float("nan"))
        folium.CircleMarker(
            [p.lat, p.lon], radius=3, color="#999999", fill=True, fill_opacity=0.6,
            popup=folium.Popup(
                f"occluded<br>elev {p.elev_ft:.0f} ft<br>prom {p.prom_ft:.0f} ft<br>"
                f"barrier +{barrier:.0f} m above summit", max_width=220),
        ).add_to(fg_occ)

    folium.LayerControl(collapsed=False).add_to(m)
    m.save(str(out_path))
    print(f"[viz] wrote {out_path}")
    return out_path
