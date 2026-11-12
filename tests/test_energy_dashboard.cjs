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
const selection=get('eacSelection');
test('yesterday uses available intervals while daily registers are pending, then prefers registers',()=>{
 const range=period('yesterday','',zone,Date.parse('2026-04-20T10:00:00+03:00'));
 const profile={time_zone:zone,points:Array.from({length:48},(_,i)=>[range.start+(i+1)*1800000,.2,.1])};
 const pending=selection(profile,range,[]);
 assert.equal(pending.fallback,true);assert.equal(pending.expected,48);assert.equal(pending.totals.paired,48);assert(Math.abs(pending.totals.imported-9.6)<1e-9);
 const final=selection(profile,range,[{t:range.start,values:[10,5,5]}]);
 assert.equal(final.provisional,false);assert.equal(final.totals.imported,10);
});
test('past-day fallback preserves gaps and never enters month or week totals',()=>{
 const range=period('day','2026-10-25',zone);
 const profile={time_zone:zone,points:[[range.start+1800000,1,0],[range.start+5400000,2,null]]};
 const partial=selection(profile,range,[]);
 assert.equal(partial.expected,50);assert.equal(partial.totals.paired,1);assert.equal(partial.totals.net,1);
 for(const multi of [period('month','2026-10',zone),period('week','',zone,range.end+86400000)]) {
  const r=selection(profile,multi,[]);assert.equal(r.provisional,false);assert.equal(r.totals.imported,null);
 }
 assert.equal(selection({points:[]},range,[]).totals.imported,null);
});
const averageSummary=get('eacAverageSummary');
function fullExportWeek(today){
 const now=Date.parse(today+'T12:00:00+03:00'),range=period('week','',zone,now),points=[];
 for(let t=range.start+1800000;t<=range.end;t+=1800000)points.push([t,null,.25]);
 return {now,range,profile:{time_zone:zone,points}};
}
test('average uses one consistent complete interval week when a daily register is pending',()=>{
 const {now,range,profile}=fullExportWeek('2026-04-20');
 const result={[ids.export]:Array.from({length:6},(_,i)=>({start:range.start+i*86400000,change:999}))};
 const r=averageSummary(result,ids.export,profile,now);assert.equal(r.value,12);assert.match(r.label,/provisional/);
 result[ids.export].push({start:range.start+6*86400000,change:999});
 assert.equal(averageSummary(result,ids.export,profile,now).value,999);
});
test('average requires every interval, accepts observed zeros, and ignores today',()=>{
 const {now,range,profile}=fullExportWeek('2026-04-20');
 profile.points.forEach(p=>p[2]=0);profile.points.push([range.end+1800000,null,999]);
 assert.equal(averageSummary({},ids.export,profile,now).value,0);
 profile.points.splice(2,1);profile.points.push([...profile.points[0]]);
 const r=averageSummary({},ids.export,profile,now);assert.equal(r.value,null);assert.match(r.label,/6\/7/);
});
test('average completeness follows spring and autumn DST day lengths',()=>{
 for(const [today,count] of [['2026-03-30',334],['2026-10-26',338]]){
  const {now,profile}=fullExportWeek(today);assert.equal(profile.points.length,count);
  assert.equal(averageSummary({},ids.export,profile,now).value,count*.25/7);
  profile.points.pop();assert.equal(averageSummary({},ids.export,profile,now).value,null);
 }
});
