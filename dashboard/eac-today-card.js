/* Local, dependency-free display of paired EAC half-hour energy estimates. */
class EacTodayCard extends HTMLElement {
  constructor() { super(); this.attachShadow({mode: 'open'}); }
  setConfig(config) {
    if (!config.entity) throw new Error('Specify the Today net provisional entity');
    this.config = config;
  }
  getCardSize() { return 6; }
  set hass(hass) {
    if (!this.config) return;
    const state = hass.states[this.config.entity];
    const day = new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Nicosia', year:'numeric', month:'2-digit', day:'2-digit'}).format(new Date());
    if (this.previous === state && this.previousDay === day) return;
    this.previous = state; this.previousDay = day;
    const a = state?.attributes || {};
    const active = state && !['unknown','unavailable'].includes(state.state) && a.date === day;
    const points = active && Array.isArray(a.points) ? a.points.filter(p => Array.isArray(p) && p.length === 3 && Number.isFinite(Date.parse(p[0])) && Number.isFinite(p[1]) && p[1] >= 0 && Number.isFinite(p[2]) && p[2] >= 0).slice(0,50) : [];
    const valid = active && points.length && Number.isFinite(a.import_kwh) && Number.isFinite(a.export_kwh);
    const format = n => Number(n).toLocaleString(undefined, {maximumFractionDigits:2, minimumFractionDigits:2});
    const clock = t => new Date(t).toLocaleTimeString(undefined,{timeZone:'Asia/Nicosia', hour:'2-digit',minute:'2-digit',hour12:false});
    const net = valid ? a.import_kwh - a.export_kwh : 0;
    const count = Number.isFinite(a.paired_intervals) ? a.paired_intervals : 0;
    const expected = Number.isFinite(a.expected_intervals) ? a.expected_intervals : 0;
    const gaps = Number.isFinite(a.gaps_before_latest) ? a.gaps_before_latest : 0;
    let chart = '';
    if (valid) {
      const start = Date.parse(a.day_start);
      const duration = Number.isFinite(a.day_hours) ? a.day_hours : 24;
      let imp=0, exp=0;
      const rows = points.map(p => ({t:Date.parse(p[0]), imp:imp+=p[1], exp:exp+=p[2]}));
      const max = Math.max(1,...rows.map(r=>Math.max(r.imp,r.exp)));
      const top = Math.ceil(max / 4) * 4;
      const x = t => 42 + (t-start)/3600000/duration*476;
      const y = v => 184-v/top*158;
      const path = key => {
        let prev = start;
        return rows.map((r,i)=>{
          const gap=r.t-prev>1800000;
          const command=i===0||gap?'M':'L';
          const prefix=i===0&&!gap?`M${x(start)},${y(0)} L`:command;
          prev=r.t;return `${prefix}${x(r.t)},${y(r[key])}`;
        }).join(' ');
      };
      const ticks=[0,1,2,3,4].map(i=>{
        const value=top*i/4;
        return `<line x1="42" x2="518" y1="${y(value)}" y2="${y(value)}" class="grid"/><text x="34" y="${y(value)+4}" text-anchor="end">${value}</text>`;
      }).join('');
      const hours=[0,6,12,18,24].filter(h=>h<=duration).map(h=>`<text x="${42+h/duration*476}" y="207" text-anchor="middle">${clock(start+h*3600000)}</text>`).join('');
      const dots=rows.map(r=>`<circle cx="${x(r.t)}" cy="${y(r.imp)}" r="2.5" fill="#42a5f5"><title>${clock(r.t)} · import ${format(r.imp)} kWh</title></circle><circle cx="${x(r.t)}" cy="${y(r.exp)}" r="2.5" fill="#f9b938"><title>${clock(r.t)} · export ${format(r.exp)} kWh</title></circle>`).join('');
      chart=`<svg viewBox="0 0 540 222" role="img" aria-label="Cumulative grid import and export for available half-hour intervals today"><text x="42" y="14">kWh accumulated</text>${ticks}${hours}<path d="${path('imp')}" stroke="#42a5f5"/><path d="${path('exp')}" stroke="#f9b938"/>${dots}</svg>`;
    }
    this.shadowRoot.innerHTML=`<style>
      :host{display:block}ha-card{padding:20px;overflow:hidden;color:var(--primary-text-color);font-family:var(--paper-font-body1_-_font-family,inherit)}
      header{display:flex;justify-content:space-between;align-items:center;gap:8px}h2{margin:0;font-size:20px;font-weight:600}.badge{font-size:11px;letter-spacing:.04em;padding:5px 8px;border-radius:20px;background:rgba(249,185,56,.15);color:var(--primary-text-color)}
      .sub,.note{color:var(--secondary-text-color);font-size:12px;line-height:1.55}.sub{margin:7px 0 16px}.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.kpi{padding:12px 8px;border-radius:12px;background:var(--secondary-background-color,rgba(127,127,127,.1))}.label{font-size:12px}.value{font-size:clamp(20px,5vw,29px);font-weight:650;margin:5px 0}.unit{font-size:11px;color:var(--secondary-text-color)}.import{color:#42a5f5}.export{color:#f9b938}.net{color:#b39ddb}
      svg{width:100%;margin-top:15px;overflow:visible}svg text{fill:var(--secondary-text-color);font-size:11px}svg path{fill:none;stroke-width:2.8;stroke-linejoin:round}svg .grid{stroke:var(--divider-color,#777);stroke-opacity:.4;stroke-dasharray:3 4}.empty{padding:30px 6px;text-align:center;color:var(--secondary-text-color)}.legend{font-size:12px;display:flex;gap:18px;margin:4px 0 12px}.note{border-top:1px solid var(--divider-color);padding-top:12px}.warn{color:var(--warning-color,#f9b938)}
    </style><ha-card><header><h2>Today so far</h2><span class="badge">PROVISIONAL</span></header>
    <p class="sub">${valid?`Data through ${clock(a.data_through)} · Cyprus time · ${count}/${expected} elapsed half-hours received`:'Waiting for matching import and export readings for today'}</p>
    <div class="kpis"><div class="kpi"><div class="label import">Grid import</div><div class="value">${valid?format(a.import_kwh):'—'}</div><div class="unit">kWh bought</div></div><div class="kpi"><div class="label export">Grid export</div><div class="value">${valid?format(a.export_kwh):'—'}</div><div class="unit">kWh sent to grid</div></div><div class="kpi"><div class="label net">${valid&&net<0?'Net export':'Net import'}</div><div class="value">${valid?format(Math.abs(net)):'—'}</div><div class="unit">kWh balance</div></div></div>
    ${valid?chart:'<div class="empty">No total yet. Missing readings are not zero.</div>'}
    <div class="legend"><span class="import">● Import</span><span class="export">● Export</span></div>
    <div class="note">${gaps?`<span class="warn">${gaps} missing half-hour interval(s) before the latest reading. Totals cover received intervals only.</span><br>`:''}Delayed DSO data, refreshed every 30 minutes. Later readings may revise these estimates. Daily register totals remain separate. Export is surplus solar, not total generation.</div></ha-card>`;
  }
}
if (!customElements.get('eac-today-card')) customElements.define('eac-today-card',EacTodayCard);
window.customCards = window.customCards || [];
window.customCards.push({type:'eac-today-card', name:'EAC Today so far', description:'Provisional paired half-hour grid energy'});
