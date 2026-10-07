const assert = require('node:assert/strict');
const {reconcileDocuments} = require('../app/static/circulation-editor-state.js');
const law = {key:'law',kind:'law',id:4,title:'Dienstanweisung'};
const pdf = {key:'pdf',kind:'file',title:'Einstieg.pdf'};
const existing = {ref:'item:old',item:{...law,key:'old'},existing:true};
const empty = {objects:[],bundles:[],uploads:[],markdown:null};
const bundles = [{id:'1',bundle:{title:'Onboarding',items:[law,pdf]}},{id:'2',bundle:{title:'Weitere Unterlagen',items:[{...law,key:'law-two'},{...pdf,key:'pdf-two'}]}}];
let entries = reconcileDocuments([existing],{...empty,bundles});
assert.deepEqual(entries.map(e=>e.ref),['item:old','bundle:1:pdf','bundle:2:pdf-two']);
assert.equal(entries[1].item.bundle_title,'Onboarding');
// Manually reordered selections stay ordered while new choices append.
entries = reconcileDocuments(entries.reverse(),{...empty,bundles,uploads:[{name:'Neu.md',type:'text/markdown',size:25}],markdown:{title:'Checkliste'}});
assert.deepEqual(entries.map(e=>e.ref),['bundle:2:pdf-two','bundle:1:pdf','item:old','upload:0','markdown:new']);
// Removing a collection removes its pending documents, without removing existing copies.
entries = reconcileDocuments(entries,{...empty,bundles:bundles.slice(1)});
assert.deepEqual(entries.map(e=>e.ref),['bundle:2:pdf-two','item:old']);
// Direct portal selection takes priority over a matching bundled reference.
const selected = {ref:'law:4',item:law};
entries=reconcileDocuments([],{...empty,objects:[selected],bundles});
assert.deepEqual(entries.map(e=>e.ref),['law:4','bundle:1:pdf','bundle:2:pdf-two']);
// Inputs are not mutated and unsafe titles stay data, never HTML.
const title='<img src=x onerror=alert(1)>';
const selection={...empty,bundles:[{id:'3',bundle:{title,items:[pdf]}}]};
assert.equal(reconcileDocuments([],selection)[0].item.bundle_title,title);
assert.deepEqual(pdf,{key:'pdf',kind:'file',title:'Einstieg.pdf'});
console.log('Circulation editor selection tests passed.');
