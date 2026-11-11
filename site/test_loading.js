"use strict";
// Dependency-free fetch/route integration fixture. Real browser layout is checked by site_smoke.py.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const path = require('node:path'), read = name => fs.readFileSync(path.join(__dirname, name), 'utf8');
const html = read('index.html'), ids = new Map(), requests = [];
const context = {console, Set, Map, URLSearchParams, URL, Blob, Int32Array, Uint32Array, Float32Array, Number, String, Math,
  setTimeout, clearTimeout, requestAnimationFrame: fn => setTimeout(fn,0), matchMedia: () => ({matches:false}),
  localStorage: {getItem:()=>null,setItem:()=>{}}, history: {}, location: {hash:'',protocol:'http:'},
  Option: function(text,value) {this.text=text;this.value=value}, addEventListener:()=>{}};
class Element {
  constructor(id) {this.id=id; this.value=''; this.checked=['alltime'].includes(id); this.dataset={}; this.style={}; this.classList={add(){}, remove(){}, toggle(){}}; this.firstElementChild={}; }
  set innerHTML(s) {this.html=s; for (const m of s.matchAll(/id="([^"]+)"/g)) if (!ids.has(m[1])) ids.set(m[1],new Element(m[1])); }
  get innerHTML() {return this.html||''}
  setAttribute(k,v) {this[k]=v}
  querySelectorAll() {return []}
  insertAdjacentHTML() {}
  addEventListener() {}
  add() {}
}
for (const m of html.matchAll(/id="([^"]+)"/g)) ids.set(m[1],new Element(m[1]));
ids.get('spacing').value='1'; ids.get('sort').value='n';
context.document={body:{dataset:{},insertAdjacentHTML(){}}, getElementById:id=>ids.get(id),querySelectorAll:()=>[],addEventListener:()=>{}};
context.window=context;
context.history.pushState=context.history.replaceState=(_,__,h)=>{context.location.hash=h};
const agency={id:'O1',name:'ALPHA CARE',kind:'hospice',state:'CA',status:'active',ef:[0],first_seen:'2024-01-01',group:1,ind:{},x:0,y:0};
const person={id:'I1@1',cms_id:'1',name:'PERSON ONE',kind:'person',n_here:1,n_enrollments:1,x:100,y:100};
const edge={from:person.id,to:agency.id,cat:'officer',roles:['OFFICER'],first:'2024-01-01',last:'2024-01-01',fs:[1]};
const files=[{ds:'Enrollments',rel:'2024-01-01',api:'https://data.cms.gov/enrollment'}, {ds:'Owners',rel:'2024-01-01',api:'https://data.cms.gov/owners'}];
const values={tables:{count:2,states:['CA','NY'],pairs:[],events:[]},'agencies-first':[agency],agencies:[agency,{...agency,id:'O2',state:'NY',name:'BETA CARE'}],index:{groups:[{id:1,states:['CA'],n:1,people:[]}],files,releases:['2024-01-01'],ext:{}},'g/1':{nodes:[agency,person],edges:[edge]},'r/1':[[{f:[1],aid:'1',role:'OFFICER'}]],search:{1:'ALPHA CARE PERSON ONE'}};
let recordResolve, recordFail=false, holdRecords=true, searchResolve, holdSearch=true;
values['path-names'] = {names:['ALPHA CARE','PERSON ONE'],sub:['CA','CMS ID 1'],kinds:'hp',search:['ALPHA CARE','PERSON ONE']};
values['path-edges'] = {edges:[0,1,1,0],cat:'f',weak:'1'};
context.fetch=async url=>{
  let name=url.replace(/^data\/__VERSION__\//,'').replace(/\.json$/,'');
  const shard=name.match(/^([gra])\/([0-9a-f]{2})$/);
  if(shard){   // a bucket file: answer with every fixture of that folder whose name hashes into it
    const stems=Object.keys(values).filter(k=>k.startsWith(shard[1]+'/')).map(k=>k.slice(2)).filter(st=>context.shardKey(st)===shard[2]);
    if(stems.length!==1) throw new Error('fixture bucket '+name);
    name=shard[1]+'/'+stems[0];
    requests.push(name);
    if(name==='r/1'&&holdRecords) await new Promise(r=>recordResolve=r);
    return {ok: !(name==='r/1'&&recordFail), json: async()=>({[stems[0]]:JSON.parse(JSON.stringify(values[name]))})};
  }
  requests.push(name);
  if(name==='r/1'&&holdRecords) await new Promise(r=>recordResolve=r);
  if(name==='search'&&holdSearch) await new Promise(r=>searchResolve=r);
  return {ok: !(name==='r/1'&&recordFail), json: async()=>JSON.parse(JSON.stringify(values[name]))};
};
context.GraphRenderer=class {
  constructor(){this.handlers=new Map()}
  setGraph(nodes,edges){this.nodes=nodes;this.edges=edges;this.nodeById=new Map(nodes.map(n=>[n.id,n]))}
  on(){} refresh(){} startLayout(){} stopLayout(){} _hideTip(){} fit(){} focus(){}
};
vm.createContext(context);
vm.runInContext(read('graph_logic.js'),context);
vm.runInContext(read('tables.js'),context);
vm.runInContext(read('case.js'),context);
vm.runInContext(html.split('<script>')[1].split('</script>')[0],context);
const delay=()=>new Promise(r=>setTimeout(r,20));
(async()=>{
  await delay(); assert.deepEqual(requests,['tables','agencies-first']);
  context.location.hash='#/agencies?state=CA&q=care'; await vm.runInContext('route()',context);
  assert.equal(vm.runInContext('tableFiltered.length',context),1);
  assert(requests.includes('agencies')); assert(!requests.includes('index'));
  context.location.hash='#1/I1%401'; const routing=vm.runInContext('route()',context); await delay();
  assert(ids.get('infobody').innerHTML.includes('Loading source records'));
  assert(vm.runInContext('!network.nodeById.get("I1@1").hidden',context));
  recordFail=true; recordResolve(); await routing; await delay();
  assert(ids.get('infobody').innerHTML.includes('recordretry'));
  recordFail=false; holdRecords=false; ids.get('recordretry').onclick(); await delay();
  assert(ids.get('infobody').innerHTML.includes('rows'));
  assert(ids.get('infobody').innerHTML.includes('https://data.cms.gov/owners'));
  // Selecting an agency uses the same hydrated row sources and builds the requested sections.
  vm.runInContext('select(network.nodeById.get("O1"))',context);
  for(const text of ['Summary','Timeline','Sources','Show all people on this agency']) assert(ids.get('infobody').innerHTML.includes(text),text);
  assert(ids.get('infobody').innerHTML.includes('data-export="O1"'));
  vm.runInContext('downloadFile=(t,ty,n)=>{globalThis.dl={t,n}}',context);   // the export is a pure text build plus one download
  ids.get('info').onclick({target:{closest:s=>s==='[data-export]'?{dataset:{export:'O1'}}:null}});
  assert.equal(context.dl.n,'caregraph-O1.md'); assert(context.dl.t.startsWith('# Alpha Care')); assert(context.dl.t.includes('## Connections (1)')); assert(context.dl.t.includes('Person One'));
  vm.runInContext('select(network.nodeById.get("I1@1"))',context);
  assert(ids.get('infobody').innerHTML.includes('data-export="I1@1"'));
  ids.get('q').value = 'PERSON'; vm.runInContext('renderList()',context);
  assert(ids.get('list').innerHTML.includes('Loading search'));
  holdSearch=false; searchResolve(); await delay();
  assert(ids.get('list').innerHTML.includes('data-id="1"'));
  ids.get('pathfrom').value='a'; await vm.runInContext('suggestPathNames("pathfrom")',context);
  await delay(); assert(requests.includes('path-names')); assert(!requests.includes('path-edges'));
  await ids.get('pathfind').onclick(); assert(requests.includes('path-edges'));
  context.location.hash='#/agencies'; await vm.runInContext('route()',context);
  assert.equal(context.document.body.dataset.section,'agencies');
  console.log('test_loading: passed (default requests, full filters, hidden deep links, record retry, deferred search/paths, sections, back)');
})().catch(e=>{console.error(e);process.exitCode=1});
