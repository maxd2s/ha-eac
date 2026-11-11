/* No libraries, credentials or DSO calls: read permission-scoped HA cache only. */
class EacInsightsCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});this._meters=[];this._day='';}
  setConfig(c){this._config=c;this._entity=c.entity||'';}
  getCardSize(){return 12;}
  set hass(h){this._hass=h;if(!this._config)return;
    const stamp=h.states[this._entity]?.last_updated;
    if(!this._busy && Date.now()-(this._attemptAt||0)>30000 && (!this._data||stamp!==this._stamp||Date.now()-(this._loaded||0)>60000))this._load();
  }
  async _load(){
    if(this._busy){this._reload=true;return;}this._busy=true;this._attemptAt=Date.now();
    try{
      this._meters=await this._hass.callWS({type:'eac_cyprus/profile_meters'});
      if(!this._entity)this._entity=this._meters[0]?.entity_id||'';
      if(!this._entity){this._error='No readable EAC meters found.';return;}
      const entity=this._entity;
      const data=await this._hass.callWS({type:'eac_cyprus/profile',entity_id:entity});
      if(entity!==this._entity)return;
      this._data=data;this._stamp=this._hass.states[entity]?.last_updated;this._loaded=Date.now();this._error='';
    }catch{this._error='Unable to load this meter. Check the integration and your access permissions.';this._data=null;}
    finally{this._busy=false;this._render();if(this._reload){this._reload=false;this._load();}}
  }
  _render(){
    const d=this._data;
    const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const fmt=(n,digits=2)=>Number.isFinite(n)?new Intl.NumberFormat(undefined,{maximumFractionDigits:digits}).format(n):'—';
    const zone=d?.time_zone||'Asia/Nicosia';
    const dateKey=t=>{const p=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(t)).map(p=>[p.type,p.value]));return `${p.year}-${p.month}-${p.day}`;};
    const when=t=>t?new Date(t).toLocaleString(undefined,{timeZone:zone,month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}):'No readings';
    const hour=n=>`${String(n).padStart(2,'0')}:00`;
    const choices=this._meters.map(m=>`<option value="${esc(m.entity_id)}" ${m.entity_id===this._entity?'selected':''}>${esc(m.name)}</option>`).join('');
    const css=`:host{display:block}ha-card{display:block;padding:20px;border-radius:18px;color:var(--primary-text-color);font-family:inherit}h2{font-size:21px;margin:0 0 8px}h3{font-size:16px;margin:22px 0 7px}p,.muted{font-size:12px;line-height:1.6;color:var(--secondary-text-color)}.controls{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}select,input,button{font:inherit;padding:8px;border-radius:8px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color);max-width:100%}.kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.kpi{background:var(--secondary-background-color);padding:12px;border-radius:12px}.kpi strong{font-size:24px;display:block;margin:7px 0}.kpi small{font-size:11px;color:var(--secondary-text-color)}.label{font-size:12px}.legend{font-size:12px;display:flex;gap:18px;margin:8px 0}.blue{color:#42a5f5}.gold{color:#f9b938}svg{width:100%;overflow:visible}svg text{font:11px sans-serif;fill:var(--secondary-text-color)}svg path{fill:none;stroke-width:1.8;stroke-linejoin:round}svg .grid{stroke:var(--divider-color);stroke-dasharray:3 4}.empty{padding:25px;color:var(--secondary-text-color)}.details{margin-top:18px;padding-top:12px;border-top:1px solid var(--divider-color);font-size:12px;line-height:1.7}.warn{color:var(--warning-color,#f9b938)}@media(max-width:420px){ha-card{padding:12px}.kpis{gap:5px}.kpi{padding:8px}.kpi strong{font-size:20px}}`;
    if(!d){this.shadowRoot.innerHTML=`<style>${css}</style><ha-card><h2>Grid energy insights</h2><select aria-label="Meter">${choices}</select><p>${esc(this._error||'Loading meter history…')}</p></ha-card>`;this._events();return;}
    const all=(d.points||[]).filter(p=>Array.isArray(p)&&Number.isFinite(p[0]));
    const points=all.filter(p=>!this._day||dateKey(p[0]-1)===this._day);
    const observedDays=new Set(all.map(p=>dateKey(p[0]-1)));
    const calendarStart=Date.parse(dateKey(Date.parse(d.window_start))+'T12:00:00Z');
    const days=Array.from({length:Math.min(90,Math.max(0,d.window_days))},(_,i)=>new Date(calendarStart+i*86400000).toISOString().slice(0,10));
    const dates=days.map(day=>`<option value="${day}" ${this._day===day?'selected':''}>${day}${observedDays.has(day)?'':' — no readings'}</option>`).join('');
    let history='<div class="empty">No half-hour readings for this selection.</div>';
    if(points.length){
      const from=this._day?points[0][0]-1800000:Date.parse(d.window_start);
      const to=this._day?Math.max(from+1800000,points.at(-1)[0]):Math.max(from+1800000,Date.parse(d.fetched_at));
      const max=Math.max(1,...points.flatMap(p=>p.slice(1).filter(Number.isFinite).map(v=>v*2)));
      const top=Math.ceil(max);const x=t=>44+(t-from)/(to-from)*500;const y=v=>186-v/top*156;
      const path=index=>{let previous=null;return points.map(p=>{if(!Number.isFinite(p[index])){previous=null;return '';}const move=previous===null||p[0]-previous>1800000;previous=p[0];return `${move?'M':'L'}${x(p[0]).toFixed(2)},${y(p[index]*2).toFixed(2)}`;}).join(' ');};
      const ticks=[0,1,2,3,4].map(i=>`<line class="grid" x1="44" x2="544" y1="${y(top*i/4)}" y2="${y(top*i/4)}"/><text x="36" y="${y(top*i/4)+4}" text-anchor="end">${fmt(top*i/4,1)}</text>`).join('');
      const labels=[0,1,2,3,4].map(i=>{const t=from+(to-from)*i/4;const label=new Date(t).toLocaleString(undefined,{timeZone:zone,...(this._day?{hour:'2-digit',minute:'2-digit',hour12:false}:{month:'short',day:'numeric'})});return `<text x="${x(t)}" y="211" text-anchor="middle">${esc(label)}</text>`;}).join('');
      const isolated=[1,2].map(index=>points.map((p,i)=>{
        if(!Number.isFinite(p[index]))return '';
        const before=points[i-1],after=points[i+1];
        const adjacent=q=>q&&Number.isFinite(q[index])&&Math.abs(q[0]-p[0])===1800000;
        return !adjacent(before)&&!adjacent(after)?`<circle cx="${x(p[0])}" cy="${y(p[index]*2)}" r="2.5" fill="${index===1?'#42a5f5':'#f9b938'}"/>`:'';
      }).join('')).join('');
      history=`<svg viewBox="0 0 580 230" role="img" aria-label="Half-hour grid import and export in average kilowatts"><text x="44" y="16">Average kW per half-hour</text>${ticks}${labels}<path d="${path(1)}" stroke="#42a5f5"/><path d="${path(2)}" stroke="#f9b938"/>${isolated}</svg>`;
    }
    const slots=d.surplus_by_half_hour||[];const top=Math.max(1,...slots.map(p=>Number.isFinite(p[1])?p[1]:0));
    const bars=slots.map(p=>{if(!Number.isFinite(p[1]))return '';const h=p[1]/top*105;const label=`${String(Math.floor(p[0]/2)).padStart(2,'0')}:${p[0]%2?'30':'00'}`;return `<rect x="${44+p[0]*10.4}" y="${135-h}" width="8" height="${h}" rx="1" fill="#f9b938"><title>${label} · ${fmt(p[1])} kW · ${p[2]} observations</title></rect>`;}).join('');
    const surplus=slots.some(p=>Number.isFinite(p[1]))?`<svg viewBox="0 0 580 165" role="img" aria-label="Average exported power by local half-hour of day"><text x="44" y="16">Average export kW · scale 0–${fmt(top,1)}</text>${bars}${[0,6,12,18,24].map(h=>`<text x="${44+h/24*499.2}" y="156" text-anchor="middle">${hour(h)}</text>`).join('')}</svg>`:'<div class="empty">No export profile available for this meter.</div>';
    const tariff=d.tariff?.code||'Unknown';
    this.shadowRoot.innerHTML=`<style>${css}</style><ha-card><h2>Grid energy insights</h2><p>${d.window_days} calendar days · Cyprus time · through ${esc(when(d.data_through))}${d.available?'':'<br><span class="warn">Last portal refresh failed; showing cached readings.</span>'}</p>
    <div class="controls"><select aria-label="Meter">${choices}</select><button id="refresh" aria-label="Refresh cached data">Refresh</button></div>
    <div class="kpis"><div class="kpi"><div class="label">Overnight baseline</div><strong>${fmt(d.overnight_baseline_kw)}</strong><small>kW · ${d.complete_nights} complete nights<br>${hour(d.night_start_hour)}–${hour(d.night_end_hour)}</small></div><div class="kpi"><div class="label">Highest demand</div><strong>${fmt(d.peak_import_kw)}</strong><small>kW · 30-min average<br>${esc(when(d.peak_import_at))}</small></div><div class="kpi"><div class="label">Tariff code</div><strong>${esc(tariff)}</strong><small>Reported by DSO<br>Prices not inferred</small></div></div>
    <h3>Import vs export</h3><div class="controls"><select id="day" aria-label="History date"><option value="">Full ${d.window_days}-day window</option>${dates}</select></div>${history}<div class="legend"><span class="blue">● Grid import</span><span class="gold">● Grid export</span></div>
    <p>Full ${d.window_days}-day coverage: import ${fmt(d.import_coverage_percent,1)}% · export ${fmt(d.export_coverage_percent,1)}%. Missing intervals break the lines; they are not zero.</p>
    <h3>Usual surplus-solar hours</h3>${surplus}<p>Average grid export by half-hour of day across all ${d.window_days} retained calendar days. Received zeros are included; missing samples are excluded. This is historical surplus, not a forecast.</p>
    <div class="details">${esc(d.model||'Meter model unavailable')} · ${esc(d.phases||'—')} phases · entitlement ${esc(d.load_entitlement||'—')} ${esc(d.load_entitlement_unit||'')}<br>Tariff source: ${esc(d.tariff?.source||'Not available')} · checked ${esc(when(d.tariff?.retrieved_at))}<br>Baseline = median of complete nights’ average grid demand. It includes any overnight charging or heating. Neither chart measures total solar generation or whole-house consumption.<br>History length and overnight hours are configurable in the integration options. Reports refresh daily; readings follow your configured polling schedule.</div></ha-card>`;
    this._events();
  }
  _events(){
    const meter=this.shadowRoot.querySelector('select[aria-label="Meter"]');
    if(meter)meter.onchange=e=>{this._entity=e.target.value;this._data=null;this._day='';this._load();};
    const day=this.shadowRoot.querySelector('#day');if(day)day.onchange=e=>{this._day=e.target.value;this._render();};
    const refresh=this.shadowRoot.querySelector('#refresh');if(refresh)refresh.onclick=()=>this._load();
  }
}
if(!customElements.get('eac-insights-card'))customElements.define('eac-insights-card',EacInsightsCard);
window.customCards=window.customCards||[];window.customCards.push({type:'eac-insights-card',name:'EAC grid energy insights',description:'Discover readable meters, profile history, demand and DSO tariff codes'});
