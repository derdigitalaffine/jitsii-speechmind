const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('portal/app/static/circulations.js','utf8');
function node(extra={}){return Object.assign({listeners:{},children:[],addEventListener(type,fn){(this.listeners[type] ||= []).push(fn);},querySelector(){return null;},querySelectorAll(){return [];},append(child){this.children.push(child);},prepend(child){this.children.unshift(child);},setAttribute(){},focus(){this.focused=true;},checkValidity(){return true;},reportValidity(){},dataset:{}},extra);}
function setup(){
  const form=node({action:'https://portal.example.org/umlaeufe/1/save'}),publish=node(),bundle=node(),window=node(),nodes={'#cl-editor':form,'#cl-editor-data':{textContent:'{"items":[]}'}};
  const document=node({querySelector(selector){return nodes[selector] || form.children.find(n=>'#'+n.id===selector) || null;},querySelectorAll(selector){return selector==='[data-cl-saved-action]'?[publish,bundle]:[];},createElement(){return node();}});
  const responses=[];let navigated='';window.location={assign(url){navigated=url;}};
  vm.runInNewContext(source,{window,document,FormData:class{},fetch:async()=>{const response=responses.shift();if(response instanceof Error)throw response;return response;},Set,Map,JSON,Array,String,Number,Event:class{},URL,AbortController,setTimeout,clearTimeout});
  async function fire(target,type,event={}){event.target ||= target;event.preventDefault ||= function(){this.defaultPrevented=true;};for(const fn of target.listeners[type] || [])await fn(event);return event;}
  return {form,publish,bundle,window,responses,fire,nodes,get navigated(){return navigated;}};
}
(async()=>{
  const app=setup();
  await app.fire(app.form,'input',{target:{name:'',type:'search'}});
  assert.equal((await app.fire(app.window,'beforeunload')).defaultPrevented,undefined,'Searching must not mark the draft dirty.');
  await app.fire(app.form,'input',{target:{name:'body',type:'textarea'}});
  assert.equal((await app.fire(app.window,'beforeunload')).defaultPrevented,true,'Actual unsaved content stays protected.');
  assert.equal((await app.fire(app.publish,'submit')).defaultPrevented,true,'Publish must wait for unsaved edits.');
  assert.match(app.form.children.find(n=>n.id==='cl-save-error').textContent,/zuerst den Entwurf speichern/);
  app.responses.push({ok:true,redirected:true,url:'https://portal.example.org/umlaeufe/1/edit'});
  await app.fire(app.form,'submit');
  assert.equal(app.navigated,'https://portal.example.org/umlaeufe/1/edit');
  assert.equal((await app.fire(app.window,'beforeunload')).defaultPrevented,undefined,'Successful save redirect must not warn.');
  assert.equal((await app.fire(app.publish,'submit')).defaultPrevented,undefined,'Saved draft can be published.');
  assert.equal((await app.fire(app.bundle,'submit')).defaultPrevented,undefined,'Saved draft can be copied to a bundle.');
  const failed=setup();await failed.fire(failed.form,'change',{target:{name:'title',type:'text'}});
  failed.responses.push({ok:false,redirected:false,json:async()=>({detail:'Bitte erneut versuchen.'})});await failed.fire(failed.form,'submit');
  assert.equal(failed.navigated,'');assert.equal((await failed.fire(failed.window,'beforeunload')).defaultPrevented,true,'Failed saves keep unsaved edits protected.');
  const expired=setup();await expired.fire(expired.form,'input',{target:{name:'body',type:'textarea'}});expired.responses.push({ok:true,redirected:true,url:'https://portal.example.org/login'});await expired.fire(expired.form,'submit');
  assert.equal(expired.navigated,'');assert.equal((await expired.fire(expired.window,'beforeunload')).defaultPrevented,true,'A login redirect must not count as a saved draft.');
  const offline=setup();await offline.fire(offline.form,'input',{target:{name:'body',type:'textarea'}});offline.responses.push(new Error('Offline'));await offline.fire(offline.form,'submit');
  assert.equal((await offline.fire(offline.window,'beforeunload')).defaultPrevented,true);
  console.log('Circulation submit lifecycle tests passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
