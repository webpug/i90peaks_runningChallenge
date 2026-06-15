"""Generate a standalone interactive web app (single self-contained HTML).

Features:
  - Topo / satellite / street basemaps
  - First-row peaks (green) vs occluded (grey), marker size scaled by prominence
  - Prominence slider to filter, and a show/hide-occluded toggle
  - Live stats, click popups
  - In-browser export to GPX + GeoJSON of the *currently visible* peaks
    (CalTopo-ingestible) -- so the download respects your filter.
"""
from __future__ import annotations

import json

from . import config

M_PER_FT = 0.3048


def _peaks_geojson(classified) -> dict:
    feats = []
    for _, p in classified.iterrows():
        cls = "front" if bool(p.get("frontrow", False)) else "behind"
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(p.lon, 6), round(p.lat, 6)]},
            "properties": {
                "elev_ft": round(float(p.elev_ft)),
                "prom_ft": round(float(p.prom_ft)),
                "cls": cls,
                "name": (str(p.get("name")) if p.get("name") not in (None, "", "nan") else ""),
            },
        })
    return {"type": "FeatureCollection", "features": feats}


def build_app(classified, highway, out_path=None) -> str:
    out_path = out_path or (config.PROCESSED / "i90_app.html")
    peaks_gj = _peaks_geojson(classified)
    hw_gj = json.loads(highway.to_crs(4326).to_json())
    n_fr = int(classified.frontrow.sum())
    max_prom = int(classified.prom_ft.max())
    center = [float(classified.lat.mean()), float(classified.lon.mean())]

    html = _TEMPLATE
    html = html.replace("__PEAKS__", json.dumps(peaks_gj))
    html = html.replace("__HIGHWAY__", json.dumps(hw_gj))
    html = html.replace("__CENTER__", json.dumps(center))
    html = html.replace("__NFR__", str(n_fr))
    html = html.replace("__NTOTAL__", str(len(classified)))
    html = html.replace("__MAXPROM__", str(max_prom))
    with open(out_path, "w") as fh:
        fh.write(html)
    print(f"[webapp] wrote {out_path}")
    return str(out_path)


_TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>I-90 First-Row Peaks</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html,body,#map{height:100%;margin:0}
  #panel{position:absolute;top:10px;right:10px;z-index:1000;background:#fff;
    padding:12px 14px;border-radius:10px;box-shadow:0 1px 6px rgba(0,0,0,.3);
    font:13px/1.4 system-ui,sans-serif;max-width:270px}
  #panel h3{margin:0 0 6px;font-size:14px}
  .row{margin:7px 0}
  button{cursor:pointer;border:0;border-radius:6px;padding:6px 9px;font-size:12px;
    background:#2c7fb8;color:#fff;margin-right:5px}
  button.alt{background:#555}
  input[type=range]{width:100%}
  .sw{display:inline-block;width:11px;height:11px;border-radius:50%;
    margin-right:4px;vertical-align:middle}
  .muted{color:#666;font-size:11px}
</style></head><body>
<div id="map"></div>
<div id="panel">
  <h3>I-90 First-Row Peaks</h3>
  <div class="muted">Seattle &rarr; Columbia River &middot; &ge;250&prime; prominence</div>
  <div class="row">
    <label><input type="checkbox" class="cls" value="front" checked>
      <span class="sw" style="background:#2ca02c"></span>First row &mdash; drains to I-90
      (<b id="n_front">0</b>)</label><br>
    <label><input type="checkbox" class="cls" value="behind">
      <span class="sw" style="background:#999"></span>Behind the crest
      (<b id="n_behind">0</b>)</label>
  </div>
  <div class="row">Min prominence: <b id="pval">250</b> ft
    <input id="prom" type="range" min="250" max="__MAXPROM__" step="50" value="250"></div>
  <div class="row muted">Showing <b id="count">0</b> peaks</div>
  <div class="row">
    <button onclick="dl('gpx')">Export GPX</button>
    <button class="alt" onclick="dl('geojson')">GeoJSON</button>
  </div>
  <div class="row muted">GPX/GeoJSON import directly into CalTopo. Export = visible peaks.</div>
</div>
<script>
const PEAKS=__PEAKS__, HIGHWAY=__HIGHWAY__, CENTER=__CENTER__;
const COLOR={front:'#2ca02c',behind:'#999'};
const map=L.map('map').setView(CENTER,10);
const topo=L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
  {maxZoom:17,attribution:'© OpenTopoMap'}).addTo(map);
const sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{x}/{y}',
  {maxZoom:18,attribution:'© Esri'});
const street=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {maxZoom:19,attribution:'© OSM'});
L.control.layers({'Topo':topo,'Satellite':sat,'Street':street}).addTo(map);
L.geoJSON(HIGHWAY,{style:{color:'#1f77b4',weight:3}}).addTo(map);

const counts={front:0,behind:0};
PEAKS.features.forEach(f=>counts[f.properties.cls]++);
for(const k in counts) document.getElementById('n_'+k).textContent=counts[k];

const layer=L.layerGroup().addTo(map);
const radius=p=>Math.max(3,Math.min(11,2+Math.sqrt(p)/12));
function activeClasses(){return new Set([...document.querySelectorAll('.cls:checked')].map(c=>c.value));}
function visiblePeaks(){
  const minP=+document.getElementById('prom').value, cl=activeClasses();
  return PEAKS.features.filter(f=>f.properties.prom_ft>=minP && cl.has(f.properties.cls));
}
const LABEL={front:'FIRST ROW (drains to I-90)',behind:'behind the crest'};
function render(){
  layer.clearLayers();
  const vis=visiblePeaks();
  vis.forEach(f=>{
    const p=f.properties,c=f.geometry.coordinates,col=COLOR[p.cls];
    const nm=p.name||(p.elev_ft+'ft pk');
    L.circleMarker([c[1],c[0]],{radius:radius(p.prom_ft),color:col,weight:1,
      fillColor:col,fillOpacity:.85}).bindPopup(
      `<b>${nm}</b><br>elev ${p.elev_ft} ft<br>prominence ${p.prom_ft} ft`+
      `<br><b style="color:${col}">${LABEL[p.cls]}</b>`).addTo(layer);
  });
  document.getElementById('count').textContent=vis.length;
}
document.getElementById('prom').addEventListener('input',e=>{
  document.getElementById('pval').textContent=e.target.value;render();});
document.querySelectorAll('.cls').forEach(c=>c.addEventListener('change',render));
render();

function download(name,text,mime){
  const a=document.createElement('a');
  a.href='data:'+mime+';charset=utf-8,'+encodeURIComponent(text);
  a.download=name;a.click();
}
function dl(kind){
  const vis=visiblePeaks();
  if(kind==='geojson'){
    download('i90_peaks.geojson',
      JSON.stringify({type:'FeatureCollection',features:vis}),'application/json');
    return;
  }
  let g='<?xml version="1.0" encoding="UTF-8"?>\n'+
    '<gpx version="1.1" creator="i90peaks" xmlns="http://www.topografix.com/GPX/1/1">\n';
  vis.forEach(f=>{const p=f.properties,c=f.geometry.coordinates;
    const nm=(p.name||(p.elev_ft+'ft pk (P'+p.prom_ft+')'))
      .replace(/&/g,'&amp;').replace(/</g,'&lt;');
    g+=`  <wpt lat="${c[1]}" lon="${c[0]}"><ele>${(p.elev_ft*0.3048).toFixed(1)}</ele>`+
       `<name>${nm}</name><cmt>elev ${p.elev_ft} ft, prom ${p.prom_ft} ft, ${p.cls}</cmt>`+
       `<sym>Summit</sym></wpt>\n`;});
  g+='</gpx>\n';
  download('i90_peaks.gpx',g,'application/gpx+xml');
}
</script></body></html>
"""
