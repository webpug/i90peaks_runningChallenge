"""Generate the standalone interactive web app (one self-contained HTML file).

The app maps every >= 250 ft-prominence peak along I-90 (Seattle -> Columbia
River), highlights the *first-row* peaks, draws each peak's summit cap (the top
250 ft of its massif), and explains every verdict: select a peak to see the
straight approach from I-90 and its terrain profile, with the cap entry or the
blocking peak/ridge marked.

Optional layers (completed summits, GPS tracks, planned routes) are injected as
GeoJSON so later phases can reuse the same page. Served from theblacks.ai, the page
then loads the live state (runs uploaded as CalTopo GeoJSON, summits, drawn routes)
from /i90peaks/api/state and lets the owner upload runs and save routes drawn with
the built-in route tool (elevation from AWS terrain tiles, time from the pace model).
"""
from __future__ import annotations

import json

from . import config, promraster


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
                "access": p.get("access_note") or "",
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
              out_path=None, links=None, pace=None) -> str:
    out_path = out_path or (config.PROCESSED / "i90_app.html")
    data = {
        "peaks": _peaks_geojson(classified),
        "highway": json.loads(highway.to_crs(4326).simplify(0.0002).to_json()),
        "details": details or [],
        "caps": _caps_geojson(caps, classified),
        "tracks": tracks or {"type": "FeatureCollection", "features": []},
        "routes": routes or {"type": "FeatureCollection", "features": []},
        "links": links or [],
        "pace": pace,
        "prom": promraster.load_meta(),     # prominence-island raster, if built
    }
    html = (_TEMPLATE.replace("__LIVE_JS__", _LIVE_JS)
            .replace("__DATA__", json.dumps(data, separators=(",", ":"))))
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
  --done:#2f8a5b; --track:#7a3fb0; --route:#0f7c86; --drawn:#c2185b; --chip:#ece7dc; --shadow:0 10px 30px rgba(28,36,34,.12);
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#121615; --panel:#1a201e; --ink:#e9ece8; --muted:#9aa49f; --line:#2b3330;
  --front:#ff7a45; --front-soft:rgba(255,122,69,.2); --behind:#6d7772; --hw:#78a9d8;
  --done:#4cc489; --track:#b98cf0; --route:#4fc6cf; --drawn:#f06292; --chip:#242c29; --shadow:0 10px 30px rgba(0,0,0,.45);}}
:root[data-theme="dark"]{
  --bg:#121615; --panel:#1a201e; --ink:#e9ece8; --muted:#9aa49f; --line:#2b3330;
  --front:#ff7a45; --front-soft:rgba(255,122,69,.2); --behind:#6d7772; --hw:#78a9d8;
  --done:#4cc489; --track:#b98cf0; --route:#4fc6cf; --drawn:#f06292; --chip:#242c29; --shadow:0 10px 30px rgba(0,0,0,.45);}
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
.nav a:hover,.nav button:hover{background:var(--front-soft)}
.nav button{font:600 12px Inter,sans-serif;color:var(--ink);background:var(--chip);border:0;
  padding:6px 10px;border-radius:999px;cursor:pointer}
.nav button.on{background:var(--ink);color:var(--panel)}
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
.panel{position:absolute;right:16px;top:16px;width:380px;max-width:calc(100% - 32px);max-height:calc(100% - 32px);
  overflow:auto;background:var(--panel);border-radius:16px;box-shadow:var(--shadow);padding:16px 18px;z-index:600;
  display:none;border:1px solid var(--line)}
.panel h2{font-family:Fraunces,serif;font-size:21px;margin:0 28px 4px 0;line-height:1.15}
.panel .x{position:absolute;right:12px;top:10px;border:0;background:none;color:var(--muted);font-size:20px;cursor:pointer}
.panel p{margin:6px 0;color:var(--muted);font-size:12.5px}
.field{width:100%;border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:9px;padding:7px 10px;font:inherit}
.row{display:flex;gap:8px;align-items:center;margin-top:8px;flex-wrap:wrap}
.btn.primary{background:var(--ink);color:var(--panel);border-color:var(--ink)}
.btn:disabled{opacity:.45;cursor:default}
.drop{border:1.5px dashed var(--line);border-radius:12px;padding:16px;text-align:center;color:var(--muted);
  font-size:12.5px;margin-top:10px;cursor:pointer}
.drop.over{border-color:var(--front);background:var(--front-soft)}
.runs{margin-top:10px;display:grid;gap:8px}
.run{border:1px solid var(--line);border-radius:11px;padding:8px 10px;display:grid;grid-template-columns:18px 1fr;gap:4px 8px}
.run input[type=text],.run input[type=date]{border:0;border-bottom:1px solid var(--line);background:transparent;color:var(--ink);
  font:600 13px Inter,sans-serif;padding:2px 0;width:100%}
.run input[type=date]{font-weight:400;font-size:12px;width:auto}
.run .meta{grid-column:2;font-size:11.5px;color:var(--muted)}
.chip{display:inline-block;background:var(--chip);border-radius:999px;padding:2px 8px;font-size:11.5px;margin:2px 3px 0 0}
.chip.done{background:color-mix(in srgb,var(--done) 22%,transparent)}
.msg{font-size:12.5px;margin-top:8px;color:var(--muted)} .msg.err{color:#c0392b}
.dstats{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin:10px 0 4px}
.dstats div{background:var(--chip);border-radius:10px;padding:6px 8px;font-size:10.5px;color:var(--muted)}
.dstats b{display:block;font-size:15px;color:var(--ink);font-variant-numeric:tabular-nums}
.vtx{width:12px;height:12px;border-radius:50%;background:var(--panel);border:2.5px solid var(--drawn);box-sizing:border-box}
.vtx.end{background:var(--drawn)}
.mid{width:10px;height:10px;border-radius:50%;background:var(--drawn);opacity:.35;border:0}
.mid:hover{opacity:.9}
.drawing #map{cursor:crosshair}
.kbd{font-size:11px;color:var(--muted)}
#promInfo{position:absolute;left:56px;bottom:24px;z-index:500;display:none;max-width:290px;background:var(--panel);
  border:1px solid var(--line);border-radius:12px;padding:8px 10px;box-shadow:var(--shadow);font-size:11.5px;color:var(--muted)}
#promInfo b{color:var(--ink)}
#promInfo .ramp{display:flex;margin:6px 0 2px;border-radius:4px;overflow:hidden}
#promInfo .ramp i{flex:1;height:8px}
#promInfo .ticks{display:flex;font-size:10px}
#promInfo .ticks span{flex:1}
#promInfo input{width:100%;margin:6px 0 0}
@media (max-width:820px){
  .app{grid-template-columns:1fr;grid-template-rows:52vh 1fr}
  aside{order:2;border-right:0;border-top:1px solid var(--line)}
  header{padding:14px 16px 10px} h1{font-size:22px}
  .controls,.pk,.foot{padding-left:16px;padding-right:16px}
  #card,.panel{left:16px;right:16px;top:auto;bottom:16px;width:auto;max-height:45vh;overflow:auto}
  /* drawing on a phone: give the map most of the screen and keep the tool small */
  .drawing .app{grid-template-rows:82vh 1fr}
  #drawPanel{left:8px;right:8px;bottom:8px;max-height:36vh;padding:10px 12px}
  #drawPanel .eyebrow,#drawPanel .kbd.help,#dNotes,#dProfile{display:none}
  .dstats{margin:6px 0 2px}
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
    <div class="nav"><button id="addRunsBtn">+ Add runs</button><button id="drawBtn">✎ Draw a route</button></div>
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
      <label><input type="checkbox" id="t_drawn" checked> drawn routes</label>
      <label title="the ground each peak rises above its key col, coloured by prominence"><input type="checkbox" id="t_prom"> prominence islands</label>
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
  <div id="promInfo"></div>
  <div class="panel" id="uploadPanel"><button class="x" onclick="closeUpload()">×</button>
    <div class="eyebrow">CalTopo → map</div><h2>Add runs</h2>
    <p>Export a track from CalTopo (Export → GeoJSON) and drop it here. Each line becomes a run; any first-row
      summit it tops out on (within 120 m of the summit and 40 ft of its height) is checked off. The ends of each run
      and anything near home are trimmed before the line is published.</p>
    <div id="upAuth"></div><div id="upBody"></div></div>
  <div class="panel" id="drawPanel"><button class="x" onclick="stopDraw()">×</button>
    <div class="eyebrow">Route tool</div>
    <input class="field" id="dName" placeholder="Route name" style="font:600 16px Fraunces,serif;margin-top:4px">
    <div class="dstats"><div><b id="dDist">0.0</b>miles</div><div><b id="dGain">0</b>ft gain</div>
      <div><b id="dLoss">0</b>ft loss</div><div><b id="dTime">–</b>est. hours</div></div>
    <div id="dProfile"></div><div id="dPeaks" style="margin-top:6px"></div>
    <div class="kbd help" style="margin-top:6px">Click the map to add points · drag points to move · drag a faint midpoint to
      insert · double-click or right-click a point to delete · Ctrl+Z undo</div>
    <div class="row"><label class="kbd"><input type="checkbox" id="dSnap" checked> snap to summits</label>
      <label class="kbd"><input type="checkbox" id="dOff"> mostly off-trail</label></div>
    <textarea class="field" id="dNotes" rows="2" placeholder="Notes (access, scramble, water…)" style="margin-top:8px"></textarea>
    <div class="row"><button class="btn" onclick="undo()">Undo</button><button class="btn" onclick="reverseRoute()">Reverse</button>
      <button class="btn" onclick="clearRoute()">Clear</button><span style="flex:1"></span>
      <button class="btn" onclick="exportDrawn()">GPX</button><button class="btn primary" id="dSave" onclick="saveDrawn()">Save</button></div>
    <div class="msg" id="dMsg"></div></div>
  <button class="btn theme" id="themeBtn" title="Toggle light/dark">◐</button>
</div>
</div>
<script>
const D=__DATA__;
const P=D.peaks.features, DET=D.details;
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const nameOf=p=>p.name||`Pt ${p.elev_ft}`;
const fmt=n=>n.toLocaleString();

const esc=s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
const API='/i90peaks/api';
let STATE=null;   // live state from the site (runs, summits, drawn routes); null = static page

// ---- header stats
function updateStats(){
  const front=P.filter(f=>f.properties.front), done=front.filter(f=>f.properties.done);
  document.getElementById('s_front').textContent=front.length;
  document.getElementById('s_done').textContent=done.length;
  document.getElementById('s_gain').textContent=front.length-done.length;
  requestAnimationFrame(()=>document.getElementById('s_bar').style.width=(100*done.length/Math.max(1,front.length))+'%');
}
updateStats();
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
  onEachFeature:trackPopup}).addTo(map);
function trackPopup(f,l){const p=f.properties;
  l.bindTooltip(esc(p.name||'run'),{sticky:true});
  l.bindPopup(()=>`<b>${esc(p.name||'Run')}</b><br>${esc(p.date||p.run_date||'')}${p.dist_mi?` · ${p.dist_mi} mi`:''}${p.gain_ft?` · ${fmt(Math.round(p.gain_ft))} ft`:''}`+
    (STATE?.owner&&p.uuid&&p.source==='caltopo'?`<br><a href="#" onclick="deleteRun('${p.uuid}');return false">Delete this run</a>`:''));}
const routeLayer=L.geoJSON(D.routes,{style:f=>({color:css('--route'),weight:3.5,opacity:.9,dashArray:f.properties.fallback?'2 6':'7 6'}),
  onEachFeature:(f,l)=>l.bindPopup(`<b>${esc(f.properties.name||'Planned route')}</b><br>${esc(f.properties.desc||'')}`+
    `<br><a href="#" onclick="editPlanned(${f.properties.route_id});return false">✎ Edit in the route tool</a>`)}).addTo(map);
const drawnLayer=L.geoJSON(null,{style:()=>({color:css('--drawn'),weight:4,opacity:.95}),
  onEachFeature:(f,l)=>{const p=f.properties;
    l.bindTooltip(esc(p.name),{sticky:true});
    l.bindPopup(()=>`<b>${esc(p.name)}</b><br>${p.dist_mi??'–'} mi · ${p.gain_ft!=null?fmt(Math.round(p.gain_ft)):'–'} ft · ~${p.est_hours??'–'} h`+
      (p.notes?`<br><i>${esc(p.notes)}</i>`:'')+`<br><a href="#" onclick="editDrawn('${p.id}');return false">✎ ${STATE?.owner?'Edit':'Open in route tool'}</a>`+
      ` · <a href="#" onclick="gpxOfDrawn('${p.id}');return false">GPX</a>`+
      (STATE?.owner?` · <a href="#" onclick="deleteDrawn('${p.id}');return false">Delete</a>`:''));}}).addTo(map);
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
    m.on('click',()=>{if(!drawing) select(p.id,false);});
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
map.on('zoomend',syncCaps);document.getElementById('t_caps').addEventListener('change',syncCaps);syncCaps();tog('t_tracks',trackLayer);tog('t_routes',routeLayer);tog('t_drawn',drawnLayer);

// ---- prominence islands: an index PNG (pixel RGB = peak id + 1, see promraster.py),
// coloured here by prominence and read back on hover to name the peak that owns the ground
const PROM_STOPS=[250,400,600,1000,2000,4000];
const PROM_COLS=['#fcfdbf','#feb078','#f1605d','#b63679','#721f81','#2c115f'];
const promCol=v=>{let k=0;while(k<PROM_STOPS.length-1&&v>=PROM_STOPS[k+1])k++;return PROM_COLS[k];};
let promLayer=null,promIdx=null,promOpacity=.6;
map.createPane('prom').style.zIndex=350;          // under the routes and markers
async function loadProm(){
  const img=new Image();
  img.src=/\.html$/.test(location.pathname)?'prominence.png':'/i90peaks/prominence.png';
  await img.decode();
  const [w,h]=[img.width,img.height],cv=document.createElement('canvas');cv.width=w;cv.height=h;
  const cx=cv.getContext('2d',{willReadFrequently:true});cx.drawImage(img,0,0);
  const px=cx.getImageData(0,0,w,h),d=px.data;promIdx=new Int32Array(w*h);
  const lut=P.map(f=>{const c=promCol(f.properties.prom_ft);return [1,3,5].map(i=>parseInt(c.slice(i,i+2),16));});
  for(let i=0,j=0;i<promIdx.length;i++,j+=4){
    const id=(d[j]<<16|d[j+1]<<8|d[j+2])-1;promIdx[i]=id;
    if(id<0){d[j+3]=0;continue;}
    const c=lut[id]||[128,128,128];d[j]=c[0];d[j+1]=c[1];d[j+2]=c[2];d[j+3]=255;}
  cx.putImageData(px,0,0);
  const url=URL.createObjectURL(await new Promise(r=>cv.toBlob(r)));
  promLayer=L.imageOverlay(url,D.prom.bounds,{pane:'prom',opacity:promOpacity,interactive:false});
}
function promAt(ll){
  if(!promIdx) return -1;
  const [[s,w],[n,e]]=D.prom.bounds,[W,H]=D.prom.size,pr=ll=>L.CRS.EPSG3857.project(ll);
  const a=pr(L.latLng(s,w)),b=pr(L.latLng(n,e)),p=pr(ll);
  const x=Math.floor((p.x-a.x)/(b.x-a.x)*W),y=Math.floor((b.y-p.y)/(b.y-a.y)*H);
  return x<0||y<0||x>=W||y>=H?-1:promIdx[y*W+x];
}
function promInfo(id){
  const box=document.getElementById('promInfo');
  const ramp=`<div class="ramp">${PROM_COLS.map(c=>`<i style="background:${c}"></i>`).join('')}</div>`+
    `<div class="ticks">${PROM_STOPS.map(v=>`<span>${fmt(v)}+</span>`).join('')}</div>`;
  let head='Ground above each peak\'s key col, coloured by its prominence (ft). Hover or tap to see whose it is.';
  if(id>=0){const p=P[id].properties;
    head=`<b>${esc(p.name||'Unnamed peak')}</b>'s ground · ${fmt(p.prom_ft)} ft prominence`+
      `${p.front?'':' · not first row'} · <a href="#" onclick="select(${id},true);return false">show</a>`;}
  box.innerHTML=head+ramp+`<input type="range" min="15" max="100" value="${promOpacity*100}" oninput="promOpacity=this.value/100;promLayer.setOpacity(promOpacity)" aria-label="opacity">`;
}
if(D.prom){
  const t=document.getElementById('t_prom'),box=document.getElementById('promInfo');
  t.addEventListener('change',async()=>{
    if(!t.checked){if(promLayer)map.removeLayer(promLayer);box.style.display='none';return;}
    if(!promLayer){box.style.display='block';box.textContent='Loading prominence…';await loadProm();}
    if(t.checked){promLayer.addTo(map);box.style.display='block';promInfo(-1);}
  });
  let last=-2;
  const hover=e=>{if(!t.checked||(typeof drawing!=='undefined'&&drawing))return;
    const id=promAt(e.latlng);if(id!==last){last=id;promInfo(id);}};
  map.on('mousemove',hover);map.on('click',hover);
}else document.getElementById('t_prom').parentElement.style.display='none';

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
  else if(d&&d.kind==='far_lowland') why=`<div class="verdict no"><b>Not counted.</b> Nothing ≥250 ft stands between it and I-90, but it is a lowland hill (under 1,500 ft) ${p.near_mi} mi from the freeway. Lowland hills only count within 4 mi.</div>`;
  else if(d&&d.kind==='ridge') why=`<div class="verdict no"><b>Behind.</b> Every approach from I-90 crosses ridge ground higher than this summit.</div>`;
  else why=`<div class="verdict no"><b>Behind.</b> No clean approach from I-90.</div>`;
  if(p.access) why+=`<div class="verdict no">⚠ On the ${esc(p.access)}.</div>`;
  if(p.done) why+=`<div class="verdict ok" style="background:color-mix(in srgb,var(--done) 18%,transparent)"><b>✓ Summited</b>${p.done_by.length?' on '+p.done_by.slice(0,4).map(esc).join(', '):''}</div>`;
  if(STATE?.owner&&p.front){
    const manual=(STATE.summits||[]).some(x=>x.peak_id===p.id&&x.how==='manual'&&!x.track_id);
    why+=`<div class="row">${manual?`<button class="btn" onclick="unmarkPeak(${p.id})">Remove hand-marked summit</button>`:
      `<input type="date" class="field" id="mDate" style="width:auto"><button class="btn" onclick="markPeak(${p.id})">✓ Mark summited</button>`}</div>`;}
  document.getElementById('cardBody').innerHTML=
    `<div class="eyebrow">${p.front?'First-row peak':'Behind the first row'}</div><h2>${nameOf(p)}</h2>`+
    `<div class="kv"><div><b>${fmt(p.elev_ft)}′</b>elevation</div><div><b>${fmt(p.prom_ft)}′</b>prominence</div><div><b>${p.near_mi} mi</b>to I-90</div></div>`+
    (d?profileSVG(d):'')+why+
    `<div class="legend"><a class="btn" style="text-decoration:none" target="_blank" href="https://caltopo.com/map.html#ll=${c[1]},${c[0]}&z=15&b=mbt">Open in CalTopo ↗</a>`+
    `<button class="btn" onclick="drawTo(${p.id})">✎ Draw a route here</button></div>`;
  hidePanels();
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
  const layer=m[1]==='route'?routeLayer:trackLayer;
  // track ids are the analysis page's; once live state replaces the layer, match on the run key
  const want=m[1]==='route'?f=>String(f.properties.route_id)===m[2]:
    f=>String(f.properties.id)===m[2]||f.properties.key===D.tracks.features.find(t=>String(t.properties.id)===m[2])?.properties.key;
  layer.eachLayer(l=>{
    const hit=want(l.feature);
    l.setStyle({weight:hit?6:3,opacity:hit?1:.35});
    if(hit){map.flyToBounds(l.getBounds().pad(.25),{duration:.8});l.openPopup?.();}
  });
}
addEventListener('hashchange',focusFromHash); focusFromHash();
__LIVE_JS__
</script></body></html>
"""

# Live layer: everything that needs theblacks.ai (state, uploads, saving). The
# route tool itself also works offline except for saving.
_LIVE_JS = r"""
// ================= live state (when served from theblacks.ai) =================
const $=id=>document.getElementById(id);
const fmtDate=s=>s?new Date(String(s).slice(0,10)+'T12:00:00').toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'}):'';
async function api(path,opt={}){
  const r=await fetch(API+path,{credentials:'same-origin',cache:'no-store',...opt,
    headers:{'content-type':'application/json'},body:opt.body&&JSON.stringify(opt.body)});
  const j=await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(j.error||r.statusText);
  return j;
}
async function loadState(){
  try{STATE=await api('/state');}catch(e){return;}   // opened as a file: keep the built-in data
  const by={};
  STATE.summits.forEach(x=>(by[x.peak_id]??=[]).push(x));
  P.forEach(f=>{const p=f.properties,ss=by[p.id]||[];
    p.done=p.front&&ss.length>0;
    p.done_by=[...new Set(ss.map(x=>fmtDate(x.summit_date)+(x.how==='manual'?' (marked by hand)':'')))];});
  trackLayer.clearLayers();
  trackLayer.addData({type:'FeatureCollection',features:STATE.tracks.map(t=>({type:'Feature',geometry:t.geometry,
    properties:{uuid:t.id,key:t.key,source:t.source,name:t.name,date:fmtDate(t.run_date),dist_mi:t.dist_mi,gain_ft:t.gain_ft}}))});
  drawnLayer.clearLayers();
  drawnLayer.addData({type:'FeatureCollection',features:STATE.drawn.map(({geometry,...d})=>({type:'Feature',geometry,properties:d}))});
  updateStats(); render(); focusFromHash();
  if(selected!=null&&$('card').style.display==='block') select(selected,false);
  if($('uploadPanel').style.display==='block') renderUpload();
}
async function signIn(after){
  const pw=$('pw')?.value; if(!pw) return;
  try{await api('/login',{method:'POST',body:{password:pw}});}catch(e){note(e.message,true);return;}
  STATE.owner=true; renderUpload(); after?.();
}
function note(t,err,id){const el=$(id||(drawing?'dMsg':'upMsg')); if(el){el.textContent=t;el.className='msg'+(err?' err':'');}}
const pwBox=(after)=>`<div class="row"><input type="password" class="field" id="pw" placeholder="Owner password" style="flex:1"
  onkeydown="if(event.key==='Enter')signIn(${after||''})"><button class="btn primary" onclick="signIn(${after||''})">Sign in</button></div>`;

// ---- hand-marked summits, run deletion
async function markPeak(id){
  try{await api('/summits',{method:'POST',body:{peak_id:id,summit_date:$('mDate')?.value||null}});}catch(e){alert(e.message);return;}
  await loadState();
}
async function unmarkPeak(id){
  try{await api('/summits?peak_id='+id,{method:'DELETE'});}catch(e){alert(e.message);return;}
  await loadState();
}
async function deleteRun(uuid){
  if(!confirm('Delete this run and the summits it checked off?')) return;
  try{await api('/runs?id='+uuid,{method:'DELETE'});}catch(e){alert(e.message);return;}
  map.closePopup(); await loadState();
}

// ================= upload CalTopo GeoJSON =================
function hidePanels(){$('card').style.display='none';$('uploadPanel').style.display='none';preview.clearLayers();}
const preview=L.layerGroup().addTo(map);
let pending=[];
$('addRunsBtn').onclick=()=>{if(drawing) stopDraw(); hidePanels(); $('uploadPanel').style.display='block'; renderUpload();};
function closeUpload(){$('uploadPanel').style.display='none';preview.clearLayers();pending=[];}
function renderUpload(){
  if(!STATE){$('upAuth').innerHTML='<p class="msg err">Uploading works on theblacks.ai/i90peaks.</p>';$('upBody').innerHTML='';return;}
  if(!STATE.owner){$('upAuth').innerHTML=pwBox()+'<div class="msg" id="upMsg"></div>';$('upBody').innerHTML='';return;}
  $('upAuth').innerHTML='';
  $('upBody').innerHTML=`<div class="drop" id="drop">Drop CalTopo <b>.json / .geojson</b> here, or click to choose</div>
    <input type="file" id="file" accept=".json,.geojson,application/geo+json,application/json" multiple hidden>
    <div class="runs" id="runs"></div><div class="row" id="upActions"></div><div class="msg" id="upMsg"></div>`;
  const drop=$('drop'),file=$('file');
  drop.onclick=()=>file.click();
  file.onchange=()=>readFiles(file.files);
  drop.ondragover=e=>{e.preventDefault();drop.classList.add('over');};
  drop.ondragleave=()=>drop.classList.remove('over');
  drop.ondrop=e=>{e.preventDefault();drop.classList.remove('over');readFiles(e.dataTransfer.files);};
  renderRuns();
}
function linesOf(gj,fallbackName){
  const out=[];
  const visit=(g,name)=>{if(!g) return;
    if(g.type==='LineString') out.push({name,lines:[g.coordinates]});
    else if(g.type==='MultiLineString') out.push({name,lines:g.coordinates});
    else if(g.type==='GeometryCollection') g.geometries.forEach(x=>visit(x,name));};
  if(gj.type==='FeatureCollection') gj.features.forEach((f,i)=>visit(f.geometry,f.properties?.title||f.properties?.name||`${fallbackName} ${i+1}`));
  else if(gj.type==='Feature') visit(gj.geometry,gj.properties?.title||gj.properties?.name||fallbackName);
  else visit(gj,fallbackName);
  return out;
}
const mOf=(a,b)=>map.distance([a[1],a[0]],[b[1],b[0]]);
function thinLine(l,step=5){const o=[l[0]];for(let i=1;i<l.length-1;i++) if(mOf(o[o.length-1],l[i])>=step) o.push(l[i]);o.push(l[l.length-1]);return o;}
async function readFiles(files){
  for(const f of files){
    let gj; try{gj=JSON.parse(await f.text());}catch(e){note(`${f.name}: not JSON`,true);continue;}
    for(const r of linesOf(gj,f.name.replace(/\.(geo)?json$/i,''))){
      const lines=r.lines.filter(l=>l.length>1).map(l=>thinLine(l));
      if(!lines.length) continue;
      const t=lines[0][0][3], hasT=t>1e11, hasZ=lines.every(l=>l.filter(c=>c.length>2&&Number.isFinite(c[2])).length>=l.length*.8);
      let dist=0; lines.forEach(l=>{for(let i=1;i<l.length;i++) dist+=mOf(l[i-1],l[i]);});
      pending.push({name:r.name,date:hasT?new Date(t).toISOString().slice(0,10):new Date().toISOString().slice(0,10),
        hasT,hasZ,lines,dist_mi:dist/1609.344,gain_ft:null,on:true,peaks:null});
    }
  }
  if(!pending.length){note('No lines found. Export the track from CalTopo as GeoJSON.',true);return;}
  preview.clearLayers();
  const b=L.latLngBounds([]);
  pending.forEach(r=>r.lines.forEach(l=>{const pl=L.polyline(l.map(c=>[c[1],c[0]]),{color:css('--drawn'),weight:3,dashArray:'5 5'}).addTo(preview);b.extend(pl.getBounds());}));
  map.flyToBounds(b.pad(.2),{duration:.6});
  // climb from the DEM when the export has no elevations
  for(const r of pending.filter(r=>!r.hasZ&&r.gain_ft==null)){
    const ll=r.lines.flatMap(l=>densify(l.map(c=>L.latLng(c[1],c[0])),30));
    r.gain_ft=climb(await Promise.all(ll.map(p=>elevAt(p.lat,p.lng))))[0]/0.3048;
  }
  renderRuns(); checkRuns();
}
const payload=r=>({name:r.name,date:r.date,lines:r.lines,gain_ft:r.gain_ft});
async function checkRuns(){
  note('Checking summits…');
  try{const j=await api('/runs',{method:'POST',body:{dry_run:true,runs:pending.map(payload)}});
    j.results.forEach((x,i)=>{pending[i].peaks=x.peak_names||[];pending[i].on=(x.peak_names||[]).length>0;if(x.gain_ft!=null)pending[i].gain_ft=x.gain_ft;});
    note('');}catch(e){note(e.message,true);}
  renderRuns();
}
function renderRuns(){
  const box=$('runs'); if(!box) return;
  box.innerHTML=pending.map((r,i)=>`<div class="run"><input type="checkbox" ${r.on?'checked':''} onchange="pending[${i}].on=this.checked;renderRuns()">
    <input type="text" value="${esc(r.name)}" onchange="pending[${i}].name=this.value">
    <div class="meta">${r.hasT?esc(fmtDate(r.date)):`<input type="date" value="${r.date}" onchange="pending[${i}].date=this.value">`}
      · ${r.dist_mi.toFixed(1)} mi${r.gain_ft!=null?` · ${fmt(Math.round(r.gain_ft))} ft`:''}</div>
    <div class="meta">${r.peaks==null?'checking…':r.peaks.length?r.peaks.map(n=>`<span class="chip done">▲ ${esc(n)}</span>`).join(''):
      'No first-row summit on this line, so it is left out unless you tick it.'}</div></div>`).join('');
  const n=pending.filter(r=>r.on).length;
  $('upActions').innerHTML=pending.length?`<button class="btn" onclick="pending=[];preview.clearLayers();renderRuns()">Clear</button><span style="flex:1"></span>
    <button class="btn primary" ${n?'':'disabled'} onclick="uploadRuns()">Upload ${n} run${n===1?'':'s'}</button>`:'';
}
async function uploadRuns(){
  const sel=pending.filter(r=>r.on);
  note('Uploading…');
  let j; try{j=await api('/runs',{method:'POST',body:{runs:sel.map(payload)}});}catch(e){note(e.message,true);return;}
  const before=new Set(P.filter(f=>f.properties.done).map(f=>f.properties.id));
  pending=[];preview.clearLayers();
  await loadState();
  const fresh=P.filter(f=>f.properties.done&&!before.has(f.properties.id)).map(f=>nameOf(f.properties));
  const errs=j.results.filter(x=>x.error).map(x=>`${x.name}: ${x.error}`);
  renderRuns();
  note(`Uploaded ${j.results.length-errs.length} run(s).`+(fresh.length?` New summits: ${fresh.join(', ')}.`:' No new summits.')+(errs.length?' '+errs.join('; '):''),errs.length>0);
}

// ================= route tool (CalTopo-style line drawing) =================
let drawing=false,pts=[],hist=[],editId=null,dLine=null,lastStats=null,statSeq=0,statTimer=null;
const dLayer=L.layerGroup().addTo(map), hoverDot=L.circleMarker([0,0],{radius:6,color:'#fff',weight:2,fillOpacity:1,interactive:false});
$('drawBtn').onclick=()=>drawing?stopDraw():startDraw();
function startDraw(o={}){
  hidePanels(); drawing=true; document.body.classList.add('drawing'); map.doubleClickZoom.disable();
  pts=(o.pts||[]).map(p=>L.latLng(p.lat,p.lng)); hist=[]; editId=o.id||null;
  $('dName').value=o.name||''; $('dNotes').value=o.notes||''; $('dOff').checked=!!o.off; note('',false,'dMsg');
  $('drawPanel').style.display='block'; $('drawBtn').classList.add('on'); map.invalidateSize(); redraw();
  if(pts.length>1) map.flyToBounds(L.latLngBounds(pts).pad(.3),{duration:.6});
}
function stopDraw(){
  drawing=false; document.body.classList.remove('drawing'); map.doubleClickZoom.enable();
  dLayer.clearLayers(); map.removeLayer(hoverDot); $('drawPanel').style.display='none'; $('drawBtn').classList.remove('on');
  map.invalidateSize();
}
map.on('click',e=>{if(!drawing) return; push(); pts.push(snap(e.latlng)); redraw();});
map.on('popupopen',()=>{if(drawing) map.closePopup();});
function push(){hist.push(pts.map(p=>L.latLng(p.lat,p.lng))); if(hist.length>200) hist.shift();}
function undo(){if(hist.length){pts=hist.pop();redraw();}}
function clearRoute(){if(pts.length){push();pts=[];redraw();}}
function reverseRoute(){push();pts.reverse();redraw();}
addEventListener('keydown',e=>{if(drawing&&(e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'&&!/INPUT|TEXTAREA/.test(document.activeElement.tagName)){e.preventDefault();undo();}});
function snap(ll){
  if(!$('dSnap').checked) return ll;
  const at=map.latLngToContainerPoint(ll); let best=ll,bd=14;
  P.forEach(f=>{if(!f.properties.front) return; const c=f.geometry.coordinates,q=map.latLngToContainerPoint([c[1],c[0]]),d=q.distanceTo(at);
    if(d<bd){bd=d;best=L.latLng(c[1],c[0]);}});
  return best;
}
const icon=(cls,s)=>L.divIcon({className:'',html:`<div class="${cls}"></div>`,iconSize:[s,s],iconAnchor:[s/2,s/2]});
function redraw(){
  dLayer.clearLayers();
  dLine=L.polyline(pts,{color:css('--drawn'),weight:4,opacity:.95,interactive:false}).addTo(dLayer);
  pts.forEach((p,i)=>{
    const m=L.marker(p,{draggable:true,icon:icon('vtx'+(i===0||i===pts.length-1?' end':''),12)}).addTo(dLayer);
    m.on('dragstart',push); m.on('drag',e=>{pts[i]=e.target.getLatLng();dLine.setLatLngs(pts);});
    m.on('dragend',e=>{pts[i]=snap(e.target.getLatLng());redraw();});
    const del=e=>{L.DomEvent.stop(e);push();pts.splice(i,1);redraw();};
    m.on('dblclick',del); m.on('contextmenu',del);
  });
  for(let i=1;i<pts.length;i++){
    const a=pts[i-1],b=pts[i];
    const m=L.marker([(a.lat+b.lat)/2,(a.lng+b.lng)/2],{draggable:true,icon:icon('mid',10)}).addTo(dLayer);
    m.on('dragstart',()=>{push();pts.splice(i,0,m.getLatLng());});
    m.on('drag',e=>{pts[i]=e.target.getLatLng();dLine.setLatLngs(pts);});
    m.on('dragend',e=>{pts[i]=snap(e.target.getLatLng());redraw();});
  }
  clearTimeout(statTimer); statTimer=setTimeout(computeStats,150);
}
function densify(ll,step){
  const out=[];
  for(let i=0;i<ll.length;i++){
    if(i===0){out.push(ll[0]);continue;}
    const a=ll[i-1],b=ll[i],n=Math.max(1,Math.ceil(map.distance(a,b)/step));
    for(let k=1;k<=n;k++) out.push(L.latLng(a.lat+(b.lat-a.lat)*k/n,a.lng+(b.lng-a.lng)*k/n));
  }
  return out;
}
// elevation from AWS terrain tiles (terrarium PNG, z13 ~ 13 m at this latitude)
const DEMZ=13,TILE=new Map();
function tileXY(lat,lng){const n=2**DEMZ,r=lat*Math.PI/180;
  return [(lng+180)/360*n,(1-Math.log(Math.tan(r)+1/Math.cos(r))/Math.PI)/2*n];}
function loadTile(tx,ty){
  const k=tx+'/'+ty;
  if(!TILE.has(k)) TILE.set(k,new Promise(res=>{const img=new Image();img.crossOrigin='anonymous';
    img.onload=()=>{const c=document.createElement('canvas');c.width=c.height=256;const g=c.getContext('2d',{willReadFrequently:true});
      g.drawImage(img,0,0);res(g.getImageData(0,0,256,256).data);};
    img.onerror=()=>res(null);
    img.src=`https://s3.amazonaws.com/elevation-tiles-prod/terrarium/${DEMZ}/${tx}/${ty}.png`;}));
  return TILE.get(k);
}
async function elevAt(lat,lng){
  const [x,y]=tileXY(lat,lng),tx=Math.floor(x),ty=Math.floor(y),d=await loadTile(tx,ty);
  if(!d) return null;
  const i=(Math.min(255,Math.floor((y-ty)*256))*256+Math.min(255,Math.floor((x-tx)*256)))*4;
  return d[i]*256+d[i+1]+d[i+2]/256-32768;
}
function climb(z){   // [gain_m, loss_m] after a 3-point smooth
  const v=z.map((_,i)=>{const w=z.slice(Math.max(0,i-1),i+2).filter(x=>x!=null);return w.length?w.reduce((a,b)=>a+b)/w.length:null;});
  let g=0,l=0; for(let i=1;i<v.length;i++) if(v[i]!=null&&v[i-1]!=null){const d=v[i]-v[i-1]; if(d>0) g+=d; else l-=d;}
  return [g,l];
}
function paceAt(grade){   // seconds per metre on trail, from the athlete's own runs
  const c=D.pace.centers,b=D.pace.base;
  if(grade<=c[0]) return b[0]; if(grade>=c[c.length-1]) return b[b.length-1];
  let k=1; while(c[k]<grade) k++;
  return b[k-1]+(b[k]-b[k-1])*(grade-c[k-1])/(c[k]-c[k-1]);
}
async function computeStats(){
  const seq=++statSeq;
  if(pts.length<2){lastStats=null;['dDist','dGain','dLoss'].forEach(k=>$(k).textContent='0');$('dTime').textContent='–';
    $('dProfile').innerHTML='';$('dPeaks').innerHTML='';return;}
  const dense=densify(pts,30), z=await Promise.all(dense.map(p=>elevAt(p.lat,p.lng)));
  if(seq!==statSeq) return;
  const cum=[0]; for(let i=1;i<dense.length;i++) cum.push(cum[i-1]+map.distance(dense[i-1],dense[i]));
  const [gain,loss]=climb(z), dist=cum[cum.length-1];
  let secs=null;
  if(D.pace){secs=0;for(let i=1;i<dense.length;i++){const h=cum[i]-cum[i-1];
    secs+=h*paceAt(z[i]!=null&&z[i-1]!=null&&h>0?(z[i]-z[i-1])/h:0);}
    if($('dOff').checked) secs*=D.pace.off;}
  const near=P.filter(f=>f.properties.front&&dense.some(p=>map.distance(p,[f.geometry.coordinates[1],f.geometry.coordinates[0]])<60));
  lastStats={dense,z,cum,dist,gain,loss,secs,peaks:near.map(f=>f.properties.id)};
  $('dDist').textContent=(dist/1609.344).toFixed(1);
  $('dGain').textContent=fmt(Math.round(gain/0.3048)); $('dLoss').textContent=fmt(Math.round(loss/0.3048));
  $('dTime').textContent=secs==null?'–':(secs/3600).toFixed(1);
  $('dPeaks').innerHTML=near.map(f=>`<span class="chip${f.properties.done?' done':''}">▲ ${esc(nameOf(f.properties))}</span>`).join('');
  drawProfile();
}
function drawProfile(){
  const s=lastStats,W=340,H=110,px=4,py=12;
  const vals=s.z.filter(v=>v!=null); if(vals.length<2){$('dProfile').innerHTML='';return;}
  const mn=Math.min(...vals),mx=Math.max(...vals),span=Math.max(1,mx-mn);
  const X=d=>px+(W-2*px)*d/Math.max(1,s.dist), Y=v=>H-py-(H-2*py)*(v-mn)/span;
  const line=s.z.map((v,i)=>v==null?null:X(s.cum[i]).toFixed(1)+','+Y(v).toFixed(1)).filter(Boolean);
  const col=css('--drawn');
  $('dProfile').innerHTML=`<svg id="dSvg" viewBox="0 0 ${W} ${H}" width="100%" style="display:block;margin-top:8px;touch-action:none">
    <path d="M${X(0)},${H} L${line.join(' L')} L${X(s.dist)},${H} Z" fill="${col}" opacity=".14"/>
    <polyline points="${line.join(' ')}" fill="none" stroke="${col}" stroke-width="2"/>
    <text x="${W-px}" y="10" text-anchor="end" font-size="10" fill="${css('--muted')}">${fmt(Math.round(mx/0.3048))} ft</text>
    <text x="${W-px}" y="${H-2}" text-anchor="end" font-size="10" fill="${css('--muted')}">${fmt(Math.round(mn/0.3048))} ft</text>
    <line id="dCross" y1="0" y2="${H}" stroke="${css('--muted')}" stroke-dasharray="2 3" visibility="hidden"/>
    <text id="dTip" y="10" font-size="10.5" font-weight="600" fill="${css('--ink')}"></text></svg>`;
  const svg=$('dSvg');
  const move=e=>{const r=svg.getBoundingClientRect(),d=Math.max(0,Math.min(1,((e.clientX-r.left)/r.width*W-px)/(W-2*px)))*s.dist;
    let i=0; while(i<s.cum.length-1&&s.cum[i]<d) i++;
    const x=X(s.cum[i]); $('dCross').setAttribute('x1',x); $('dCross').setAttribute('x2',x); $('dCross').setAttribute('visibility','visible');
    const t=$('dTip'); t.textContent=`${(s.cum[i]/1609.344).toFixed(2)} mi · ${s.z[i]==null?'–':fmt(Math.round(s.z[i]/0.3048))} ft`;
    t.setAttribute('x',x>W/2?x-6:x+6); t.setAttribute('text-anchor',x>W/2?'end':'start');
    hoverDot.setLatLng(s.dense[i]).setStyle({fillColor:col}).addTo(map);};
  svg.onpointermove=move; svg.onpointerdown=move;
  svg.onpointerleave=()=>{$('dCross').setAttribute('visibility','hidden');$('dTip').textContent='';map.removeLayer(hoverDot);};
}
const autoName=()=>lastStats?.peaks.length?lastStats.peaks.map(i=>nameOf(P[i].properties)).join(' → '):'Drawn route';
async function saveDrawn(){
  if(pts.length<2){note('Draw at least two points.',true,'dMsg');return;}
  if(!STATE){note('Saving works on theblacks.ai/i90peaks. Use GPX to keep it.',true,'dMsg');return;}
  if(!STATE.owner){$('dMsg').innerHTML=pwBox('saveDrawn')+'<div class="msg" id="dErr"></div>';return;}
  if(statTimer){clearTimeout(statTimer);await computeStats();}
  const s=lastStats;
  try{const j=await api('/drawn',{method:'POST',body:{id:editId,name:$('dName').value.trim()||autoName(),
      peaks:s?.peaks||[],coordinates:pts.map(p=>[p.lng,p.lat]),notes:$('dNotes').value.trim(),
      dist_mi:s&&+(s.dist/1609.344).toFixed(2),gain_ft:s&&Math.round(s.gain/0.3048),est_hours:s?.secs!=null?+(s.secs/3600).toFixed(1):null}});
    editId=j.id; if(!$('dName').value.trim()) $('dName').value=autoName();
    note('Saved ✓',false,'dMsg'); loadState();}
  catch(e){note(e.message,true,'dMsg');}
}
function gpx(name,ll,z){
  const e=s=>s.replace(/&/g,'&amp;').replace(/</g,'&lt;');
  return `<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="i90peaks" xmlns="http://www.topografix.com/GPX/1/1">\n<trk><name>${e(name)}</name><trkseg>`+
    ll.map((p,i)=>`<trkpt lat="${p.lat.toFixed(6)}" lon="${p.lng.toFixed(6)}">${z&&z[i]!=null?`<ele>${z[i].toFixed(1)}</ele>`:''}</trkpt>`).join('')+'</trkseg></trk>\n</gpx>\n';
}
const slug=s=>s.replace(/[^\w]+/g,'_').replace(/^_|_$/g,'').slice(0,60)||'route';
function exportDrawn(){
  if(pts.length<2) return;
  const name=$('dName').value.trim()||autoName();
  download(slug(name)+'.gpx',gpx(name,lastStats?lastStats.dense:pts,lastStats?.z),'application/gpx+xml');
}
function gpxOfDrawn(id){const d=STATE.drawn.find(x=>x.id===id); if(!d) return;
  download(slug(d.name)+'.gpx',gpx(d.name,d.geometry.coordinates.map(c=>L.latLng(c[1],c[0]))),'application/gpx+xml');}
async function deleteDrawn(id){
  if(!confirm('Delete this drawn route?')) return;
  try{await api('/drawn?id='+id,{method:'DELETE'});}catch(e){alert(e.message);return;}
  map.closePopup(); loadState();
}
function editDrawn(id){const d=STATE.drawn.find(x=>x.id===id); if(!d) return; map.closePopup();
  startDraw({id:STATE.owner?d.id:null,name:d.name,notes:d.notes,pts:d.geometry.coordinates.map(c=>L.latLng(c[1],c[0]))});}
function simplify(ll,tol){   // Douglas-Peucker in metres, so a dense route stays editable
  if(ll.length<3) return ll;
  const xy=ll.map(p=>map.options.crs.project(p)), keep=new Array(ll.length).fill(false); keep[0]=keep[ll.length-1]=true;
  const k=1/Math.cos(ll[0].lat*Math.PI/180), st=[[0,ll.length-1]];
  while(st.length){const [a,b]=st.pop(); let md=0,mi=-1;
    for(let i=a+1;i<b;i++){const d=L.LineUtil.pointToSegmentDistance(xy[i],xy[a],xy[b])/k; if(d>md){md=d;mi=i;}}
    if(md>tol){keep[mi]=true;st.push([a,mi],[mi,b]);}}
  return ll.filter((_,i)=>keep[i]);
}
function editPlanned(rid){const f=D.routes.features.find(x=>x.properties.route_id===rid); if(!f) return; map.closePopup();
  startDraw({name:f.properties.name,notes:f.properties.desc,off:f.properties.off_trail_pct>50,
    pts:simplify(f.geometry.coordinates.map(c=>L.latLng(c[1],c[0])),12)});}
function drawTo(id){const c=P[id].geometry.coordinates; startDraw({name:nameOf(P[id].properties)}); map.flyTo([c[1],c[0]],14,{duration:.6});}

loadState();
"""
