'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../app/static/seminar_planner.js'),'utf8');
function node(extra={}){return Object.assign({value:'',checked:false,disabled:false,hidden:false,dataset:{},listeners:{},children:[],textContent:'',addEventListener(k,fn){(this.listeners[k]||=[]).push(fn);},append(...ns){this.children.push(...ns);},replaceChildren(...ns){this.children=ns;},setAttribute(){},removeAttribute(){},scrollIntoView(){},focus(){},querySelector(){return null;},querySelectorAll(){return [];},setCustomValidity(){},reportValidity(){return true;},checkValidity(){return true;}},extra);}
function setup(channel){
 const nodes={},all=[],get=id=>nodes[id]||=(all.push(node({id})),all.at(-1));
 const root=get('seminar-planner');root.querySelectorAll=()=>all.filter(n=>n!==root);
 get('sp-data').textContent=JSON.stringify({initial:{title:'Reihe',channels:[channel],schedule:{first:'2027-01-01',kind:'once',time:'09:00',duration:60}},people:[],groups:[],resources:[],csrf:'csrf'});
 for(const [id,value]of Object.entries({kind:'once',booking:'individual',channel:'internal',delivery:'onsite','video-mode':'new',time:'09:00',duration:'60',count:'6',nth:'1',weekday:'0','end-mode':'count'}))get('sp-'+id).value=value;
 const panels=[0,1,2,3].map(i=>node({dataset:{panel:String(i)}}));
 const document={getElementById:get,createElement:()=>node(),createTextNode:t=>node({textContent:t}),querySelectorAll:s=>s==='[data-panel]'?panels:[],querySelector:s=>panels.find(n=>s.includes(n.dataset.panel))};
 const window=node();let sent,complete,navigation='';window.location={pathname:'/seminare/planen',assign:p=>navigation=p};window.confirm=()=>true;
 vm.runInNewContext(source,{document,window,structuredClone,Date,fetch:async(url,options)=>{sent=JSON.parse(options.body);await new Promise(resolve=>complete=resolve);return {ok:true,json:async()=>({redirect:'/seminare/1/planen'})};}});
 async function fire(target,event){const e={preventDefault(){this.defaultPrevented=true;}};for(const fn of target.listeners[event]||[])await fn(e);return e;}
 return {get,window,fire,get sent(){return sent;},finish(){complete();},get navigation(){return navigation;}};
}
(async()=>{
 for(const [channel,expected]of [['internal',['internal']],['guest',['internal','guest']],['public',['internal','guest','public']]]){
   const app=setup(channel);await app.fire(app.get('sp-form'),'input');const pending=app.fire(app.get('sp-save-draft'),'click');
   assert.deepEqual(app.sent.channels,expected,'Browser must send the backend channel list contract.');
   assert.equal(app.get('sp-title').disabled,true,'Inputs remain protected during save.');
   assert.equal((await app.fire(app.window,'beforeunload')).defaultPrevented,true,'In-flight save must not silently discard unsaved input.');
   app.finish();await pending;assert.equal(app.navigation,'/seminare/1/planen');assert.equal((await app.fire(app.window,'beforeunload')).defaultPrevented,undefined,'Successful save clears the leave warning.');
 }
 console.log('Seminar planner channel contracts and safe save lifecycle passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
