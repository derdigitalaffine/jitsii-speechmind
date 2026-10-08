'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../app/static/seminars.js'),'utf8');
function node(extra={}){return Object.assign({listeners:{},children:[],dataset:{},addEventListener(k,f){(this.listeners[k] ||= []).push(f);},prepend(n){this.children.unshift(n);},setAttribute(){},focus(){this.focused=true;}},extra);}
function setup(){
  class Form{constructor(){Object.assign(this,node(),{action:'/seminare/1/edit',revision:{value:0},requests:0});}querySelector(){return this.revision;}reportValidity(){return true;}requestSubmit(){++this.requests;}}
  const form=new Form(),other=new Form(),window=node(),document=node(),responses=[];let navigation='',calls=0;
  document.querySelector=s=>s==='#sem-settings'?form:s==='#sem-save-message'?form.children.find(n=>n.id==='sem-save-message'):null;
  document.querySelectorAll=()=>[];document.createElement=()=>node();
  vm.runInNewContext(source,{document,window,HTMLFormElement:Form,FormData:class{set(){}},location:{assign(u){navigation=u;}},fetch:async()=>{++calls;let r=responses.shift();return typeof r==='function'?r():r;}});
  async function fire(target,k,e={}){e.target ||= target;e.preventDefault ||= function(){this.defaultPrevented=true;};for(const fn of target.listeners[k] || [])await fn(e);return e;}
  return {form,other,document,window,responses,fire,get navigation(){return navigation;},get calls(){return calls;}};
}
(async()=>{
  const a=setup();await a.fire(a.form,'input');a.responses.push({ok:true,json:async()=>({revision:1,redirect:''})});await a.fire(a.document,'submit',{target:a.form,submitter:{value:'save'}});
  assert.equal(a.form.revision.value,1);assert.equal(a.navigation,'');assert.equal((await a.fire(a.window,'beforeunload')).defaultPrevented,undefined,'Successful in-place save must clear the leave warning.');
  await a.fire(a.form,'change');a.responses.push({ok:true,json:async()=>({revision:2,redirect:''})});await a.fire(a.document,'submit',{target:a.other});assert.equal(a.other.requests,1,'Settings must save before another form navigates.');
  const b=setup();await b.fire(b.form,'input');b.responses.push({ok:false,json:async()=>({detail:'Kapazität ungültig'})});await b.fire(b.document,'submit',{target:b.other});assert.equal(b.other.requests,0);assert.match(b.form.children[0].textContent,/Kapazität/);assert.equal((await b.fire(b.window,'beforeunload')).defaultPrevented,true,'Failed save keeps edits protected.');
  const c=setup();await c.fire(c.form,'input');await c.fire(c.document,'submit',{target:c.other,defaultPrevented:true});assert.equal(c.calls,0,'Cancelled confirmation must not autosave or submit.');
  const d=setup();await d.fire(d.form,'input');d.responses.push(async()=>{await d.fire(d.form,'input');return {ok:true,json:async()=>({revision:1,redirect:'/seminare/1'})};});await d.fire(d.document,'submit',{target:d.form,submitter:{value:'publish'}});assert.equal(d.navigation,'','New edits during an in-flight save must not disappear on redirect.');assert.equal((await d.fire(d.window,'beforeunload')).defaultPrevented,true);
  console.log('Seminar save, autosave, cancelled confirmation and concurrent input lifecycle passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
