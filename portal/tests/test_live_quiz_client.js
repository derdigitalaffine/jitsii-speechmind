'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/static/live-join.js'), 'utf8');
async function exercise(kind, mine, click, expected) {
  const listeners = {}, sent = [];
  const q = {id: 1, kind, title:'Question', options:[{id:'o1',label:'A'},{id:'o2',label:'B'},{id:'o3',label:'C'}],settings:{max_choices:20,nickname:kind==='quiz',top_n:2},mine,answered:true,locked:false};
  const state = {status:'open',questions:[q]};
  const box = {innerHTML:'',addEventListener:(type,fn)=>listeners[type]=fn,querySelector:()=>null,querySelectorAll:()=>[]};
  const root = {dataset:{token:'token',device:'device'}};
  const fetch = async (url,opts) => { if(opts && opts.method==='POST') { sent.push(JSON.parse(opts.body)); return {json:async()=>({...state,ok:true})}; } return {json:async()=>state}; };
  const document = {activeElement:null,getElementById:id=>id==='live-join'?root:box};
  const LiveChart={esc:x=>String(x).replaceAll('&','&amp;').replaceAll('"','&quot;')};
  vm.runInNewContext(source,{window:{fetch,LiveChart},LiveChart,document,fetch,setInterval:()=>{},clearTimeout:()=>{},setTimeout:()=>{}});
  const flush = async()=>{for(let i=0;i<6;i++) await Promise.resolve();};
  await flush();
  if(kind==='quiz') assert.ok(box.innerHTML.includes('value="Ada"'), 'own name is prefilled after reload');
  function press(cls,oid) { const button={dataset:{q:'1',o:oid},classList:{contains:x=>x===cls}}; listeners.click({target:{closest:()=>button}}); }
  for(const [cls,oid] of click) { press(cls,oid); await flush(); }
  assert.deepEqual(sent[0].value, expected);
  if(kind==='quiz') assert.equal(sent[0].nickname,'Ada');
}
(async()=>{
  await exercise('quiz',{o:['o1','o3'],nickname:'Ada'},[['js-toggle','o2'],['js-send-multi']],{o:['o1','o3','o2']});
  await exercise('multi',{o:['o1','o3']},[['js-toggle','o1'],['js-send-multi']],{o:['o3']});
  await exercise('rank',{r:['o3','o1']},[['js-rank-up','o1'],['js-send-rank']],{r:['o1','o3']});
  console.log('Live quiz/rank client: reload selections, own nickname and keyboard/button ranking passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
