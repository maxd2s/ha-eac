const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
class Element{attachShadow(){this.shadowRoot={innerHTML:'',querySelector:()=>null,querySelectorAll:()=>[]};}}
const context=vm.createContext({HTMLElement:Element,Intl,Date,Number,Map,Promise,customElements:{get:()=>false,define(){}},window:{customCards:[]}});
vm.runInContext(fs.readFileSync('dashboard/eac-energy-dashboard.js','utf8'),context);
const get=name=>vm.runInContext(name,context);
const period=get('eacPeriod'), rows=get('eacRegisterRows'), totals=get('eacTotals'), provisional=get('eacProvisional'), average=get('eacExportAverage');
const Card=get('EacEnergyDashboard');
const zone='Asia/Nicosia';
const ids={import:'eac_cyprus:synthetic_import',export:'eac_cyprus:synthetic_export',net:'eac_cyprus:synthetic_net'};
test('calendar boundaries respect Cyprus DST and leap/month ends',()=>{
 assert.equal((period('day','2026-03-29',zone).end-period('day','2026-03-29',zone).start)/3600000,23);
 assert.equal((period('day','2026-10-25',zone).end-period('day','2026-10-25',zone).start)/3600000,25);
 assert.equal(period('month','2024-02',zone).next,'2024-03-01');
 assert.equal(period('month','2026-12',zone).next,'2027-01-01');
});
test('missing statistics stay unknown, actual zero stays zero, net uses matching series',()=>{
 const range=period('month','2026-04',zone);
 const result={[ids.import]:[{start:range.start,change:0},{start:range.start+86400000,change:9}],[ids.export]:[{start:range.start,change:2}]};
 const r=rows(result,ids,range,zone),t=totals(r);
 assert.equal(r[0].values[0],0);assert.equal(r[1].values[1],null);
 assert.equal(t.imported,9);assert.equal(t.exported,2);assert.equal(t.net,null);
 assert.equal(totals([]).imported,null);
});
test('today net excludes unpaired intervals and keeps import-only totals',()=>{
 const t=provisional([{values:[2,1,1]},{values:[8,null,null]}]);
 assert.equal(t.imported,10);assert.equal(t.exported,1);assert.equal(t.net,1);assert.equal(t.paired,1);
 assert.equal(provisional([{values:[8,null,null]}]).net,null);
});
test('export average requires all seven completed calendar days',()=>{
 const now=Date.parse('2026-04-20T12:00:00+03:00');
 const result={[ids.export]:Array.from({length:7},(_,i)=>({start:period('day',`2026-04-${13+i}`,zone).start,change:i}))};
 assert.equal(average(result,ids.export,zone,now),3);
 result[ids.export].pop();assert.equal(average(result,ids.export,zone,now),null);
});
test('account-provided text is escaped and empty totals are not false balance',()=>{
 const card=new Card();card._events=()=>{};card.setConfig({});card._meters=[{entity_id:'sensor.synthetic',name:'<script>attack</script>'}];
 card._data={time_zone:zone,points:[],window_days:30,tariff:{code:'<img onerror=x>'},available:true,surplus_by_half_hour:[]};card._render();
 assert(!card.shadowRoot.innerHTML.includes('<script>'));assert(!card.shadowRoot.innerHTML.includes('<img onerror'));
 assert(card.shadowRoot.innerHTML.includes('Waiting for readings'));assert(!card.shadowRoot.innerHTML.includes('Imports and exports match'));
});
test('late responses cannot replace a newly selected period',async()=>{
 const data={time_zone:zone,statistic_ids:ids};
 const second=new Card();second._data=data;second._mode='month';second._value='2026-04';second._request=1;
 let finish;const wait=new Promise(r=>{finish=r;});second._statistics=()=>wait;
 const load=second._loadStatistics(1);second._request=2;second._rows=[{key:'new-selection'}];finish({});await load;
 assert.equal(second._rows[0].key,'new-selection');
});
test('permission failure clears profile and previous totals',async()=>{
 const card=new Card();card._render=()=>{};card._data={tariff:{code:'PRIVATE'}};card._rows=[{values:[1,2,-1]}];card._hass={callWS:async()=>{throw Error('denied')}};
 await card._load();assert.equal(card._data,null);assert.equal(card._rows.length,0);assert.match(card._error,/access permissions/);
});
