"""The AlphaEarth route-similarity analysis + predicted-route plan (one HTML file)."""
from __future__ import annotations

import json

from . import config


def build(data: dict, out_path=None) -> str:
    out_path = out_path or (config.PROCESSED / "similarity.html")
    html = _TEMPLATE.replace("__DATA__", json.dumps(data, separators=(",", ":"), default=str))
    out_path.write_text(html)
    print(f"[analysis] wrote {out_path} ({len(html) / 1e3:.0f} kB)")
    return str(out_path)


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>I-90 Route Similarity</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Comparing completed I-90 peak runs with AlphaEarth satellite embeddings, and predicting routes for the peaks still to go.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#f4f1ea; --panel:#fbfaf6; --ink:#1c2422; --ink2:#4b5350; --muted:#6b736f; --line:#e2ddd2; --chip:#ece7dc;
  --accent:#d4572a; --pos:#2a78d6; --neg:#eb6834; --mid:#e9e6df; --mark:#2f5d8a;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#121615; --panel:#1a201e; --ink:#e9ece8; --ink2:#c3c8c4; --muted:#9aa49f; --line:#2b3330; --chip:#242c29;
  --accent:#ff7a45; --pos:#3987e5; --neg:#d95926; --mid:#2c3431; --mark:#78a9d8;}}
:root[data-theme="dark"]{
  --bg:#121615; --panel:#1a201e; --ink:#e9ece8; --ink2:#c3c8c4; --muted:#9aa49f; --line:#2b3330; --chip:#242c29;
  --accent:#ff7a45; --pos:#3987e5; --neg:#d95926; --mid:#2c3431; --mark:#78a9d8;}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 Inter,system-ui,sans-serif;-webkit-font-smoothing:antialiased}
a{color:var(--accent)}
.wrap{max-width:1180px;margin:0 auto;padding:0 20px}
nav.top{position:sticky;top:0;z-index:10;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
nav.top .wrap{display:flex;gap:18px;align-items:center;height:54px;overflow-x:auto;white-space:nowrap}
nav.top b{font-family:Fraunces,serif;font-size:17px;margin-right:auto}
nav.top a{color:var(--ink2);text-decoration:none;font-size:13px;font-weight:600}
nav.top a:hover{color:var(--accent)}
.btn{display:inline-block;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:999px;padding:7px 14px;font:600 13px Inter,sans-serif;text-decoration:none;cursor:pointer}
.btn:hover{border-color:var(--accent);color:var(--ink)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
header.hero{padding:56px 0 28px}
.eyebrow{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-weight:600}
h1{font-family:Fraunces,Georgia,serif;font-size:clamp(34px,5vw,54px);line-height:1.05;margin:8px 0 14px;font-weight:700}
h2{font-family:Fraunces,Georgia,serif;font-size:30px;margin:0 0 6px;line-height:1.15}
h3{font-size:15px;margin:0 0 4px}
.lede{font-size:17px;color:var(--ink2);max-width:760px}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:28px 0 8px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.tile b{display:block;font-family:Fraunces,serif;font-size:32px;line-height:1.1}
.tile span{font-size:12px;color:var(--muted)}
section{padding:44px 0;border-top:1px solid var(--line)}
.sub{color:var(--muted);font-size:14px;max-width:780px;margin:0 0 20px}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12px;color:var(--ink2);margin:10px 0 16px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px;cursor:pointer;transition:border-color .15s}
.card:hover,.card.sel{border-color:var(--accent)}
.card .meta{font-size:12px;color:var(--muted)}
.card .stats{display:flex;gap:14px;font-size:12px;color:var(--ink2);margin:8px 0;font-variant-numeric:tabular-nums}
.barcode{display:flex;height:22px;border-radius:6px;overflow:hidden;margin:10px 0 6px}
.barcode i{flex:1}
.stack{display:flex;height:10px;border-radius:5px;overflow:hidden;gap:2px;background:var(--panel)}
.stack i{display:block;height:100%}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.chip{font-size:11.5px;background:var(--chip);border-radius:999px;padding:3px 9px;color:var(--ink2)}
.grid2{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:22px;align-items:start}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px}
#heat svg text,#scatter svg text,#pace svg text,#offm svg text{font:11px Inter,sans-serif;fill:var(--ink2)}
.tip{position:fixed;pointer-events:none;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:10px;padding:8px 10px;font-size:12.5px;box-shadow:0 8px 24px rgba(0,0,0,.18);z-index:50;display:none;max-width:280px}
.rank{list-style:none;padding:0;margin:0}
.rank li{display:grid;grid-template-columns:1fr 120px 44px;gap:10px;align-items:center;padding:7px 0;border-bottom:1px solid var(--line);font-size:13px}
.rank .bar{height:8px;border-radius:4px;background:var(--chip);overflow:hidden}
.rank .bar i{display:block;height:100%;background:var(--pos);border-radius:0 4px 4px 0}
.rank .v{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink2)}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:600;padding:8px 8px;border-bottom:1px solid var(--line)}
td{padding:10px 8px;border-bottom:1px solid var(--line);vertical-align:top}
td.n{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
th.n{text-align:right}
tr.region td{background:var(--chip);font-weight:600;font-size:12px;letter-spacing:.04em;padding:7px 8px}
.flag{font-size:11px;color:var(--accent);font-weight:600}
.tablewrap{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:16px}
.note{font-size:13px;color:var(--ink2);background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
details summary{cursor:pointer;font-weight:600;font-size:14px}
footer{padding:36px 0 60px;color:var(--muted);font-size:12.5px;border-top:1px solid var(--line)}
@media (max-width:860px){.tiles{grid-template-columns:repeat(2,1fr)}.grid2{grid-template-columns:1fr}
  .cards{grid-template-columns:1fr} .hide-sm{display:none}}
</style></head><body>
<nav class="top"><div class="wrap"><b>I-90 Peaks</b>
  <a href="#routes">My routes</a><a href="#similarity">Similarity</a><a href="#plan">Planned routes</a><a href="#pace">Pace model</a><a href="#method">Method</a>
  <a class="btn primary" id="mapLink" href="#">Open the map ↗</a>
  <button class="btn" id="themeBtn" title="Toggle theme">◐</button></div></nav>

<div class="wrap">
<header class="hero">
  <div class="eyebrow">Running challenge · route analysis</div>
  <h1>How alike are my I-90 peak runs?</h1>
  <p class="lede">Every 10&nbsp;m of Earth has a 64-number fingerprint from Google DeepMind's
  <b>AlphaEarth</b> model, learned from a year of satellite, radar and terrain data. Averaging those
  fingerprints along each run gives a route a fingerprint of its own, and two routes are alike when
  their fingerprints point the same way. The same fingerprints, plus my pace on and off trail,
  predict routes for the first-row peaks still to go.</p>
  <div class="tiles" id="tiles"></div>
</header>

<section id="routes">
  <h2>My completed peak routes</h2>
  <p class="sub">Each run that topped out on a first-row peak. The colour strip is the route
    "painted in the AI's own colours": its top three embedding directions shown as red, green and
    blue, start to finish. The bar under it is the route's terrain mix (unsupervised classes from the
    embeddings). Click a card to rank every other run against it.</p>
  <div class="legend" id="legend"></div>
  <div class="cards" id="cards"></div>
</section>

<section id="similarity">
  <h2>Similarity between routes</h2>
  <p class="sub">Cosine similarity of the route fingerprints (centred on the corridor average, so
  the score reflects what makes a route distinctive, not the fact that it's all in the Cascades). Blue = alike,
  orange = opposite terrain, grey = unrelated. Rows are ordered by hierarchical clustering, so
  look-alike routes sit in blocks. Hover a cell for the value, or click to select a row.</p>
  <div class="grid2">
    <div class="panel" id="heat"></div>
    <div>
      <div class="panel" style="margin-bottom:16px">
        <h3 id="rankTitle">Most similar routes</h3>
        <p class="sub" style="margin:0 0 8px;font-size:12.5px" id="rankSub">Pick a route from a card or the matrix.</p>
        <ul class="rank" id="rank"></ul>
      </div>
      <div class="panel"><h3>Route space</h3>
        <p class="sub" style="margin:0 0 6px;font-size:12.5px">The fingerprints projected onto their two main directions of variation. Nearby dots are similar routes.</p>
        <div id="scatter"></div></div>
    </div>
  </div>
</section>

<section id="plan">
  <h2>Predicted routes for the peaks still to go</h2>
  <p class="sub" id="planSub"></p>
  <div class="tablewrap"><table id="planTable"></table></div>
  <p class="sub" style="margin-top:12px" id="unrouted"></p>
  <p><a class="btn" href="planned_routes.gpx" id="gpxLink" download>Download all planned routes (GPX for CalTopo)</a></p>
</section>

<section id="pace">
  <h2>The pace model behind the predictions</h2>
  <p class="sub" id="paceSub"></p>
  <div class="grid2">
    <div class="panel"><h3>On-trail pace by grade</h3><div id="paceChart"></div></div>
    <div class="panel"><h3>Off-trail slowdown by terrain type</h3>
      <p class="sub" style="margin:0 0 6px;font-size:12.5px">Multiplier on the on-trail pace at the same grade. Hollow bars have fewer than 20 off-trail samples and lean on the overall average.</p>
      <div id="offm"></div></div>
  </div>
</section>

<section id="method">
  <h2>Method</h2>
  <div class="note">
  <details open><summary>Peaks: what counts as "first row"</summary>
  <p>Every summit with ≥250 ft of prominence (computed on a 26 m DEM and cross-checked against the
  Kirmse/de Ferranti global list) between Seattle and the Columbia. A peak's <i>cap</i> is the part of
  its massif within 250 ft of the summit: the peak plus connected ridges that don't descend more than 250 ft.
  A peak is first row if a straight line from I-90 reaches its cap without crossing another peak's
  cap, an intervening ridge (rises ≥250 ft then drops ≥250 ft), or ground higher than the summit.</p></details>
  <details><summary>Similarity: AlphaEarth fingerprints</summary>
  <p>Embeddings are the 2025 annual AlphaEarth Foundations Satellite Embedding layer (the same
  data as Earth Engine's <code>GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL</code>), read from the public
  Source Cooperative COG mirror at 40 m and de-quantised with <code>(q/127.5)²·sign(q)</code>.
  Each route is sampled every 40 m; its fingerprint is the mean vector minus the corridor mean,
  normalised, and similarity is the cosine between fingerprints. Terrain types come from k-means
  (k = 10) on 400k corridor pixels, named after the fact from each cluster's elevation, slope and
  location, so treat the names as interpretations rather than ground truth.</p>
  <p>Adapted from the <a href="https://github.com/webpug/geospatial/blob/main/alpha_earth_embeddings_demo.ipynb">AlphaEarth
  embeddings demo notebook</a>, itself adapted from work by Teodora Szasz, PhD (Standout Systems).</p></details>
  <details><summary>Predicted routes</summary>
  <p>Routes are least-time paths on a 40 m grid. Travel time = horizontal distance × my on-trail pace
  at that grade × the off-trail multiplier for that cell's terrain type (1 on any OSM trail or road).
  Ground steeper than 45° on the DEM is excluded, and so is water. Each outing starts on a public road at
  least 250 ft below its lowest summit (driving to the top doesn't count) and descends to the
  quickest road. Nearby peaks are chained when linking them beats separate trips and the day
  stays under the cap. These are planning sketches: check land access, seasonal closures and
  scrambling difficulty in CalTopo before going.</p></details>
  </div>
</section>

<footer><div class="wrap" style="padding:0">The AlphaEarth Foundations Satellite Embedding dataset is produced by Google and Google DeepMind (CC-BY 4.0).
Terrain: AWS Terrain Tiles. Trails, roads and names: © OpenStreetMap contributors. Published tracks skip my Strava privacy zones and the first and last 300 m of each run.</div></footer>
</div>
<div class="tip" id="tip"></div>
<script>
const D=__DATA__;
const $=s=>document.querySelector(s);
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const isDark=()=>{const t=document.documentElement.dataset.theme;return t?t==='dark':matchMedia('(prefers-color-scheme: dark)').matches;};
const gcol=g=>isDark()?g.dark:g.light;
const fmt=n=>n==null?'–':Number(n).toLocaleString();
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const R=D.routes, N=R.length;
$('#mapLink').href=D.map_url;
const tip=$('#tip');
function showTip(e,html){tip.innerHTML=html;tip.style.display='block';
  const x=Math.min(e.clientX+14,innerWidth-tip.offsetWidth-8),y=Math.min(e.clientY+14,innerHeight-tip.offsetHeight-8);
  tip.style.left=x+'px';tip.style.top=y+'px';}
function hideTip(){tip.style.display='none';}

function render(){
// ---- tiles
const s=D.stats;
$('#tiles').innerHTML=[[s.front,'first-row peaks'],[s.done,'summited'],[N,'routes compared'],[s.n_planned,'planned outings']]
  .map(([v,l])=>`<div class="tile"><b>${v}</b><span>${l}</span></div>`).join('');
// ---- legend + cards
$('#legend').innerHTML=D.groups.map(g=>`<span><i style="background:${gcol(g)}"></i>${g.label}</span>`).join('');
const stack=c=>`<div class="stack" role="img" aria-label="terrain mix">${c.map((v,k)=>v>0.004?`<i title="${D.groups[k].label}: ${Math.round(v*100)}%" style="width:${v*100}%;background:${gcol(D.groups[k])}"></i>`:'').join('')}</div>`;
$('#cards').innerHTML=R.map(r=>`<div class="card${sel===r.id?' sel':''}" data-id="${r.id}">
  <div class="meta">${esc(r.date)} · ${esc(r.type)}</div><h3>${esc(r.name)}</h3>
  <div class="barcode" title="route painted in AlphaEarth colours, start → finish">${r.barcode.map(c=>`<i style="background:${c}"></i>`).join('')}</div>
  ${stack(r.comp)}
  <div class="stats"><span>${r.dist_mi} mi</span><span>${fmt(r.gain_ft)} ft gain</span>${r.moving_h?`<span>${r.moving_h} h moving</span>`:''}<span>${r.off_trail_pct}% off-trail</span></div>
  <div class="chips">${r.peaks.map(p=>`<span class="chip">▲ ${esc(p)}</span>`).join('')}</div></div>`).join('');
document.querySelectorAll('.card').forEach(c=>c.onclick=()=>{select(+c.dataset.id);$('#similarity').scrollIntoView();});
heat();scatter();rank();plan();pace();
}

let sel=null;
function select(i){sel=i;render();}

// ---- diverging colour: orange (-1) -> neutral (0) -> blue (+1)
function mix(a,b,t){const p=h=>[1,3,5].map(i=>parseInt(h.slice(i,i+2),16));const A=p(a),B=p(b);
  return '#'+A.map((v,i)=>Math.round(v+(B[i]-v)*t).toString(16).padStart(2,'0')).join('');}
function divColor(v){const t=Math.max(-1,Math.min(1,v));return t>=0?mix(css('--mid'),css('--pos'),Math.pow(t,0.8)):mix(css('--mid'),css('--neg'),Math.pow(-t,0.8));}

function heat(){
  const O=D.order, cell=Math.max(14,Math.min(26,Math.floor(520/N))), lab=170, W=lab+cell*N+4, H=lab*0.0+cell*N+90;
  let s=`<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="route similarity matrix">`;
  O.forEach((i,row)=>{
    const y=row*cell; const bold=sel===i;
    s+=`<text x="${lab-6}" y="${y+cell/2+4}" text-anchor="end" style="${bold?'font-weight:700;fill:var(--ink)':''}">${esc(R[i].name.slice(0,24))}</text>`;
    O.forEach((j,col)=>{const v=D.sim[i][j];
      s+=`<rect x="${lab+col*cell}" y="${y}" width="${cell-2}" height="${cell-2}" rx="3" fill="${i===j?'var(--chip)':divColor(v)}" data-i="${i}" data-j="${j}" ${sel!==null&&sel!==i&&sel!==j?'opacity=".45"':''}/>`;});
  });
  // colour key
  const ky=cell*N+30, kw=Math.min(260,cell*N);
  for(let k=0;k<40;k++){const v=-1+2*k/39;s+=`<rect x="${lab+k*kw/40}" y="${ky}" width="${kw/40+0.5}" height="10" fill="${divColor(v)}"/>`;}
  s+=`<text x="${lab}" y="${ky+26}">−1 opposite</text><text x="${lab+kw/2}" y="${ky+26}" text-anchor="middle">0</text><text x="${lab+kw}" y="${ky+26}" text-anchor="end">+1 alike</text></svg>`;
  $('#heat').innerHTML=s;
  $('#heat').querySelectorAll('rect[data-i]').forEach(r=>{
    const i=+r.dataset.i,j=+r.dataset.j;
    r.onmousemove=e=>showTip(e,i===j?`<b>${esc(R[i].name)}</b>`:`<b>${esc(R[i].name)}</b><br>vs <b>${esc(R[j].name)}</b><br>similarity <b>${D.sim[i][j].toFixed(2)}</b>`);
    r.onmouseleave=hideTip; r.onclick=()=>select(i);});
}
function rank(){
  if(sel===null){$('#rank').innerHTML='';return;}
  const r=R[sel];
  $('#rankTitle').textContent='Most similar to '+r.name;
  $('#rankSub').textContent=r.date+' · '+r.peaks.join(', ');
  const list=R.filter(x=>x.id!==sel).map(x=>({x,v:D.sim[sel][x.id]})).sort((a,b)=>b.v-a.v);
  $('#rank').innerHTML=list.map(({x,v})=>`<li><span>${esc(x.name)} <span style="color:var(--muted);font-size:11.5px">${esc(x.date)}</span></span>
    <span class="bar"><i style="width:${Math.max(0,v)*100}%"></i></span><span class="v">${v.toFixed(2)}</span></li>`).join('');
}
function scatter(){
  const W=440,H=300,p=28, xs=R.map(r=>r.xy[0]), ys=R.map(r=>r.xy[1]);
  const x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys);
  const X=v=>p+(W-2*p)*(v-x0)/((x1-x0)||1), Y=v=>H-p-(H-2*p)*(v-y0)/((y1-y0)||1);
  let s=`<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="routes in fingerprint space">`;
  s+=`<line x1="${p}" x2="${W-p}" y1="${H-p}" y2="${H-p}" stroke="var(--line)"/><line x1="${p}" x2="${p}" y1="${p}" y2="${H-p}" stroke="var(--line)"/>`;
  s+=`<text x="${W-p}" y="${H-8}" text-anchor="end">direction 1 →</text><text x="${p}" y="${p-10}">↑ direction 2</text>`;
  // label only the selected route + its top 3 neighbours, everything else on hover
  let labelled=new Set();
  if(sel!==null){labelled.add(sel);R.filter(x=>x.id!==sel).sort((a,b)=>D.sim[sel][b.id]-D.sim[sel][a.id]).slice(0,3).forEach(x=>labelled.add(x.id));}
  R.forEach(r=>{const cx=X(r.xy[0]),cy=Y(r.xy[1]),on=sel===r.id;
    s+=`<circle cx="${cx}" cy="${cy}" r="${on?7:5.5}" fill="${on?css('--accent'):css('--mark')}" stroke="var(--panel)" stroke-width="2" data-id="${r.id}" style="cursor:pointer"/>`;
    if(labelled.has(r.id)) s+=`<text x="${cx+9}" y="${cy+4}" style="fill:var(--ink)">${esc(r.name.slice(0,22))}</text>`;});
  $('#scatter').innerHTML=s+'</svg>';
  $('#scatter').querySelectorAll('circle').forEach(c=>{const r=R[+c.dataset.id];
    c.onmousemove=e=>showTip(e,`<b>${esc(r.name)}</b><br>${esc(r.date)} · ${r.dist_mi} mi`);c.onmouseleave=hideTip;c.onclick=()=>select(r.id);});
}
function plan(){
  const P=D.planned,s=D.stats;
  $('#planSub').innerHTML=`${s.left} first-row peaks are left. The planner groups them into <b>${P.length} outings</b>, each capped at ${s.max_day_h} h of predicted moving time (about 1.25× my longest peak day so far). Times come from my own pace (next section). The "most like" column is the completed run with the closest AlphaEarth fingerprint: a hint of what the terrain will feel like.`;
  let h=`<thead><tr><th>Outing</th><th class="n">Miles</th><th class="n">Gain</th><th class="n">Est.</th><th class="n hide-sm">Off-trail</th><th class="hide-sm">Terrain</th><th class="hide-sm">Most like</th><th></th></tr></thead><tbody>`;
  let reg='';
  P.forEach(r=>{
    if(r.region!==reg){reg=r.region;const n=P.filter(x=>x.region===reg);h+=`<tr class="region"><td colspan="8">${esc(reg)} · ${n.length} outings · ${n.reduce((a,x)=>a+x.n_peaks,0)} peaks</td></tr>`;}
    h+=`<tr><td><b>${esc(r.name)}</b>${r.shuttle_mi>=1?`<br><span class="flag">ends ${r.shuttle_mi} mi from start</span>`:''}${r.new_terrain?`<br><span class="flag">new off-trail terrain for me</span>`:''}${r.fallback?`<br><span class="flag">hand-check: long approach or summit scramble</span>`:''}${r.restricted?`<br><span class="flag">⚠ ${esc(r.restricted)}</span>`:''}</td>
      <td class="n">${r.dist_mi}</td><td class="n">${fmt(r.gain_ft)}′</td><td class="n">${r.est_hours} h</td><td class="n hide-sm">${r.off_trail_pct}%</td>
      <td class="hide-sm" style="min-width:110px">${`<div class="stack">${r.comp8.map((v,k)=>v>0.004?`<i title="${D.groups[k].label}: ${Math.round(v*100)}%" style="width:${v*100}%;background:${gcol(D.groups[k])}"></i>`:'').join('')}</div>`}</td>
      <td class="hide-sm" style="font-size:12px;color:var(--ink2)">${r.like_run&&r.like_sim>=0.3?esc(r.like_run)+` <span style="color:var(--muted)">(${r.like_sim})</span>`:'<span style="color:var(--accent)">unlike anything I\'ve run yet</span>'}</td>
      <td><a class="btn" href="${D.map_url}#route=${r.route_id}">Map</a></td></tr>`;});
  $('#planTable').innerHTML=h+'</tbody>';
  $('#unrouted').textContent=s.unrouted.length?`Not routed automatically (too steep for the 45° rule, or at the edge of the data): ${s.unrouted.join(', ')}. Plan these by hand.`:'';
  $('#gpxLink').href=D.map_url+'/planned_routes.gpx';
}
function pace(){
  const P=D.pace;
  $('#paceSub').innerHTML=`Fit from ${fmt(P.n_chunks)} 100 m pieces of my timed runs in the corridor (${fmt(P.n_off)} of them off-trail). Grade comes from the terrain model, not the watch, and "off-trail" means more than 25 m from any mapped trail or road. On average I move <b>${P.overall_off}×</b> slower off-trail (mean, since time adds up); the planner never routes over ground steeper than <b>${P.max_slope}°</b>.`;
  // line chart
  const W=520,H=260,l=46,b=34,t=12,r=12;
  const xs=P.grade, ys=P.min_per_mi, x0=xs[0],x1=xs[xs.length-1], ymax=Math.ceil(Math.max(...ys)/10)*10;
  const X=v=>l+(W-l-r)*(v-x0)/(x1-x0), Y=v=>H-b-(H-b-t)*v/ymax;
  let s=`<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="pace by grade">`;
  for(let v=0;v<=ymax;v+=10) s+=`<line x1="${l}" x2="${W-r}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)"/><text x="${l-6}" y="${Y(v)+4}" text-anchor="end">${v}</text>`;
  [-0.5,-0.25,0,0.25,0.5].forEach(g=>s+=`<text x="${X(g)}" y="${H-b+18}" text-anchor="middle">${g>0?'+':''}${Math.round(g*100)}%</text>`);
  s+=`<text x="${l}" y="${t-1}" style="font-size:10.5px">min / mile</text><text x="${W-r}" y="${H-4}" text-anchor="end" style="font-size:10.5px">grade</text>`;
  s+=`<polyline fill="none" stroke="${css('--mark')}" stroke-width="2" points="${xs.map((g,i)=>X(g)+','+Y(ys[i])).join(' ')}"/>`;
  xs.forEach((g,i)=>s+=`<circle cx="${X(g)}" cy="${Y(ys[i])}" r="${P.n[i]>=20?4:3}" fill="${P.n[i]>=20?css('--mark'):'var(--panel)'}" stroke="${css('--mark')}" stroke-width="1.5"/>`);
  s+=`<line id="xh" x1="0" x2="0" y1="${t}" y2="${H-b}" stroke="var(--muted)" stroke-dasharray="3 3" style="display:none"/><rect x="${l}" y="${t}" width="${W-l-r}" height="${H-b-t}" fill="transparent" id="paceHit"/></svg>`;
  $('#paceChart').innerHTML=s+`<div class="legend"><span><i style="background:${css('--mark')};border-radius:50%"></i>≥20 samples</span><span><i style="border:1.5px solid ${css('--mark')};border-radius:50%"></i>sparse, blended with a Tobler hiking curve</span></div>`;
  const hit=$('#paceHit'), svg=hit.ownerSVGElement;
  hit.onmousemove=e=>{const pt=svg.createSVGPoint();pt.x=e.clientX;pt.y=e.clientY;const q=pt.matrixTransform(svg.getScreenCTM().inverse());
    let k=0,best=1e9;xs.forEach((g,i)=>{const d=Math.abs(X(g)-q.x);if(d<best){best=d;k=i;}});
    const xh=svg.querySelector('#xh');xh.style.display='';xh.setAttribute('x1',X(xs[k]));xh.setAttribute('x2',X(xs[k]));
    showTip(e,`grade <b>${xs[k]>0?'+':''}${Math.round(xs[k]*100)}%</b><br><b>${ys[k].toFixed(1)}</b> min/mi on trail<br><span style="color:var(--muted)">${P.n[k]} samples</span>`);};
  hit.onmouseleave=()=>{hideTip();svg.querySelector('#xh').style.display='none';};
  // off-trail multipliers
  const O=[...P.off].sort((a,b)=>b.mult-a.mult), bw=W, rowh=26, lw=170, mmax=Math.ceil(Math.max(...O.map(o=>o.mult))*2)/2;
  const BX=v=>lw+(bw-lw-50)*v/mmax;
  let o=`<svg viewBox="0 0 ${bw} ${O.length*rowh+30}" width="100%" role="img" aria-label="off-trail multipliers">`;
  o+=`<line x1="${BX(1)}" x2="${BX(1)}" y1="0" y2="${O.length*rowh}" stroke="var(--muted)" stroke-dasharray="3 3"/><text x="${BX(1)}" y="${O.length*rowh+18}" text-anchor="middle">1× = on-trail pace</text>`;
  O.forEach((d,i)=>{const y=i*rowh+4, solid=d.n>=20;
    o+=`<text x="${lw-8}" y="${y+13}" text-anchor="end">${esc(d.label)}</text>`;
    o+=`<rect x="${lw}" y="${y+2}" width="${Math.max(2,BX(d.mult)-lw)}" height="14" rx="4" fill="${solid?css('--mark'):'transparent'}" stroke="${css('--mark')}" stroke-width="${solid?0:1.5}"/>`;
    o+=`<text x="${BX(d.mult)+6}" y="${y+13}">${d.mult}× <tspan style="fill:var(--muted)">(${d.n})</tspan></text>`;});
  $('#offm').innerHTML=o+'</svg>';
}
$('#themeBtn').onclick=()=>{const r=document.documentElement;r.dataset.theme=isDark()?'light':'dark';render();};
// default selection: the most recent route
sel=N?N-1:null;
render();
</script></body></html>
"""
