/* Select provisional data only for TODAY alone. Never add it to register
 * totals for a month, year or historical day (that would risk double counting). */
function solarBalanceModel(data,state,config={},now=new Date(),zone='Asia/Nicosia') {
  const dayKey=value=>{
    const parts=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(value).map(p=>[p.type,p.value]));
    return `${parts.year}-${parts.month}-${parts.day}`;
  };
  const start=new Date(data?.start);
  const end=data?.end?new Date(data.end):now;
  const empty=explanation=>({mode:'empty',explanation});
  if(!Number.isFinite(+start)||!Number.isFinite(+end)) return empty('Waiting for the selected period and its readings.');
  const today=dayKey(now);
  const todayOnly=dayKey(start)===today && dayKey(new Date(+end-1))===today && end-start<=26*3600000;
  if(todayOnly) {
    const a=state?.attributes;
    if(state && !['unknown','unavailable'].includes(state.state) && a?.date===today &&
        Number.isFinite(a.import_kwh)&&a.import_kwh>=0&&Number.isFinite(a.export_kwh)&&a.export_kwh>=0&&a.paired_intervals>0&&Number.isFinite(Date.parse(a.data_through))) {
      const through=new Date(a.data_through).toLocaleTimeString(undefined,{timeZone:zone,hour:'2-digit',minute:'2-digit',hour12:false});
      const coverage=`${a.paired_intervals} paired half-hours received`;
      const gaps=a.gaps_before_latest>0?' Missing intervals are excluded from these totals.':'';
      return {mode:'provisional',imported:a.import_kwh,exported:a.export_kwh,
        explanation:`Today so far through ${through} · ${coverage}. Delayed DSO data; not a completed daily total.${gaps}`};
    }
    return empty('Today’s readings have not arrived yet. Missing data does not mean zero consumption or export.');
  }
  const grids=data?.prefs?.energy_sources?.filter(s=>s.type==='grid')||[];
  const ids=[config.import_statistic,config.export_statistic].filter(Boolean);
  if(!config.import_statistic) ids.push(...grids.map(g=>g.stat_energy_from).filter(Boolean));
  if(!config.export_statistic) ids.push(...grids.map(g=>g.stat_energy_to).filter(Boolean));
  const observed=id=>(data.stats?.[id]||[]).some(r=>{
    const stamp=typeof r.start==='number'?r.start:Date.parse(r.start);
    return stamp>=+start && stamp<=+end && (Number.isFinite(r.change)||Number.isFinite(r.sum));
  });
  if(!ids.length||!ids.every(observed)) return empty('No matching import/export readings for this period yet. Missing data is not zero.');
  return {mode:'register'};
}
/* Solar balance presentation. Uses HA's native energy card for selected-period
 * calculations; no extra API requests, polling, libraries, or credentials.
 * If HA changes the native markup, show its original card as a fallback. */
class SolarBalanceCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: 'open'});
    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; }
        ha-card { overflow:hidden; border-radius:20px; padding:22px; box-sizing:border-box; }
        .surface[hidden], .native[hidden] { display:none; }
        .native.ready { position:absolute; width:1px; height:1px; overflow:hidden; clip-path:inset(50%); pointer-events:none; }
        .eyebrow { font-size:11px; font-weight:700; letter-spacing:.13em; text-transform:uppercase; color:var(--secondary-text-color); }
        .top { display:flex; justify-content:space-between; align-items:center; gap:12px; }
        .period { color:var(--secondary-text-color); font-size:12px; }
        .hero { margin:18px 0; padding:20px; border-radius:15px; background:linear-gradient(120deg,rgba(249,168,37,.15),rgba(249,168,37,.025)); border:1px solid rgba(249,168,37,.24); --accent:#f9a825; }
        .hero.import { --accent:#64b5f6; background:linear-gradient(120deg,rgba(25,118,210,.17),rgba(25,118,210,.025)); border-color:rgba(100,181,246,.27); }
        .hero.balanced { --accent:var(--secondary-text-color); background:var(--secondary-background-color); border-color:var(--divider-color); }
        .direction { display:flex; align-items:center; gap:8px; font-size:12px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; color:var(--accent); }
        .direction ha-icon { --mdc-icon-size:20px; }
        .amount { color:var(--primary-text-color); font-size:clamp(32px,5vw,44px); line-height:1.2; font-weight:750; letter-spacing:-.035em; margin:10px 0 7px; font-variant-numeric:tabular-nums; }
        .explanation { color:var(--secondary-text-color); font-size:13px; line-height:1.5; }
        .flows { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:12px; }
        .flow { padding:14px; border-radius:13px; background:var(--secondary-background-color); border:1px solid var(--divider-color); }
        .label { display:flex; align-items:center; gap:7px; font-size:12px; color:var(--secondary-text-color); }
        .label ha-icon { --mdc-icon-size:18px; flex-shrink:0; }
        .in ha-icon, .in .flow-value { color:#64b5f6; }
        .out ha-icon, .out .flow-value { color:#f9a825; }
        .flow-value { margin:9px 0 3px; font-size:22px; font-weight:650; font-variant-numeric:tabular-nums; white-space:nowrap; }
        .caption { font-size:11px; line-height:1.4; color:var(--secondary-text-color); }
        .average { display:flex; justify-content:space-between; align-items:center; gap:10px; margin-top:16px; padding-top:15px; border-top:1px solid var(--divider-color); font-size:12px; color:var(--secondary-text-color); }
        .average strong { color:var(--primary-text-color); font-size:14px; white-space:nowrap; font-variant-numeric:tabular-nums; }
        .foot { margin-top:12px; font-size:11px; line-height:1.5; color:var(--secondary-text-color); }
        @media(max-width:360px) { ha-card {padding:16px} .hero {padding:16px} .flow {padding:10px} .flow-value {font-size:19px} }
      </style>
      <ha-card class="surface" hidden aria-label="Grid energy balance">
        <div class="top"><div class="eyebrow">Your grid balance</div><div class="period">Selected period</div></div>
        <div class="hero" role="status" aria-live="polite">
          <div class="direction"><ha-icon></ha-icon><span></span></div>
          <div class="amount"></div><div class="explanation"></div>
        </div>
        <div class="flows">
          <div class="flow in"><div class="label"><ha-icon icon="mdi:home-import-outline"></ha-icon>From the grid</div><div class="flow-value imported"></div><div class="caption">Electricity you bought</div></div>
          <div class="flow out"><div class="label"><ha-icon icon="mdi:home-export-outline"></ha-icon>To the grid</div><div class="flow-value exported"></div><div class="caption">Solar electricity you sent back</div></div>
        </div>
        <div class="average"><span>Avg. solar export · last 7 days</span><strong class="average-value">Loading…</strong></div>
        <div class="foot">Net balance = imported − exported. Energy only; this is not a bill or payment credit.</div>
      </ha-card><div class="native"></div>`;
  }
  setConfig(config) { this._config=config; if(this.isConnected) this._mountSource(); }
  set hass(value) { this._hass=value; if(this._source) this._source.hass=value; this._refreshAverage(); this._sync(); }
  getCardSize() { return 4; }
  getLayoutOptions() { return {grid_columns:4,grid_rows:5}; }
  connectedCallback() { if(this._config) this._mountSource(); }
  disconnectedCallback() { this._observer?.disconnect(); this._generation=(this._generation||0)+1; }
  async _mountSource() {
    const generation=this._generation=(this._generation||0)+1;
    const helpers=await window.loadCardHelpers();
    if(!this.isConnected || generation!==this._generation) return;
    this._observer?.disconnect();
    const config={type:'energy-grid-balance'};
    if(this._config.collection_key) config.collection_key=this._config.collection_key;
    const source=helpers.createCardElement(config);
    this._source=source;
    // A date change can produce identical native text (0 → 0), so DOM
    // mutations alone cannot reliably detect it. Recheck after Lit updates.
    const updated=source.updated;
    source.updated=(changed)=>{ updated?.call(source,changed); this._sync(); };
    source.hass=this._hass;
    source.addEventListener('ll-rebuild',()=>this._mountSource(),{once:true});
    const container=this.shadowRoot.querySelector('.native');
    container.replaceChildren(source);
    await source.updateComplete;
    if(generation!==this._generation || !this.isConnected) return;
    if(source.shadowRoot) {
      this._observer=new MutationObserver(()=>this._sync());
      this._observer.observe(source.shadowRoot,{subtree:true,childList:true,characterData:true,attributes:true});
    }
    this._sync();
  }
  async _refreshAverage() {
    if(!this._hass || !this._config?.export_statistic || this._averageBusy) return;
    const zone=this._hass.config.time_zone;
    const formatter=new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'});
    const dayKey=date=>{
      const parts=Object.fromEntries(formatter.formatToParts(date).map(p=>[p.type,p.value]));
      return `${parts.year}-${parts.month}-${parts.day}`;
    };
    const today=dayKey(new Date());
    if(this._averageDay===today && Date.now()-(this._averageFetchAt||0)<1800000) return;
    this._averageDay=today;
    this._averageFetchAt=Date.now();
    this._averageBusy=true;
    const calendarMidnight=Date.parse(today+'T00:00:00Z');
    const keys=Array.from({length:7},(_,i)=>new Date(calendarMidnight-(i+1)*86400000).toISOString().slice(0,10));
    const target=this.shadowRoot.querySelector('.average-value');
    try {
      const result=await this._hass.callWS({type:'recorder/statistics_during_period',
        start_time:new Date(calendarMidnight-9*86400000).toISOString(),
        end_time:new Date(calendarMidnight+86400000).toISOString(),
        statistic_ids:[this._config.export_statistic],period:'day',types:['change']});
      const values=new Map();
      for(const row of result[this._config.export_statistic]||[]) {
        const key=dayKey(new Date(row.start));
        if(keys.includes(key) && Number.isFinite(row.change) && row.change>=0) values.set(key,row.change);
      }
      if(values.size!==7) {
        target.textContent='Incomplete data';
        target.title='Seven completed calendar days of export readings are required.';
      } else {
        const average=[...values.values()].reduce((a,b)=>a+b,0)/7;
        target.textContent=new Intl.NumberFormat(this._hass.locale?.language||'en',{maximumFractionDigits:1}).format(average)+' kWh/day';
        target.title=keys[6]+' to '+keys[0]+' · completed days · grid export, not total PV generation';
      }
    } catch {
      target.textContent='Unavailable';
      target.title='Could not read the last seven completed days from Home Assistant.';
    } finally { this._averageBusy=false; }
  }
  _sync() {
    const root=this._source?.shadowRoot;
    const incoming=root?.querySelector('#eq-imported');
    const outgoing=root?.querySelector('#eq-exported');
    const net=root?.querySelector('#eq-net');
    const container=this.shadowRoot.querySelector('.native');
    const surface=this.shadowRoot.querySelector('.surface');
    const ready=Boolean(incoming && outgoing && net);
    surface.hidden=!ready;
    container.classList.toggle('ready',ready);
    container.setAttribute('aria-hidden',String(ready));
    if(!ready) return;
    const data=this._source?._data;
    const state=this._hass?.states?.[this._config?.provisional_entity];
    const model=solarBalanceModel(data,state,this._config,new Date(),this._hass?.config?.time_zone||'Asia/Nicosia');
    if(model.mode==='provisional') {
      this._renderValues(model.imported,model.exported,
        'Today · provisional',model.explanation);
      return;
    }
    if(model.mode==='empty') {
      const hero=this.shadowRoot.querySelector('.hero');
      hero.className='hero balanced';
      this.shadowRoot.querySelector('.period').textContent='Selected period';
      this.shadowRoot.querySelector('.amount').textContent='—';
      this.shadowRoot.querySelector('.direction span').textContent='No data yet';
      this.shadowRoot.querySelector('.direction ha-icon').setAttribute('icon','mdi:clock-outline');
      this.shadowRoot.querySelector('.explanation').textContent=model.explanation;
      this.shadowRoot.querySelector('.imported').textContent='—';
      this.shadowRoot.querySelector('.exported').textContent='—';
      return;
    }
    this.shadowRoot.querySelector('.period').textContent='Selected period';
    const text=element=>element.textContent.trim().replace(/\s+/g,' ');
    const total=text(net);
    const exported=net.classList.contains('return');
    const zero=!/[1-9]/.test(total);
    const hero=this.shadowRoot.querySelector('.hero');
    hero.className='hero '+(zero?'balanced':exported?'export':'import');
    this.shadowRoot.querySelector('.amount').textContent=total.replace(/^[\s\u200e\u200f\u061c\u2212-]+/,'');
    this.shadowRoot.querySelector('.direction span').textContent=zero?'No net difference':exported?'Net exported':'Net imported';
    this.shadowRoot.querySelector('.direction ha-icon').setAttribute('icon',zero?'mdi:scale-balance':exported?'mdi:arrow-top-right':'mdi:arrow-bottom-left');
    this.shadowRoot.querySelector('.explanation').textContent=zero?'Imports and exports match in the available readings.':exported?'You sent more electricity to the grid than you bought from it.':'You bought more electricity from the grid than you sent back.';
    this.shadowRoot.querySelector('.imported').textContent=text(incoming);
    this.shadowRoot.querySelector('.exported').textContent=text(outgoing);
  }
  _renderValues(imported,exported,period,explanation) {
    const net=imported-exported;
    const zero=Math.abs(net)<0.000001;
    const exporting=net<0;
    const format=v=>new Intl.NumberFormat(this._hass?.locale?.language||'en',{maximumFractionDigits:2}).format(v)+' kWh';
    this.shadowRoot.querySelector('.period').textContent=period;
    this.shadowRoot.querySelector('.hero').className='hero '+(zero?'balanced':exporting?'export':'import');
    this.shadowRoot.querySelector('.amount').textContent=format(Math.abs(net));
    this.shadowRoot.querySelector('.direction span').textContent=zero?'No net difference':exporting?'Net exported':'Net imported';
    this.shadowRoot.querySelector('.direction ha-icon').setAttribute('icon',zero?'mdi:scale-balance':exporting?'mdi:arrow-top-right':'mdi:arrow-bottom-left');
    this.shadowRoot.querySelector('.explanation').textContent=explanation;
    this.shadowRoot.querySelector('.imported').textContent=format(imported);
    this.shadowRoot.querySelector('.exported').textContent=format(exported);
  }

}
if(!customElements.get('solar-balance-card')) customElements.define('solar-balance-card',SolarBalanceCard);
window.customCards=window.customCards||[];
window.customCards.push({type:'solar-balance-card',name:'Solar grid balance',description:'Clear selected-period import, export and net balance.'});
