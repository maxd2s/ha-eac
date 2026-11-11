const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const nodes=new Map();
const node=()=>({textContent:'',className:'',hidden:false,setAttribute(){},classList:{toggle(){}}});
class Element {attachShadow(){this.shadowRoot={innerHTML:'',querySelector:selector=>{if(!nodes.has(selector))nodes.set(selector,node());return nodes.get(selector)}}}}
const context=vm.createContext({Intl,Date,Number,HTMLElement:Element,customElements:{get(){return false},define(){}},window:{customCards:[]}});
vm.runInContext(fs.readFileSync('dashboard/solar-balance-card.js','utf8'),context);
const evaluate=(data,state,now='2026-11-11T14:00:00+02:00')=>context.solarBalanceModel(data,state,{},new Date(now),'Asia/Nicosia');
const today={start:new Date('2026-11-11T00:00:00+02:00'),end:new Date('2026-11-11T23:59:59+02:00')};
const live={state:'-5.25',attributes:{date:'2026-11-11',import_kwh:2.5,export_kwh:7.75,paired_intervals:27,data_through:'2026-11-11T13:30:00+02:00',gaps_before_latest:0}};
const historical={start:new Date('2026-11-10T00:00:00+02:00'),end:new Date('2026-11-10T23:59:59+02:00'),prefs:{energy_sources:[{type:'grid',stat_energy_from:'import',stat_energy_to:'export'}]},stats:{}};
test('today uses paired provisional values instead of native zero',()=>{const m=evaluate(today,live);assert.equal(m.mode,'provisional');assert.equal(m.imported,2.5);assert.match(m.explanation,/13:30/)});
test('missing, unavailable and yesterday are not zero today',()=>{for(const s of [undefined,{...live,state:'unavailable'},{...live,attributes:{...live.attributes,date:'2026-11-10'}}])assert.equal(evaluate(today,s).mode,'empty')});
test('valid measured zero is distinct from missing',()=>{const m=evaluate(today,{...live,state:'0',attributes:{...live.attributes,import_kwh:0,export_kwh:0}});assert.equal(m.mode,'provisional');assert.equal(m.imported,0)});
test('historical day with baseline only has no data',()=>{historical.stats={import:[{start:+historical.start-3600000,sum:50}],export:[{start:+historical.start-3600000,sum:20}]};assert.equal(evaluate(historical,live).mode,'empty')});
test('historical measured zero keeps native register calculations',()=>{historical.stats={import:[{start:+historical.start+3600000,sum:50,change:0}],export:[{start:+historical.start+3600000,sum:20,change:0}]};assert.equal(evaluate(historical,live).mode,'register')});
test('month never substitutes just todays provisional totals',()=>{assert.equal(evaluate({...today,start:new Date('2026-11-01T00:00:00+02:00'),end:new Date('2026-11-30T23:59:59+02:00')},live).mode,'empty')});
test('missing one direction and invalid data remain unknown',()=>{assert.equal(evaluate({...historical,stats:{import:[{start:+historical.start+3600000,sum:50}]}},live).mode,'empty');assert.equal(evaluate(today,{...live,attributes:{...live.attributes,export_kwh:NaN}}).mode,'empty')});
test('today with gaps is explicitly partial',()=>assert.match(evaluate(today,{...live,attributes:{...live.attributes,gaps_before_latest:1}}).explanation,/Missing intervals/));
test('renders provisional totals and then clears them when date has no data',()=>{
 const Card=vm.runInContext('SolarBalanceCard',context);const card=new Card();
 card._config={provisional_entity:'sensor.test'};card._hass={states:{'sensor.test':live},config:{time_zone:'Asia/Nicosia'}};
 const parts={'#eq-imported':{textContent:'0 kWh'},'#eq-exported':{textContent:'0 kWh'},'#eq-net':{textContent:'0 kWh',classList:{contains:()=>false}}};
 card._source={_data:today,shadowRoot:{querySelector:k=>parts[k]}};
 // Freeze the model clock without changing the browser's global Date.
 context.solarBalanceModel=(data,state,config)=>evaluateOriginal(data,state,config,new Date('2026-11-11T14:00:00+02:00'),'Asia/Nicosia');
 card._sync();assert.equal(nodes.get('.amount').textContent,'5.25 kWh');assert.equal(nodes.get('.period').textContent,'Today · provisional');
 card._source._data={...historical,stats:{}};card._sync();assert.equal(nodes.get('.amount').textContent,'—');assert.equal(nodes.get('.direction span').textContent,'No data yet');
});
const evaluateOriginal=context.solarBalanceModel;
