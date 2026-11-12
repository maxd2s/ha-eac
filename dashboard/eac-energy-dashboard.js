/* EAC energy dashboard. No external libraries, credentials or DSO requests.
 * Profile access is permission-scoped; Recorder retains HA's own access policy.
 * Register changes and provisional intervals are never added together. */
const EAC_COLORS = ['#56b8ed', '#f3b953', '#b89ae8'];
const eacEscape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const eacNumber = (value, digits = 1) => Number.isFinite(value) ? new Intl.NumberFormat(undefined, {maximumFractionDigits:digits}).format(value) : '—';
function eacDay(value, zone = 'Asia/Nicosia') {
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(value)).map(p => [p.type,p.value]));
  return `${p.year}-${p.month}-${p.day}`;
}
function eacShift(day, count) { return new Date(Date.parse(day+'T12:00:00Z')+count*86400000).toISOString().slice(0,10); }
// Resolve calendar midnight in the meter timezone, including DST boundaries.
function eacMidnight(day, zone) {
  const target = Date.parse(day+'T00:00:00Z'); let time = target;
  for (let i=0;i<3;i++) {
    const p=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(new Date(time)).map(p=>[p.type,p.value]));
    time += target-Date.UTC(+p.year,+p.month-1,+p.day,+p.hour,+p.minute,+p.second);
  }
  return time;
}
function eacPeriod(mode, value, zone, now = Date.now()) {
  const today=eacDay(now,zone); let first, next, period='day';
  if(mode==='today'){first=today;next=eacShift(first,1);}
  else if(mode==='yesterday'){first=eacShift(today,-1);next=today;}
  else if(mode==='day'){first=value;next=eacShift(first,1);}
  else if(mode==='week'){first=eacShift(today,-7);next=today;}
  else if(mode==='year'){first=value+'-01-01';next=(+value+1)+'-01-01';period='month';}
  else {first=value+'-01';next=eacShift(first,32).slice(0,7)+'-01';}
  return {first,next,start:eacMidnight(first,zone),end:eacMidnight(next,zone),period,today:first===today&&next===eacShift(today,1)};
}
function eacRegisterRows(result, ids, range, zone) {
  const rows=new Map();
  for(const [i,direction] of ['import','export','net'].entries()) {
    for(const r of result[ids[direction]]||[]) {
      const t=typeof r.start==='number'?r.start:Date.parse(r.start);
      if(!Number.isFinite(t)||t<range.start||t>=range.end||!Number.isFinite(r.change))continue;
      const key=eacDay(t,zone);const row=rows.get(key)||{key,t,values:[null,null,null]};
      row.values[i]=r.change; rows.set(key,row);
    }
  }
  return [...rows.values()].sort((a,b)=>a.t-b.t);
}
function eacTotals(rows) {
  const total=i=>{const values=rows.map(r=>r.values[i]).filter(Number.isFinite);return values.length?values.reduce((a,b)=>a+b,0):null;};
  // Net register series uses matching import/export timestamps, not mismatched totals.
  return {imported:total(0),exported:total(1),net:total(2)};
}
function eacIntervals(profile, range) {
  return (profile.points||[]).filter(p=>p[0]>range.start&&p[0]<=range.end).map(p=>({t:p[0],key:eacDay(p[0]-1,profile.time_zone),values:[p[1],p[2],Number.isFinite(p[1])&&Number.isFinite(p[2])?p[1]-p[2]:null]}));
}
function eacProvisional(rows) {
  // Both directions must be observed at the same time to claim a net balance.
  const paired=rows.filter(r=>Number.isFinite(r.values[0])&&Number.isFinite(r.values[1]));
  return {...eacTotals(rows),net:paired.length?paired.reduce((s,r)=>s+r.values[2],0):null,paired:paired.length};
}
function eacSelection(profile, range, registerRows) {
  const intervals=eacIntervals(profile,range);
  const singleDay=range.next===eacShift(range.first,1);
  const hasRegisters=registerRows.some(r=>r.values.slice(0,2).some(Number.isFinite));
  const fallback=singleDay&&!range.today&&!hasRegisters&&intervals.some(r=>r.values.slice(0,2).some(Number.isFinite));
  const provisional=range.today||fallback;
  const expected=(range.end-range.start)/1800000;
  return {intervals,fallback,provisional,expected,totals:provisional?eacProvisional(intervals):eacTotals(registerRows)};
}
function eacExportAverage(result, id, zone, now=Date.now()) {
  const today=eacDay(now,zone),keys=Array.from({length:7},(_,i)=>eacShift(today,-i-1));
  const values=new Map();
  for(const row of result[id]||[]) {const key=eacDay(row.start,zone);if(keys.includes(key)&&Number.isFinite(row.change)&&row.change>=0)values.set(key,row.change);}
  return values.size===7?[...values.values()].reduce((a,b)=>a+b,0)/7:null;
}
function eacAverageSummary(result, id, profile, now=Date.now()) {
  const zone=profile.time_zone||'Asia/Nicosia';
  const registered=eacExportAverage(result,id,zone,now);
  if(Number.isFinite(registered))return {value:registered,label:'Last 7 completed days · registers'};
  const today=eacDay(now,zone);
  const points=new Map((profile.points||[]).filter(p=>Number.isFinite(p[0])&&Number.isFinite(p[2])&&p[2]>=0).map(p=>[p[0],p[2]]));
  let complete=0,sum=0;
  for(let i=1;i<=7;i++){
    const day=eacShift(today,-i),start=eacMidnight(day,zone),end=eacMidnight(eacShift(day,1),zone);
    let valid=true,total=0;
    for(let t=start+1800000;t<=end;t+=1800000){if(!points.has(t)){valid=false;break;}total+=points.get(t);}
    if(valid){complete++;sum+=total;}
  }
  return complete===7?{value:sum/7,label:'Last 7 completed days · provisional intervals'}:
    {value:null,label:`Waiting for complete data · ${complete}/7 interval days complete`};
}
class EacEnergyDashboard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});this._mode='month';this._value=eacDay(Date.now()).slice(0,7);this._chartMode='energy';this._style='line';this._meters=[];this._request=0;this._statsCache=new Map();this._details=false;}
  connectedCallback(){if(typeof ResizeObserver!=='undefined'){this._resize=new ResizeObserver(()=>{const narrow=this.clientWidth<600;if(narrow!==this._narrow){this._narrow=narrow;if(this._data)this._render();}});this._resize.observe(this);}}
  disconnectedCallback(){this._resize?.disconnect();}
  setConfig(config){this._config=config;this._entity=config.entity||'';}
  getCardSize(){return 18;}
  set hass(hass){this._hass=hass;if(!this._config)return;const stamp=hass.states[this._entity]?.last_updated;if(!this._busy&&Date.now()-(this._attemptAt||0)>60000&&(!this._data||stamp!==this._stamp))this._load();}
  async _load(){
    const request=++this._request;this._busy=true;this._attemptAt=Date.now();this._render();
    try {
      const meters=await this._hass.callWS({type:'eac_cyprus/profile_meters'});
      if(request!==this._request)return;this._meters=meters;
      if(!meters.some(m=>m.entity_id===this._entity))this._entity=meters[0]?.entity_id||'';
      if(!this._entity)throw Error('No readable meters');
      const data=await this._hass.callWS({type:'eac_cyprus/profile',entity_id:this._entity});
      if(request!==this._request)return;
      this._data=data;this._stamp=this._hass.states[this._entity]?.last_updated;this._error='';
      await this._loadStatistics(request);
    }catch {if(request===this._request){this._data=null;this._rows=[];this._average=null;this._error='Unable to load this meter. Check the integration and your access permissions.';}}
    finally{if(request===this._request){this._busy=false;this._render();}}
  }
  _range(){return eacPeriod(this._mode,this._value,this._data?.time_zone||'Asia/Nicosia');}
  async _statistics(range,ids){
    const key=JSON.stringify([this._entity,ids,range.first,range.next,range.period]);const cached=this._statsCache.get(key);
    if(cached&&Date.now()-cached.at<300000)return cached.data;
    const data=await this._hass.callWS({type:'recorder/statistics_during_period',start_time:new Date(range.start).toISOString(),end_time:new Date(range.end).toISOString(),statistic_ids:ids,period:range.period,types:['change']});
    if(this._statsCache.size>=12)this._statsCache.delete(this._statsCache.keys().next().value);
    this._statsCache.set(key,{data,at:Date.now()});return data;
  }
  async _loadStatistics(request){
    const d=this._data,ids=d.statistic_ids;this._rows=[];this._average=null;this._averageInfo=null;this._statsError='';
    if(!ids){this._statsError='Update the integration to use register history on this page.';return;}
    const range=this._range(),zone=d.time_zone;
    const outcomes=await Promise.allSettled([
      range.today?Promise.resolve({}):this._statistics(range,Object.values(ids)),
      this._statistics(eacPeriod('week','',zone),[ids.export])
    ]);
    if(request!==this._request)return;
    if(outcomes[0].status==='fulfilled')this._rows=eacRegisterRows(outcomes[0].value,ids,range,zone);else this._statsError='Register history is unavailable. Try refreshing.';
    this._averageInfo=eacAverageSummary(outcomes[1].status==='fulfilled'?outcomes[1].value:{},ids.export,d);
    this._average=this._averageInfo.value;
  }
  async _selectPeriod(){const request=++this._request;this._busy=true;this._rows=[];this._statsError='';this._render();try{await this._loadStatistics(request);}finally{if(request===this._request){this._busy=false;this._render();}}}
  _when(t,onlyTime=false){if(!t)return 'Not available';return new Date(t).toLocaleString(undefined,{timeZone:this._data?.time_zone||'Asia/Nicosia',...(onlyTime?{}:{month:'short',day:'numeric'}),hour:'2-digit',minute:'2-digit',hour12:false});}
  _label(){const r=this._range();if(this._mode==='today')return 'Today so far';if(this._mode==='yesterday')return 'Yesterday · '+new Date(r.start+12*3600000).toLocaleDateString(undefined,{timeZone:this._data.time_zone,month:'short',day:'numeric'});if(this._mode==='week')return 'Last 7 completed days';if(this._mode==='year')return this._value;return new Date(r.start+12*3600000).toLocaleDateString(undefined,{timeZone:this._data.time_zone,year:'numeric',month:'long',...(this._mode==='day'?{day:'numeric'}:{})});}
  _chart(rows,power=false){
    if(!rows.some(r=>r.values.some(Number.isFinite)))return '<div class="empty"><ha-icon icon="mdi:chart-line"></ha-icon><strong>No readings for this selection</strong><span>Missing data is not zero. Try another period.</span></div>';
    const zone=this._data.time_zone,range=this._range();
    const from=range.start,to=Math.min(range.end,eacMidnight(eacShift(eacDay(Date.now(),zone),1),zone));
    const width=this._narrow?580:980,plotWidth=width-92;
    const values=rows.flatMap(r=>r.values.slice(0,power?2:3).filter(Number.isFinite).map(v=>power?v*2:v));
    const max=Math.max(1,...values),min=Math.min(0,...values),span=max-min;
    const high=max+span*.12,low=min<0?min-span*.08:0;
    const x=t=>52+(t-from)/(to-from)*plotWidth,y=v=>242-(v-low)/(high-low)*204;
    const label=t=>new Date(t).toLocaleString(undefined,{timeZone:zone,...(power&&['day','today','yesterday'].includes(this._mode)?{hour:'2-digit',minute:'2-digit',hour12:false}:this._mode==='year'?{month:'short'}:{month:'short',day:'numeric'})});
    let svg=[0,1,2,3,4].map(i=>{const v=low+(high-low)*i/4;return `<line x1="52" x2="${width-40}" y1="${y(v)}" y2="${y(v)}" class="gridline"/><text x="42" y="${y(v)+4}" text-anchor="end">${eacNumber(v)}</text>`;}).join('');
    svg+=`<line x1="52" x2="${width-40}" y1="${y(0)}" y2="${y(0)}" stroke="var(--muted)" opacity=".35"/>`;
    svg+=`<text x="52" y="18">${power?'kW · half-hour average':'kWh'}</text>`;
    svg+=[0,1,2,3,4].map(i=>{const t=from+(to-from)*i/4;return `<text x="${x(t)}" y="270" text-anchor="${i===0?'start':i===4?'end':'middle'}">${eacEscape(label(t))}</text>`;}).join('');
    const count=power?2:3;
    for(let index=0;index<count;index++){
      let prev=null;const path=[];
      for(const row of rows){
        const value=row.values[index];if(!Number.isFinite(value)){prev=null;continue;}
        const v=power?value*2:value;
        const adjacent=prev&&(power?row.t-prev.t===1800000:this._mode==='year'?row.key.slice(0,7)===eacShift(prev.key,32).slice(0,7):row.key===eacShift(prev.key,1));
        const title=eacEscape(`${label(row.t)} · ${['Grid import','Solar export','Net balance'][index]}: ${eacNumber(v,3)} ${power?'kW':'kWh'}`);
        if(this._style==='bar'&&!power){const units=Math.max(1,(to-from)/(this._mode==='year'?31:1)/86400000);const width=Math.min(22,plotWidth/units/4);const xx=x(row.t)+index*width;svg+=`<rect x="${xx}" y="${Math.min(y(v),y(0))}" width="${width*.82}" height="${Math.max(1,Math.abs(y(0)-y(v)))}" rx="2" fill="${EAC_COLORS[index]}"><title>${title}</title></rect>`;}
        else {path.push(`${adjacent?'L':'M'}${x(row.t).toFixed(2)},${y(v).toFixed(2)}`);svg+=`<circle cx="${x(row.t)}" cy="${y(v)}" r="${power?1.8:3.2}" fill="${EAC_COLORS[index]}"><title>${title}</title></circle>`;}
        prev=row;
      }
      if(this._style!=='bar'||power)svg+=`<path d="${path.join(' ')}" stroke="${EAC_COLORS[index]}"/>`;
    }
    return `<svg class="timeline" viewBox="0 0 ${width} 290" role="img" aria-label="${power?'Half-hour power':'Energy'} import and export chart">${svg}</svg>`;
  }
  _surplus(){
    const slots=this._data.surplus_by_half_hour||[],top=Math.max(.1,...slots.map(p=>Number.isFinite(p[1])?p[1]:0));
    if(!slots.some(p=>Number.isFinite(p[1])))return '<p class="empty-small">No export profile available.</p>';
    return `<svg viewBox="0 0 520 155" role="img" aria-label="Typical exported power by time of day"><text x="14" y="16">kW · peak average ${eacNumber(top)}</text>${slots.map(p=>{if(!Number.isFinite(p[1]))return '';const hour=String(Math.floor(p[0]/2)).padStart(2,'0')+':'+(p[0]%2?'30':'00');const h=p[1]/top*90;return `<rect x="${14+p[0]*10.2}" y="${120-h}" width="7.8" height="${Math.max(1,h)}" rx="2" fill="#f3b953" opacity="${p[1]>0?1:.25}"><title>${hour} · ${eacNumber(p[1],2)} kW · ${p[2]} observations</title></rect>`;}).join('')}${[0,6,12,18,24].map(h=>`<text x="${14+h/24*489.6}" y="145" text-anchor="${h===0?'start':h===24?'end':'middle'}">${String(h).padStart(2,'0')}:00</text>`).join('')}</svg>`;
  }
  _render(){
    const d=this._data,esc=eacEscape,n=eacNumber;
    const css=EAC_DASHBOARD_CSS;
    if(!d){this.shadowRoot.innerHTML=`<style>${css}</style><main><header><div><div class="eyebrow">YOUR ENERGY, AT A GLANCE</div><h1>Solar & grid</h1></div></header><section class="panel empty" role="status">${esc(this._error||'Loading your energy dashboard…')}</section></main>`;return;}
    const range=this._range(),today=range.today;
    const {intervals,fallback,provisional,expected,totals}=eacSelection(d,range,this._rows||[]);
    const available=!this._busy&&(!this._statsError||provisional);
    const net=available?totals.net:null;
    const direction=net===null?'Waiting for readings':net<-.005?'More sent than bought':net>.005?'More bought than sent':'Imports and exports match';
    const current=this._mode==='month'&&this._value===eacDay(Date.now(),d.time_zone).slice(0,7)||this._mode==='year'&&this._value===eacDay(Date.now(),d.time_zone).slice(0,4);
    const source=fallback?'Provisional · daily register pending':today?'Provisional half-hour readings':`Register changes${current?' · period in progress':''}`;
    const through=provisional?intervals.at(-1)?.t:d.data_through;
    const rawChart=this._chartMode==='power'||provisional;
    const chart=rawChart?intervals:this._rows||[];
    const input=this._mode==='day'?`<input id="date" aria-label="Selected day" type="date" value="${esc(this._value)}" max="${eacDay(Date.now(),d.time_zone)}">`:this._mode==='month'?`<input id="date" aria-label="Selected month" type="month" value="${esc(this._value)}" max="${eacDay(Date.now(),d.time_zone).slice(0,7)}">`:this._mode==='year'?`<input id="date" aria-label="Selected year" type="number" min="2000" max="${new Date().getFullYear()}" value="${esc(this._value)}">`:'';
    const kpi=(label,value,color,caption)=>`<div class="metric ${color}"><div class="metric-label">${label}</div><div class="metric-value">${available?n(value):'—'} <span>kWh</span></div><div class="muted">${caption}</div></div>`;
    const hour=h=>String(h??0).padStart(2,'0')+':00';
    const dateDetails=rawChart?`Half-hour readings available within the last ${d.window_days} days. Lines break at gaps.`:'Midnight registers close the preceding day. Gaps accumulate on the next reading; missing dates are not zero.';
    const sumScope=provisional?`${totals.paired||0}${fallback?'/'+expected:''} paired half-hours · net uses matching intervals`:'Net uses the matched register series; mismatched import/export dates may differ.';
    this.shadowRoot.innerHTML=`<style>${css}</style><main>
      <header><div><div class="eyebrow"><span class="sun">✦</span> YOUR ENERGY, AT A GLANCE</div><h1>Solar & grid</h1><p class="subtitle">See what you buy, what you send back, and when.</p></div><div class="header-tools"><select id="meter" aria-label="Meter">${this._meters.map(m=>`<option value="${esc(m.entity_id)}" ${m.entity_id===this._entity?'selected':''}>${esc(m.name)}</option>`).join('')}</select><button class="refresh" id="refresh" aria-label="Refresh cached readings" title="Refresh from Home Assistant">↻</button></div></header>
      <div class="status"><span class="dot ${d.available?'':'offline'}"></span><span>${d.available?'DSO readings':'Cached readings · portal unavailable'} through <strong>${esc(this._when(d.data_through))}</strong></span><span class="checked" title="Time of the last successful DSO fetch, not the browser refresh">${d.available?'Last checked':'Last successful check'} <strong>${esc(this._when(d.fetched_at))}</strong></span><span class="status-note">Delayed data · Cyprus time</span></div>
      <nav class="toolbar" aria-label="Period controls"><div class="segmented">${[['today','Today'],['yesterday','Yesterday'],['week','7 days'],['month','Month'],['year','Year'],['day','Custom']].map(([key,label])=>`<button data-period="${key}" aria-pressed="${this._mode===key}" class="${this._mode===key?'active':''}">${label}</button>`).join('')}</div><div class="date-control">${input}<span>${esc(this._label())}</span></div></nav>
      <section class="panel summary" aria-busy="${this._busy}" aria-label="Selected period energy balance"><div class="summary-top"><h2>${esc(this._label())}</h2><span class="badge">${esc(source)}</span></div><div class="metrics">${kpi('↙ From the grid',totals.imported,'blue','Electricity you bought')}${kpi('↗ To the grid',totals.exported,'gold','Solar electricity exported')}<div class="metric net"><div class="metric-label">⇄ Net grid balance</div><div class="metric-value">${n(net)} <span>kWh</span></div><div class="muted">${direction}</div></div></div><div class="summary-foot"><span>${esc(this._busy?'Loading selected period…':this._statsError||sumScope)}</span><span>Import − export · energy, not money</span></div></section>
      <section class="panel chart-panel"><div class="section-head"><div><div class="eyebrow">YOUR ENERGY OVER TIME</div><h2>Import vs export</h2></div><div class="chart-controls">${!provisional?`<select id="chart-mode" aria-label="Chart measurement"><option value="energy" ${this._chartMode==='energy'?'selected':''}>${range.period==='month'?'Monthly':'Daily'} energy · kWh</option><option value="power" ${this._chartMode==='power'?'selected':''}>Half-hour power · kW</option></select>`:'<span class="badge">Half-hour power · kW</span>'}${!rawChart?`<div class="segmented small"><button data-style="line" class="${this._style==='line'?'active':''}" aria-pressed="${this._style==='line'}">Line</button><button data-style="bar" class="${this._style==='bar'?'active':''}" aria-pressed="${this._style==='bar'}">Bars</button></div>`:''}</div></div><div class="legend"><span class="blue">● Grid import</span><span class="gold">● Solar export</span>${rawChart?'':'<span class="purple">● Net balance</span>'}</div>${this._busy?'<div class="empty" role="status">Loading chart…</div>':this._chart(chart,rawChart)}<p class="chart-note">${esc(dateDetails)}</p>${provisional?`<p class="chart-note">${fallback?'Daily register totals are not available yet. Showing provisional half-hour totals. ':''}Received through ${esc(this._when(through))}. Missing intervals are excluded; totals may be revised.</p>`:''}</section>
      <div class="section-divider"><div><div class="eyebrow">UNDERSTAND YOUR PATTERNS</div><h2>Beyond the totals</h2></div><span class="muted">Based on retained history · independent of selected period</span></div>
      <div class="insight-grid"><section class="panel surplus"><div class="section-head"><div><h2>Usual surplus-solar hours</h2><p class="muted">When you typically send energy back to the grid.</p></div><span class="sun">☀</span></div>${this._surplus()}<p class="chart-note">Average export across ${d.window_days} retained days. Observed zeros count; missing samples do not. Historical pattern, not a forecast.</p></section>
      <section class="panel habits"><div class="habit"><div><span class="muted">Avg. daily solar export</span><p>${esc(this._averageInfo?.label||'Last 7 completed days')}</p></div><strong class="gold">${n(this._average)} <small>kWh/day</small></strong></div><div class="habit"><div><span class="muted">Overnight grid demand</span><p>${hour(d.night_start_hour)}–${hour(d.night_end_hour)} · ${d.complete_nights} complete nights</p></div><strong>${n(Number.isFinite(d.overnight_baseline_kw)?d.overnight_baseline_kw*1000:null,0)} <small>W</small></strong></div><div class="habit"><div><span class="muted">Highest half-hour demand</span><p>${esc(this._when(d.peak_import_at))}</p></div><strong>${n(d.peak_import_kw,2)} <small>kW</small></strong></div><p class="chart-note">Overnight demand includes EV charging and heating. A dash means insufficient readings.</p></section></div>
      <section class="panel metadata"><div class="metadata-top"><div><span class="muted">Your tariff</span><strong>${esc(d.tariff?.code||'Unknown')}</strong><span class="muted">Reported by DSO · prices not inferred</span></div><div class="coverage"><span>Half-hour coverage · ${d.window_days} days</span><div class="coverage-track"><i style="width:${Math.max(0,Math.min(100,d.import_coverage_percent||0))}%"></i></div><span>Import ${n(d.import_coverage_percent)}% · export ${n(d.export_coverage_percent)}%</span></div></div><details ${this._details?'open':''}><summary>Meter details & how to read this page</summary><div class="detail-grid"><div><h3>Meter & connection</h3><p>${esc(d.model||'Model unavailable')}<br>${esc(d.phases||'—')} phases · ${esc(d.load_entitlement||'—')} ${esc(d.load_entitlement_unit||'')}<br>Tariff checked ${esc(this._when(d.tariff?.retrieved_at))}<br>Last portal fetch ${esc(this._when(d.fetched_at))}</p></div><div><h3>What these figures measure</h3><p>Grid import and export only. Solar used directly at home and total solar generation require inverter data. Negative net means more exported than imported; it is not a payment credit.</p></div><div><h3>Coverage & calculation</h3><p>Missing readings stay missing. The export average requires seven complete calendar days. If daily registers are pending, a complete seven-day set of half-hour exports supplies a provisional average. Partial days are never treated as zero. Overnight baseline is the median of complete nights. Change history length and overnight hours in the integration options.</p></div></div></details></section>
      <footer>Powered by your EAC DSO readings · No live inverter data</footer></main>`;
    this._events();
  }
  _events(){
    const root=this.shadowRoot;
    root.querySelector('#meter').onchange=e=>{this._entity=e.target.value;this._data=null;this._rows=[];this._average=null;this._statsCache.clear();this._load();};
    root.querySelector('#refresh').onclick=()=>{this._statsCache.clear();this._load();};
    for(const button of root.querySelectorAll('[data-period]'))button.onclick=()=>{this._mode=button.dataset.period;const today=eacDay(Date.now(),this._data.time_zone);this._value=this._mode==='year'?today.slice(0,4):this._mode==='month'?today.slice(0,7):today;this._selectPeriod();};
    const date=root.querySelector('#date');if(date)date.onchange=e=>{if(!e.target.value||!e.target.checkValidity())return;this._value=e.target.value;this._selectPeriod();};
    const mode=root.querySelector('#chart-mode');if(mode)mode.onchange=e=>{this._chartMode=e.target.value;this._render();};
    for(const button of root.querySelectorAll('[data-style]'))button.onclick=()=>{this._style=button.dataset.style;this._render();};
    root.querySelector('details').ontoggle=e=>{this._details=e.target.open;};
  }
}
const EAC_DASHBOARD_CSS = `
:host{display:block;color:var(--primary-text-color,#e7edf3);font-family:var(--paper-font-body1_-_font-family,system-ui,sans-serif);--ink:var(--primary-text-color,#e7edf3);--muted:var(--secondary-text-color,#98a7b5);--line:var(--divider-color,rgba(149,170,190,.16));--surface:var(--ha-card-background,var(--card-background-color,#182129));--blue:#56b8ed;--gold:#f3b953;--purple:#b89ae8}
*{box-sizing:border-box}main{max-width:1280px;margin:auto;padding:32px 28px 20px}header{display:flex;align-items:center;justify-content:space-between;gap:20px}.eyebrow{font-size:10px;font-weight:750;letter-spacing:.16em;color:var(--muted)}.sun{color:var(--gold);font-size:25px;vertical-align:middle;margin-right:5px}h1{font-size:clamp(28px,4vw,40px);letter-spacing:-.045em;margin:10px 0 6px;line-height:1.1;font-weight:740}h2{font-size:18px;letter-spacing:-.02em;margin:6px 0;font-weight:650}h3{font-size:13px;margin:12px 0 6px}p{margin:5px 0;line-height:1.6}.subtitle{font-size:13px;color:var(--muted)}.header-tools{display:flex;gap:8px;align-items:center}.header-tools select{max-width:240px}.status{display:flex;align-items:center;gap:7px;font-size:11px;color:var(--muted);margin:22px 0}.status strong{font-weight:500;color:var(--ink)}.dot{width:6px;height:6px;flex-shrink:0;border-radius:50%;background:#81bfa8}.offline{background:var(--gold)}.checked{margin-left:12px}.status-note{margin-left:auto}.toolbar{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:18px;flex-wrap:wrap}.segmented{display:flex;background:var(--surface);border:1px solid var(--line);border-radius:11px;padding:4px;gap:3px}.segmented button{border:0;background:none;padding:8px 18px;color:var(--muted)}.segmented button.active{background:rgba(138,167,194,.17);color:var(--ink);box-shadow:0 1px 3px #0002}.date-control{display:flex;gap:10px;align-items:center}.date-control span{display:none}button,select,input{font:inherit;font-size:12px;border-radius:8px;border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:10px 12px;min-height:38px}button,select,summary{cursor:pointer}button:focus-visible,select:focus-visible,input:focus-visible,summary:focus-visible{outline:2px solid var(--blue);outline-offset:3px}input{color-scheme:dark light;max-width:180px}input[type=number]{width:100px}.refresh{font-size:22px;width:40px;height:40px;padding:0}.panel{background:var(--surface);border:1px solid var(--line);border-radius:18px;padding:24px;box-shadow:0 5px 16px #00000005}.summary{background:linear-gradient(115deg,rgba(86,184,237,.055),transparent 45%,rgba(184,154,232,.055)),var(--surface)}.summary-top{display:flex;align-items:center;justify-content:space-between;gap:10px}.badge{font-size:10px;color:var(--muted);padding:6px 9px;border:1px solid var(--line);border-radius:6px;white-space:nowrap}.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:24px;margin:25px 0}.metric+.metric{border-left:1px solid var(--line);padding-left:24px}.metric-label{font-size:12px;font-weight:550}.metric-value{font-size:clamp(25px,3.5vw,41px);font-weight:650;letter-spacing:-.035em;font-variant-numeric:tabular-nums;margin:10px 0 7px;white-space:nowrap}.metric-value span{font-size:14px;font-weight:450;letter-spacing:0;color:var(--muted)}.muted{color:var(--muted);font-size:11px;line-height:1.5}.blue{color:var(--blue)}.gold{color:var(--gold)}.purple,.net .metric-label,.net .metric-value{color:var(--purple)}.summary-foot{display:flex;justify-content:space-between;gap:14px;font-size:10px;line-height:1.6;color:var(--muted);border-top:1px solid var(--line);padding-top:14px}.chart-panel{margin-top:18px}.section-head{display:flex;justify-content:space-between;align-items:center;gap:14px}.chart-controls{display:flex;gap:8px;align-items:center}.small button{padding:6px 12px;min-height:30px}.legend{display:flex;gap:20px;font-size:11px;margin:20px 0 9px}svg{display:block;width:100%;overflow:visible}svg text{fill:var(--muted);font:11px system-ui,sans-serif}svg path{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}.gridline{stroke:var(--line);stroke-dasharray:3 5}.chart-note{font-size:10px;color:var(--muted);line-height:1.7;margin-top:10px}.empty{min-height:220px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;text-align:center;color:var(--muted);font-size:13px}.empty ha-icon{--mdc-icon-size:32px;opacity:.5}.empty span{font-size:12px}.section-divider{display:flex;justify-content:space-between;align-items:end;gap:15px;margin:32px 0 15px}.insight-grid{display:grid;grid-template-columns:1.2fr 1fr;gap:18px}.surplus svg{margin-top:25px}.habits{display:flex;flex-direction:column;justify-content:space-between}.habit{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 0}.habit+.habit{border-top:1px solid var(--line)}.habit p{font-size:10px;color:var(--muted);margin-top:3px}.habit strong{font-size:24px;white-space:nowrap;font-variant-numeric:tabular-nums;letter-spacing:-.025em}.habit small{font-size:11px;font-weight:400;color:var(--muted)}.metadata{margin-top:18px}.metadata-top{display:flex;justify-content:space-between;gap:25px}.metadata-top>div:first-child{display:flex;align-items:center;gap:14px;flex-wrap:wrap}.metadata strong{font-size:21px;letter-spacing:.04em}.coverage{width:250px;max-width:100%;font-size:10px;color:var(--muted)}.coverage-track{height:4px;border-radius:5px;background:var(--line);margin:8px 0}.coverage-track i{display:block;height:100%;background:var(--blue);border-radius:5px}details{margin-top:20px;border-top:1px solid var(--line);padding-top:15px}summary{font-size:12px;color:var(--muted);padding:3px 0}.detail-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:24px}.detail-grid p{font-size:11px;color:var(--muted)}footer{text-align:center;color:var(--muted);font-size:10px;padding:22px 0 5px}
@media(min-width:1100px){.timeline{max-height:330px}}@media(max-width:760px){main{padding:20px 14px}.header-tools select{max-width:170px}.insight-grid{grid-template-columns:1fr}.section-head{align-items:start;flex-wrap:wrap}.section-divider{align-items:start;flex-direction:column;gap:0}.panel{padding:18px}.metrics{gap:14px}.metric+.metric{padding-left:14px}.summary-foot{flex-direction:column;gap:3px}.detail-grid{grid-template-columns:1fr;gap:0}.chart-controls{width:100%;justify-content:space-between}.metadata-top{flex-direction:column;gap:18px}.coverage{width:100%}.status{flex-wrap:wrap}.checked{margin-left:13px}.status-note{margin-left:13px}.timeline{min-height:180px}.legend{gap:14px}}
@media(max-width:480px){.toolbar>.segmented{display:flex;flex-wrap:nowrap;min-width:0;max-width:100%;overflow-x:auto;gap:2px}.toolbar>.segmented button{flex:1 0 auto;white-space:nowrap;padding:8px 5px;font-size:11px;min-height:40px}header{align-items:start;flex-direction:column;gap:16px}.header-tools{width:100%}.header-tools select{max-width:none;flex:1}.status{margin:18px 0}.toolbar{gap:10px}.segmented{width:100%;justify-content:space-between}.segmented button{padding:8px 14px}.small{width:auto}.small button{padding:6px 10px}.date-control{width:100%;justify-content:space-between}.date-control span{display:block;font-size:11px;color:var(--muted)}.summary-top{align-items:start;flex-direction:column;gap:2px}.metrics{grid-template-columns:1fr 1fr;margin:20px 0 15px;gap:18px}.metric-value{font-size:29px}.metric.net{grid-column:1/-1;border-left:none;border-top:1px solid var(--line);padding:16px 0 0;display:grid;grid-template-columns:1fr auto;align-items:center}.metric.net .metric-value{grid-column:2;grid-row:1/3;margin:0}.metric.net .muted{grid-column:1}.metric-value span{font-size:12px}.chart-controls select{min-width:0;max-width:65%;font-size:11px}.panel{border-radius:14px}.legend{font-size:10px}.chart-note{font-size:10px}.timeline{min-height:160px}.timeline text{font-size:16px}.surplus svg text{font-size:15px}.habit strong{font-size:22px}}
@media(prefers-reduced-motion:no-preference){button{transition:background .15s}button:hover{background:rgba(138,167,194,.12)}}`;
if(!customElements.get('eac-energy-dashboard'))customElements.define('eac-energy-dashboard',EacEnergyDashboard);
window.customCards=window.customCards||[];window.customCards.push({type:'eac-energy-dashboard',name:'EAC Solar & grid dashboard',description:'One responsive page for balances, history, surplus and meter insights'});
