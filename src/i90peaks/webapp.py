"""Generate the standalone interactive web app (one self-contained HTML file).

The app maps every >= 250 ft-prominence peak along I-90 (Seattle -> Columbia
River), highlights the *first-row* peaks, draws each peak's summit cap (the top
250 ft of its massif), and explains every verdict: select a peak to see the
straight approach from I-90 and its terrain profile, with the cap entry or the
blocking peak/ridge marked.

Optional layers (completed summits, GPS tracks, planned routes) are injected as
GeoJSON so later phases can reuse the same page.
"""
from __future__ import annotations

import json

from . import config


def _clean_name(v) -> str:
    return "" if v is None or str(v) in ("", "nan", "None") else str(v)


def _peaks_geojson(classified) -> dict:
    feats = []
    for i, (_, p) in enumerate(classified.iterrows()):
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(p.lon, 5), round(p.lat, 5)]},
            "properties": {
                "id": i,
                "name": _clean_name(p.get("name")),
                "elev_ft": round(float(p.elev_ft)),
                # report the reference prominence for near-threshold peaks we rescued
                "prom_ft": round(max(float(p.prom_ft), float(p.get("prom_kirmse_ft") or 0)))
                if float(p.prom_ft) < config.PROM_MIN_FT else round(float(p.prom_ft)),
                "front": bool(p.frontrow),
                "near_mi": round(float(p.get("nearest_i90_m", 0)) / 1609.344, 1),
                "done": bool(p.get("done", False)),
                "done_by": p.get("done_by", []) if isinstance(p.get("done_by"), list) else [],
            },
        })
    return {"type": "FeatureCollection", "features": feats}


def _caps_geojson(caps, classified) -> dict:
    if caps is None:
        return {"type": "FeatureCollection", "features": []}
    front = set(classified.index[classified.frontrow].tolist())
    feats = []
    for idx, row in caps.iterrows():
        g = row.geometry.__geo_interface__
        feats.append({"type": "Feature", "geometry": _round_geom(g),
                      "properties": {"id": int(idx), "front": int(idx) in front}})
    return {"type": "FeatureCollection", "features": feats}


def _round_geom(g, nd=5):
    def r(c):
        return [round(c[0], nd), round(c[1], nd)] if isinstance(c[0], (int, float)) else [r(x) for x in c]
    return {"type": g["type"], "coordinates": r(g["coordinates"])}


def build_app(classified, highway, details=None, caps=None, tracks=None, routes=None,
              out_path=None, links=None) -> str:
    out_path = out_path or (config.PROCESSED / "i90_app.html")
    data = {
        "peaks": _peaks_geojson(classified),
        "highway": json.loads(highway.to_crs(4326).simplify(0.0002).to_json()),
        "details": details or [],
        "caps": _caps_geojson(caps, classified),
        "tracks": tracks or {"type": "FeatureCollection", "features": []},
        "routes": routes or {"type": "FeatureCollection", "features": []},
        "links": links or [],
    }
    html = _TEMPLATE.replace("__DATA__", json.dumps(data, separators=(",", ":")))
    with open(out_path, "w") as fh:
        fh.write(html)
    print(f"[webapp] wrote {out_path} ({len(html) / 1e6:.1f} MB)")
    return str(out_path)


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>I-90 Peaks</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Every peak with 250 ft of prominence directly adjacent to I-90, Seattle to the Columbia River.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root{
  --bg:#f4f1ea; --panel:#fbfaf6; --ink:#1c2422; --muted:#6b736f; --line:#e2ddd2;
  --front:#d4572a; --front-soft:rgba(212,87,42,.16); --behind:#8d9792; --hw:#2d5b86;
  --done:#2f8a5b; --track:#7a3fb0; --route:#0f7c86; --chip:#ece7dc; --shadow:0 10px 30px rgba(28,36,34,.12);
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#121615; --panel:#1a201e; --ink:#e9ece8; --muted:#9aa49f; --line:#2b3330;
  --front:#ff7a45; --front-soft:rgba(255,122,69,.2); --behind:#6d7772; --hw:#78a9d8;
  --done:#4cc489; --track:#b98cf0; --route:#4fc6cf; --chip:#242c29; --shadow:0 10px 30px rgba(0,0,0,.45);}}
:root[data-theme="dark"]{
  --bg:#121615; --panel:#1a201e; --ink:#e9ece8; --muted:#9aa49f; --line:#2b3330;
  --front:#ff7a45; --front-soft:rgba(255,122,69,.2); --behind:#6d7772; --hw:#78a9d8;
  --done:#4cc489; --track:#b98cf0; --route:#4fc6cf; --chip:#242c29; --shadow:0 10px 30px rgba(0,0,0,.45);}
*{box-sizing:border-box}
html,body{height:100%;margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.45 Inter,system-ui,sans-serif;-webkit-font-smoothing:antialiased}
.app{display:grid;grid-template-columns:380px 1fr;height:100%}
#map{height:100%;background:var(--bg)}
aside{background:var(--panel);border-right:1px solid var(--line);display:flex;flex-direction:column;min-height:0;z-index:2}
header{padding:20px 22px 14px;border-bottom:1px solid var(--line)}
.eyebrow{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-weight:600}
h1{font-family:Fraunces,Georgia,serif;font-weight:700;font-size:28px;line-height:1.1;margin:4px 0 6px}
.sub{color:var(--muted);font-size:13px}
.stats{display:flex;gap:10px;margin-top:14px}
.stat{flex:1;background:var(--chip);border-radius:12px;padding:9px 11px}
.stat b{display:block;font-family:Fraunces,serif;font-size:22px;line-height:1.1}
.stat span{font-size:11px;color:var(--muted)}
.bar{height:6px;border-radius:3px;background:var(--chip);margin-top:12px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--done);width:0;transition:width .6s}
.nav{display:flex;gap:6px;margin-top:12px;flex-wrap:wrap}
.nav a{font-size:12px;font-weight:600;color:var(--ink);text-decoration:none;background:var(--chip);
  padding:6px 10px;border-radius:999px}
.nav a:hover{background:var(--front-soft)}
.controls{padding:12px 22px;border-bottom:1px solid var(--line);display:grid;gap:10px}
.seg{display:flex;background:var(--chip);border-radius:10px;padding:3px}
.seg button{flex:1;border:0;background:transparent;color:var(--muted);font:600 12px Inter,sans-serif;
  padding:7px 4px;border-radius:8px;cursor:pointer}
.seg button.on{background:var(--panel);color:var(--ink);box-shadow:0 1px 3px rgba(0,0,0,.12)}
input[type=search]{width:100%;border:1px solid var(--line);background:var(--panel);color:var(--ink);
  border-radius:10px;padding:8px 11px;font:inherit}
.range{display:flex;align-items:center;gap:10px;font-size:12px;color:var(--muted)}
.range input{flex:1;accent-color:var(--front)}
.toggles{display:flex;gap:14px;font-size:12px;color:var(--muted);flex-wrap:wrap}
.toggles label{display:flex;align-items:center;gap:5px;cursor:pointer}
.toggles input{accent-color:var(--front)}
#list{overflow:auto;flex:1;min-height:0}
.pk{display:grid;grid-template-columns:14px 1fr auto;gap:10px;align-items:center;padding:9px 22px;
  border-bottom:1px solid var(--line);cursor:pointer}
.pk:hover,.pk.sel{background:var(--front-soft)}
.dot{width:10px;height:10px;border-radius:50%}
.pk .nm{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pk .meta{font-size:11.5px;color:var(--muted)}
.pk .el{font-variant-numeric:tabular-nums;font-size:12px;color:var(--muted);text-align:right}
.foot{padding:10px 22px;border-top:1px solid var(--line);display:flex;gap:8px;align-items:center}
.btn{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:9px;
  padding:7px 11px;font:600 12px Inter,sans-serif;cursor:pointer}
.btn:hover{border-color:var(--front)}
.foot .sp{flex:1}
#card{position:absolute;right:16px;top:16px;width:360px;max-width:calc(100% - 32px);background:var(--panel);
  border-radius:16px;box-shadow:var(--shadow);padding:16px 18px;z-index:500;display:none;border:1px solid var(--line)}
#card h2{font-family:Fraunces,serif;font-size:22px;margin:0 28px 2px 0;line-height:1.15}
#card .x{position:absolute;right:12px;top:10px;border:0;background:none;color:var(--muted);font-size:20px;cursor:pointer}
.kv{display:flex;gap:16px;margin:8px 0 10px}
.kv div{font-size:11px;color:var(--muted)} .kv b{display:block;font-size:16px;color:var(--ink);font-variant-numeric:tabular-nums}
.verdict{font-size:12.5px;padding:8px 10px;border-radius:10px;margin-top:8px}
.verdict.ok{background:var(--front-soft)} .verdict.no{background:var(--chip)}
.verdict a{color:var(--front);font-weight:600;cursor:pointer}
.legend{display:flex;gap:10px;font-size:11px;color:var(--muted);margin-top:6px;flex-wrap:wrap}
.legend i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px;vertical-align:middle}
.leaflet-container{font:inherit;background:var(--bg)}
.leaflet-popup-content-wrapper,.leaflet-popup-tip{background:var(--panel);color:var(--ink)}
.leaflet-tooltip{background:var(--panel);color:var(--ink);border:1px solid var(--line);box-shadow:var(--shadow)}
.theme{position:absolute;left:12px;bottom:24px;z-index:500}
@media (max-width:820px){
  .app{grid-template-columns:1fr;grid-template-rows:52vh 1fr}
  aside{order:2;border-right:0;border-top:1px solid var(--line)}
  header{padding:14px 16px 10px} h1{font-size:22px}
  .controls,.pk,.foot{padding-left:16px;padding-right:16px}
  #card{left:16px;right:16px;top:auto;bottom:16px;width:auto;max-height:45vh;overflow:auto}
}
</style></head><body>
<div class="app">
<aside>
  <header>
    <div class="eyebrow">Running challenge · Seattle → Columbia River</div>
    <h1>The I-90 Peaks</h1>
    <div class="sub">Every summit with ≥250 ft of prominence that stands in the first row along
      I-90, with no other qualifying peak or ridge between it and the highway.</div>
    <div class="stats">
      <div class="stat"><b id="s_front">–</b><span>first-row peaks</span></div>
      <div class="stat"><b id="s_done">–</b><span>summited</span></div>
      <div class="stat"><b id="s_gain">–</b><span>to go</span></div>
    </div>
    <div class="bar"><i id="s_bar"></i></div>
    <div class="nav" id="nav"></div>
  </header>
  <div class="controls">
    <div class="seg" id="seg">
      <button data-v="front" class="on">First row</button>
      <button data-v="todo">To do</button>
      <button data-v="done">Done</button>
      <button data-v="all">All peaks</button>
    </div>
    <input type="search" id="q" placeholder="Search peaks by name…">
    <div class="range">Prominence ≥ <b id="pval">250</b> ft
      <input id="prom" type="range" min="250" max="3000" step="50" value="250"></div>
    <div class="toggles">
      <label title="visible from zoom 11"><input type="checkbox" id="t_caps" checked> summit caps</label>
      <label><input type="checkbox" id="t_tracks" checked> my tracks</label>
      <label><input type="checkbox" id="t_routes" checked> planned routes</label>
    </div>
  </div>
  <div id="list"></div>
  <div class="foot"><span class="sub" id="count"></span><span class="sp"></span>
    <button class="btn" onclick="dl('gpx')">GPX</button>
    <button class="btn" onclick="dl('geojson')">GeoJSON</button></div>
</aside>
<div style="position:relative;min-height:0">
  <div id="map"></div>
  <div id="card"><button class="x" onclick="closeCard()">×</button><div id="cardBody"></div></div>
  <button class="btn theme" id="themeBtn" title="Toggle light/dark">◐</button>
</div>
</div>
<script>
const D=__DATA__;
const P=D.peaks.features, DET=D.details;
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const nameOf=p=>p.name||`Pt ${p.elev_ft}`;
const fmt=n=>n.toLocaleString();

// ---- header stats
const front=P.filter(f=>f.properties.front), done=front.filter(f=>f.properties.done);
document.getElementById('s_front').textContent=front.length;
document.getElementById('s_done').textContent=done.length;
document.getElementById('s_gain').textContent=front.length-done.length;
requestAnimationFrame(()=>document.getElementById('s_bar').style.width=(100*done.length/Math.max(1,front.length))+'%');
document.getElementById('nav').innerHTML=D.links.map(l=>`<a href="${l.href}">${l.label}</a>`).join('');
document.getElementById('prom').max=Math.ceil(Math.max(...P.map(f=>f.properties.prom_ft))/50)*50;

// ---- map
const map=L.map('map',{zoomControl:false,preferCanvas:true});
L.control.zoom({position:'bottomright'}).addTo(map);
const bases={
  'Terrain':L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'Esri, USGS'}),
  'Topo (contours)':L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',{maxZoom:17,attribution:'© OpenTopoMap © OSM'}),
  'Satellite':L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'Esri'}),
  'Dark':L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{maxZoom:19,attribution:'© CARTO © OSM'}),
};
const dark=matchMedia('(prefers-color-scheme: dark)').matches;
(dark?bases['Dark']:bases['Terrain']).addTo(map);
L.control.layers(bases,null,{position:'topleft'}).addTo(map);

const hwLayer=L.geoJSON(D.highway,{style:()=>({color:css('--hw'),weight:4,opacity:.85})}).addTo(map);
map.fitBounds(hwLayer.getBounds(),{padding:[20,20]});
const capLayer=L.geoJSON(D.caps,{filter:f=>f.properties.front,interactive:false,
  style:()=>({color:css('--front'),weight:1,opacity:.6,fillColor:css('--front'),fillOpacity:.13})}).addTo(map);
const trackLayer=L.geoJSON(D.tracks,{style:f=>({color:css('--track'),weight:3,opacity:.8}),
  onEachFeature:(f,l)=>l.bindTooltip(f.properties.name||'track',{sticky:true})}).addTo(map);
const routeLayer=L.geoJSON(D.routes,{style:()=>({color:css('--route'),weight:3.5,opacity:.9,dashArray:'7 6'}),
  onEachFeature:(f,l)=>l.bindPopup(`<b>${f.properties.name||'Planned route'}</b><br>${f.properties.desc||''}`)}).addTo(map);
const pickLayer=L.layerGroup().addTo(map);
const peakLayer=L.layerGroup().addTo(map);

let mode='front', selected=null;
const radius=p=>Math.max(3.5,Math.min(12,2.5+Math.sqrt(p)/9));
function colorOf(p){return p.done?css('--done'):p.front?css('--front'):css('--behind');}
function visible(){
  const minP=+document.getElementById('prom').value, q=document.getElementById('q').value.trim().toLowerCase();
  return P.filter(f=>{const p=f.properties;
    if(p.prom_ft<minP) return false;
    if(q && !nameOf(p).toLowerCase().includes(q)) return false;
    if(mode==='front') return p.front;
    if(mode==='todo') return p.front&&!p.done;
    if(mode==='done') return p.done;
    return true;});
}
function render(){
  peakLayer.clearLayers();
  const vis=visible();
  const markers=[...vis].sort((a,b)=>a.properties.front-b.properties.front);
  markers.forEach(f=>{const p=f.properties,c=f.geometry.coordinates,col=colorOf(p);
    const m=L.circleMarker([c[1],c[0]],{radius:radius(p.prom_ft),color:p.front?'#fff':col,weight:p.front?1.5:1,
      fillColor:col,fillOpacity:p.front?.95:.55});
    m.bindTooltip(`<b>${nameOf(p)}</b><br>${fmt(p.elev_ft)} ft · P${fmt(p.prom_ft)}`,{direction:'top',offset:[0,-4]});
    m.on('click',()=>select(p.id,false));
    m.addTo(peakLayer);});
  const sorted=[...vis].sort((a,b)=>b.properties.prom_ft-a.properties.prom_ft);
  document.getElementById('list').innerHTML=sorted.map(f=>{const p=f.properties;
    return `<div class="pk${selected===p.id?' sel':''}" data-id="${p.id}"><span class="dot" style="background:${colorOf(p)}"></span>
      <div><div class="nm">${p.done?'✓ ':''}${nameOf(p)}</div><div class="meta">P${fmt(p.prom_ft)} ft · ${p.near_mi} mi from I-90</div></div>
      <div class="el">${fmt(p.elev_ft)}′</div></div>`;}).join('');
  document.getElementById('count').textContent=`${vis.length} peaks`;
}
document.getElementById('list').addEventListener('click',e=>{const r=e.target.closest('.pk'); if(r) select(+r.dataset.id,true);});
document.querySelectorAll('#seg button').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('#seg button').forEach(x=>x.classList.remove('on'));b.classList.add('on');mode=b.dataset.v;render();});
document.getElementById('q').addEventListener('input',render);
document.getElementById('prom').addEventListener('input',e=>{document.getElementById('pval').textContent=e.target.value;render();});
const tog=(id,layer)=>document.getElementById(id).addEventListener('change',e=>e.target.checked?layer.addTo(map):map.removeLayer(layer));
// caps clutter the overview (flat lowland hills have huge caps): show from zoom 11
const capsOn=()=>document.getElementById('t_caps').checked&&map.getZoom()>=11;
const syncCaps=()=>capsOn()?capLayer.addTo(map):map.removeLayer(capLayer);
map.on('zoomend',syncCaps);document.getElementById('t_caps').addEventListener('change',syncCaps);syncCaps();tog('t_tracks',trackLayer);tog('t_routes',routeLayer);

// ---- detail card
function profileSVG(d){
  const z=d.z,n=z.length,W=320,H=120,px=6,py=10;
  const vals=z.filter(v=>v!=null); if(vals.length<2) return '';
  const mn=Math.min(...vals),mx=Math.max(...vals),span=Math.max(1,mx-mn);
  const X=i=>px+(W-2*px)*i/(n-1), Y=v=>H-py-(H-2*py)*(v-mn)/span;
  let pts=[];z.forEach((v,i)=>{if(v!=null)pts.push(X(i).toFixed(1)+','+Y(v).toFixed(1));});
  const col=d.ok?css('--front'):css('--behind');
  const area=`M${X(0)},${H} L${pts.join(' L')} L${X(n-1)},${H} Z`;
  const k=Math.round(d.stop*(n-1)), xs=X(k);
  let s=`<svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block;margin-top:8px">`+
    `<path d="${area}" fill="${col}" opacity=".16"/><polyline points="${pts.join(' ')}" fill="none" stroke="${col}" stroke-width="2"/>`+
    `<line x1="${xs}" x2="${xs}" y1="0" y2="${H}" stroke="${d.ok?col:'#c0392b'}" stroke-dasharray="3 3"/>`+
    `<circle cx="${X(0)}" cy="${Y(z[0]??mn)}" r="4" fill="${css('--hw')}"/>`+
    `<circle cx="${X(n-1)}" cy="${Y(z[n-1]??mx)}" r="4" fill="${col}"/></svg>`;
  return s+`<div class="legend"><span><i style="background:${css('--hw')}"></i>I-90</span>`+
    `<span><i style="background:${d.ok?col:'#c0392b'}"></i>${d.ok?'enters summit cap':'blocked here'}</span>`+
    `<span><i style="background:${col}"></i>summit</span><span>${(d.len/1609.344).toFixed(1)} mi line</span></div>`;
}
function select(id,fly){
  selected=id; const f=P[id],p=f.properties,d=DET[id],c=f.geometry.coordinates;
  pickLayer.clearLayers();
  if(d){const h=[d.h[1],d.h[0]],s=[d.s[1],d.s[0]],e=[h[0]+(s[0]-h[0])*d.stop,h[1]+(s[1]-h[1])*d.stop];
    L.polyline([h,e],{color:d.ok?css('--front'):'#c0392b',weight:3.5}).addTo(pickLayer);
    L.polyline([e,s],{color:css('--muted'),weight:2,dashArray:'4 5'}).addTo(pickLayer);
    L.circleMarker(h,{radius:6,color:'#fff',weight:2,fillColor:css('--hw'),fillOpacity:1}).addTo(pickLayer);
    if(!d.ok) L.circleMarker(e,{radius:6,color:'#fff',weight:2,fillColor:'#c0392b',fillOpacity:1}).addTo(pickLayer);
    if(fly) map.flyToBounds(L.latLngBounds([h,s]).pad(.35),{duration:.8});
  } else if(fly) map.flyTo([c[1],c[0]],13);
  let why;
  if(p.front) why=`<div class="verdict ok"><b>First row.</b> A straight line from I-90 reaches this peak's top-250 ft cap without crossing another qualifying peak or any ground higher than the summit.</div>`;
  else if(d&&d.kind==='peak'&&d.by>=0) why=`<div class="verdict no"><b>Behind.</b> Every approach from I-90 first crosses the cap of <a onclick="select(${d.by},true)">${nameOf(P[d.by].properties)}</a> (P${fmt(P[d.by].properties.prom_ft)}).</div>`;
  else if(d&&d.kind==='ridge') why=`<div class="verdict no"><b>Behind.</b> Every approach from I-90 crosses ridge ground higher than this summit.</div>`;
  else why=`<div class="verdict no"><b>Behind.</b> No clean approach from I-90.</div>`;
  if(p.done) why+=`<div class="verdict ok" style="background:color-mix(in srgb,var(--done) 18%,transparent)"><b>✓ Summited</b>${p.done_by.length?' on '+p.done_by.slice(0,4).join(', '):''}</div>`;
  document.getElementById('cardBody').innerHTML=
    `<div class="eyebrow">${p.front?'First-row peak':'Behind the first row'}</div><h2>${nameOf(p)}</h2>`+
    `<div class="kv"><div><b>${fmt(p.elev_ft)}′</b>elevation</div><div><b>${fmt(p.prom_ft)}′</b>prominence</div><div><b>${p.near_mi} mi</b>to I-90</div></div>`+
    (d?profileSVG(d):'')+why+
    `<div class="legend"><a class="btn" style="text-decoration:none" target="_blank" href="https://caltopo.com/map.html#ll=${c[1]},${c[0]}&z=15&b=mbt">Open in CalTopo ↗</a></div>`;
  document.getElementById('card').style.display='block';
  render();
}
function closeCard(){document.getElementById('card').style.display='none';pickLayer.clearLayers();selected=null;render();}

// ---- theme toggle
document.getElementById('themeBtn').onclick=()=>{
  const r=document.documentElement, cur=r.dataset.theme||(dark?'dark':'light');
  r.dataset.theme=cur==='dark'?'light':'dark';
  hwLayer.setStyle({color:css('--hw')});capLayer.setStyle({color:css('--front'),fillColor:css('--front')});render();};

// ---- exports
function download(name,text,mime){const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([text],{type:mime}));a.download=name;a.click();}
function dl(kind){
  const vis=visible();
  if(kind==='geojson'){download('i90_peaks.geojson',JSON.stringify({type:'FeatureCollection',features:vis}),'application/geo+json');return;}
  const esc=s=>s.replace(/&/g,'&amp;').replace(/</g,'&lt;');
  let g='<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="i90peaks" xmlns="http://www.topografix.com/GPX/1/1">\n';
  vis.forEach(f=>{const p=f.properties,c=f.geometry.coordinates;
    g+=`  <wpt lat="${c[1]}" lon="${c[0]}"><ele>${(p.elev_ft*0.3048).toFixed(1)}</ele><name>${esc(nameOf(p))}</name>`+
       `<cmt>elev ${p.elev_ft} ft, prom ${p.prom_ft} ft${p.front?', first row':''}${p.done?', done':''}</cmt><sym>Summit</sym></wpt>\n`;});
  download('i90_peaks.gpx',g+'</gpx>\n','application/gpx+xml');
}
render();

// ---- deep links from the analysis page: #route=ID or #track=ID
function focusFromHash(){
  const m=location.hash.match(/^#(route|track)=(\d+)$/); if(!m) return;
  const layer=m[1]==='route'?routeLayer:trackLayer, key=m[1]==='route'?'route_id':'id';
  layer.eachLayer(l=>{
    const hit=String(l.feature.properties[key])===m[2];
    l.setStyle({weight:hit?6:3,opacity:hit?1:.35});
    if(hit){map.flyToBounds(l.getBounds().pad(.25),{duration:.8});l.openPopup?.();}
  });
}
addEventListener('hashchange',focusFromHash); focusFromHash();
</script></body></html>
"""
