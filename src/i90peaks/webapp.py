"""Generate a standalone interactive web app (single self-contained HTML).

Beyond the map of first-row vs occluded peaks, the app *explains the computation*:
click any peak to draw the straight approach line from the nearest I-90 point to its
summit and a live elevation cross-section, with the blocking ridge (if any) marked --
so it's visible why each peak is first row or behind a ridge.
"""
from __future__ import annotations

import json

from . import config

M_PER_FT = 0.3048


def _peaks_geojson(classified) -> dict:
    feats = []
    for i, (_, p) in enumerate(classified.iterrows()):
        cls = "front" if bool(p.get("frontrow", False)) else "behind"
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(p.lon, 6), round(p.lat, 6)]},
            "properties": {
                "id": i,
                "elev_ft": round(float(p.elev_ft)),
                "prom_ft": round(float(p.prom_ft)),
                "cls": cls,
                "name": (str(p.get("name")) if p.get("name") not in (None, "", "nan") else ""),
            },
        })
    return {"type": "FeatureCollection", "features": feats}


def build_app(classified, highway, details=None, out_path=None) -> str:
    out_path = out_path or (config.PROCESSED / "i90_app.html")
    peaks_gj = _peaks_geojson(classified)
    hw_gj = json.loads(highway.to_crs(4326).to_json())
    center = [float(classified.lat.mean()), float(classified.lon.mean())]
    max_prom = int(classified.prom_ft.max())

    html = _TEMPLATE
    html = html.replace("__PEAKS__", json.dumps(peaks_gj))
    html = html.replace("__HIGHWAY__", json.dumps(hw_gj))
    html = html.replace("__DETAILS__", json.dumps(details or []))
    html = html.replace("__CENTER__", json.dumps(center))
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
    font:13px/1.4 system-ui,sans-serif;max-width:290px}
  #panel h3{margin:0 0 6px;font-size:14px}
  .row{margin:7px 0}
  button{cursor:pointer;border:0;border-radius:6px;padding:6px 9px;font-size:12px;
    background:#2c7fb8;color:#fff;margin-right:5px}
  button.alt{background:#555}
  input[type=range]{width:100%}
  .sw{display:inline-block;width:11px;height:11px;border-radius:50%;
    margin-right:4px;vertical-align:middle}
  .muted{color:#666;font-size:11px}
  #chart{margin-top:6px}
  #chart .ttl{font-size:12px;font-weight:600;margin-bottom:2px}
</style></head><body>
<div id="map"></div>
<div id="panel">
  <h3>I-90 First-Row Peaks</h3>
  <div class="muted">Seattle &rarr; Columbia River &middot; &ge;250&prime; prominence.
    Click a peak to see why it's classified.</div>
  <div class="row">
    <label><input type="checkbox" class="cls" value="front" checked>
      <span class="sw" style="background:#2ca02c"></span>First row &mdash; clear approach
      (<b id="n_front">0</b>)</label><br>
    <label><input type="checkbox" class="cls" value="behind">
      <span class="sw" style="background:#999"></span>Behind a ridge &ge;250&prime;
      (<b id="n_behind">0</b>)</label>
  </div>
  <div class="row">Min prominence: <b id="pval">250</b> ft
    <input id="prom" type="range" min="250" max="__MAXPROM__" step="50" value="250"></div>
  <div class="row">
    <label><input type="checkbox" id="lines"> show approach lines (visible peaks)</label>
  </div>
  <div class="row muted">Showing <b id="count">0</b> peaks</div>
  <div id="chart"></div>
  <div class="row">
    <button onclick="dl('gpx')">Export GPX</button>
    <button class="alt" onclick="dl('geojson')">GeoJSON</button>
  </div>
  <div class="row muted">GPX/GeoJSON import directly into CalTopo. Export = visible peaks.</div>
</div>
<script>
const PEAKS=__PEAKS__, HIGHWAY=__HIGHWAY__, DETAILS=__DETAILS__, CENTER=__CENTER__;
const COLOR={front:'#2ca02c',behind:'#999'};
const LABEL={front:'FIRST ROW — clear approach from I-90',
             behind:'BEHIND a ridge ≥250 ft'};
const FT=3.280839895;
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

const layer=L.layerGroup().addTo(map);      // peak markers
const lineLayer=L.layerGroup().addTo(map);  // approach lines for all visible
const pickLayer=L.layerGroup().addTo(map);  // highlighted clicked approach
const radius=p=>Math.max(3,Math.min(11,2+Math.sqrt(p)/12));
const activeClasses=()=>new Set([...document.querySelectorAll('.cls:checked')].map(c=>c.value));
function visiblePeaks(){
  const minP=+document.getElementById('prom').value, cl=activeClasses();
  return PEAKS.features.filter(f=>f.properties.prom_ft>=minP && cl.has(f.properties.cls));
}
function lerp(a,b,t){return [a[0]+(b[0]-a[0])*t, a[1]+(b[1]-a[1])*t];}

function profileChart(d,nm){
  const z=d.z,n=z.length,W=262,H=120,pad=16;
  const vals=z.filter(v=>v!=null); if(vals.length<2) return '';
  const mn=Math.min(...vals),mx=Math.max(...vals),span=Math.max(1,mx-mn);
  const X=i=>pad+(W-2*pad)*i/(n-1), Y=v=>H-pad-(H-2*pad)*(v-mn)/span;
  let pts=''; z.forEach((v,i)=>{if(v!=null)pts+=X(i).toFixed(1)+','+Y(v).toFixed(1)+' ';});
  const col=d.blk?'#d62728':'#2ca02c';
  let s=`<svg width=${W} height=${H} style="background:#f6f6f6;border-radius:6px">`;
  // summit reference level
  const zs=z[n-1]; if(zs!=null) s+=`<line x1=${pad} y1=${Y(zs)} x2=${W-pad} y2=${Y(zs)} stroke=#ccc stroke-dasharray=2/>`;
  s+=`<polyline fill=none stroke=${col} stroke-width=2 points="${pts}"/>`;
  if(z[0]!=null) s+=`<circle cx=${X(0)} cy=${Y(z[0])} r=3.5 fill=#1f77b4/>`;            // road
  if(d.lo>0&&z[d.lo]!=null) s+=`<circle cx=${X(d.lo)} cy=${Y(z[d.lo])} r=2.5 fill=#888/>`; // valley low
  if(zs!=null) s+=`<circle cx=${X(n-1)} cy=${Y(zs)} r=3.5 fill=${col}/>`;                // summit
  if(d.blk&&d.bar>=0&&z[d.bar]!=null){
    s+=`<line x1=${X(d.bar)} y1=${pad} x2=${X(d.bar)} y2=${H-pad} stroke=#d62728 stroke-dasharray=3/>`;
    s+=`<circle cx=${X(d.bar)} cy=${Y(z[d.bar])} r=3.5 fill=#d62728/>`;
  }
  s+='</svg>';
  const verdict=d.blk
    ? '<b style="color:#d62728">behind a ridge</b> — the climb from the valley drops &ge;250 ft at the red line (a qualifying barrier between it and I-90)'
    : '<b style="color:#2ca02c">first row</b> — from the valley floor it climbs to the summit with no &ge;250 ft ridge in the way';
  return `<div class="ttl">${nm}</div>`+s+
    `<div class="muted"><span style="color:#1f77b4">●</span> nearest I-90 &nbsp;`+
    `<span style="color:#888">●</span> valley low &nbsp;`+
    `<span style="color:${col}">●</span> summit &middot; ${(d.len/1000).toFixed(1)} km approach<br>${verdict}</div>`;
}

function drawPick(f){
  pickLayer.clearLayers();
  const d=DETAILS[f.properties.id]; if(!d) return;
  const h=[d.h[1],d.h[0]], s=[d.s[1],d.s[0]], col=d.blk?'#d62728':'#2ca02c';
  L.polyline([h,s],{color:col,weight:3,opacity:.9}).addTo(pickLayer);
  L.circleMarker(h,{radius:5,color:'#1f77b4',fillColor:'#1f77b4',fillOpacity:1}).addTo(pickLayer);
  if(d.blk&&d.bar>=0){const b=lerp(h,s,d.bar/(d.z.length-1));
    L.circleMarker(b,{radius:5,color:'#d62728',fillColor:'#d62728',fillOpacity:1})
      .bindTooltip('blocking ridge').addTo(pickLayer);}
  const nm=f.properties.name||(f.properties.elev_ft+'ft pk');
  document.getElementById('chart').innerHTML=profileChart(d,nm+' — '+f.properties.elev_ft+' ft');
}

function render(){
  layer.clearLayers(); lineLayer.clearLayers();
  const vis=visiblePeaks(), showLines=document.getElementById('lines').checked;
  vis.forEach(f=>{
    const p=f.properties,c=f.geometry.coordinates,col=COLOR[p.cls];
    if(showLines){const d=DETAILS[p.id];
      if(d) L.polyline([[d.h[1],d.h[0]],[d.s[1],d.s[0]]],
        {color:col,weight:1,opacity:.25}).addTo(lineLayer);}
    const nm=p.name||(p.elev_ft+'ft pk');
    const m=L.circleMarker([c[1],c[0]],{radius:radius(p.prom_ft),color:col,weight:1,
      fillColor:col,fillOpacity:.85}).bindPopup(
      `<b>${nm}</b><br>elev ${p.elev_ft} ft<br>prominence ${p.prom_ft} ft`+
      `<br><b style="color:${col}">${LABEL[p.cls]}</b>`);
    m.on('click',()=>drawPick(f));
    m.addTo(layer);
  });
  document.getElementById('count').textContent=vis.length;
}
document.getElementById('prom').addEventListener('input',e=>{
  document.getElementById('pval').textContent=e.target.value;render();});
document.querySelectorAll('.cls').forEach(c=>c.addEventListener('change',render));
document.getElementById('lines').addEventListener('change',render);
render();

function download(name,text,mime){
  const a=document.createElement('a');
  a.href='data:'+mime+';charset=utf-8,'+encodeURIComponent(text);a.download=name;a.click();
}
function dl(kind){
  const vis=visiblePeaks();
  if(kind==='geojson'){download('i90_peaks.geojson',
    JSON.stringify({type:'FeatureCollection',features:vis}),'application/json');return;}
  let g='<?xml version="1.0" encoding="UTF-8"?>\n'+
    '<gpx version="1.1" creator="i90peaks" xmlns="http://www.topografix.com/GPX/1/1">\n';
  vis.forEach(f=>{const p=f.properties,c=f.geometry.coordinates;
    const nm=(p.name||(p.elev_ft+'ft pk (P'+p.prom_ft+')')).replace(/&/g,'&amp;').replace(/</g,'&lt;');
    g+=`  <wpt lat="${c[1]}" lon="${c[0]}"><ele>${(p.elev_ft*0.3048).toFixed(1)}</ele>`+
       `<name>${nm}</name><cmt>elev ${p.elev_ft} ft, prom ${p.prom_ft} ft, ${p.cls}</cmt>`+
       `<sym>Summit</sym></wpt>\n`;});
  g+='</gpx>\n';
  download('i90_peaks.gpx',g,'application/gpx+xml');
}
</script></body></html>
"""
