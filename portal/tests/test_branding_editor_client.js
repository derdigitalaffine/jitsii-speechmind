/* Execute real editor code: stale response guard, escaped iframe and acknowledgement. */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element {
  constructor(value=''){this.value=value;this.dataset={};this.checked=false;this.listeners={};this.children=[];this.classList={add(){}};}
  addEventListener(name,fn){(this.listeners[name] ||= []).push(fn);}
  dispatchEvent(e){e.target ||= this;(this.listeners[e.type]||[]).forEach(fn=>fn(e));}
  replaceChildren(){this.children=[];}
  appendChild(n){this.children.push(n);}
  setAttribute(k,v){this[k]=v;}
  focus(){this.focused=true;}
}
(async()=>{
 const ids={},form=ids['design-form']=new Element();form.elements={};
 const fields={ui_primary:'#ffffff',ui_navbar:'primary',ui_brand_name:'<img onerror="alert(1)">',ui_product:'Safe',ui_radius:'0.375rem',ui_logo_height:'32',ui_custom:'1',ui_show_name:'1',contrast_key:''};
 for(const [k,v] of Object.entries(fields))form.elements[k]=new Element(v);
 form.elements.ui_custom.checked=true;form.elements.ui_show_name.checked=true;
 for(const id of ['design-preview','contrast-values','contrast-ack','contrast-summary','contrast-suggest','contrast-confirm','design-autoenabled'])ids[id]=new Element();
 ids['design-preview'].dataset={brand:'Default',product:'Portal'};
 const toggles=['light','dark'].map(theme=>{let e=new Element();e.dataset.previewTheme=theme;return e;});
 let timer,pending=[];
 const doc={getElementById:id=>ids[id],createElement:()=>new Element(),addEventListener(){},querySelectorAll:()=>toggles};
 vm.runInNewContext(fs.readFileSync('portal/app/static/branding-editor.js','utf8'),{document:doc,URLSearchParams,Number,String,Event:class {constructor(type){this.type=type;}},setTimeout:f=>(timer=f,1),clearTimeout(){},fetch:()=>new Promise(resolve=>pending.push(resolve))});
 timer();
 const response={css:':root{}',report:{rows:[{theme:'light',label:'Link',ratio:1,rating:'zu geringer Kontrast',ok:false}],warnings:[{}],suggestion:'#1f5fa8'}};
 pending[0]({ok:true,json:()=>Promise.resolve(response)});await new Promise(resolve=>setImmediate(resolve));
 assert(ids['design-preview'].srcdoc.includes('&lt;img onerror=&quot;alert(1)&quot;&gt;'));
 assert(!ids['design-preview'].srcdoc.includes('<img onerror='));
 assert.equal(ids['contrast-values'].children.length,1);
 assert.equal(ids['contrast-confirm'].hidden,false);
 let prevented=false;form.dispatchEvent({type:'submit',preventDefault(){prevented=true;}});
 assert(prevented);assert(ids['contrast-ack'].focused);
 ids['contrast-ack'].checked=true;
 form.elements.ui_primary.value='#222222';form.dispatchEvent({type:'input',target:{name:'ui_primary'}});
 assert.equal(ids['contrast-ack'].checked,false);
 assert.equal(form.elements.contrast_key.value,'#222222|primary');
 timer();
 form.elements.ui_primary.value='#333333';form.dispatchEvent({type:'input',target:{name:'ui_primary'}});timer();
 pending[2]({ok:true,json:()=>Promise.resolve({...response,css:'/*new*/'})});await new Promise(resolve=>setImmediate(resolve));
 pending[1]({ok:true,json:()=>Promise.resolve({...response,css:'/*stale*/'})});await new Promise(resolve=>setImmediate(resolve));
 assert(ids['design-preview'].srcdoc.includes('/*new*/'));assert(!ids['design-preview'].srcdoc.includes('/*stale*/'));
 toggles[1].dispatchEvent({type:'click'});assert(ids['design-preview'].srcdoc.includes('data-bs-theme="dark"'));
 console.log('Branding editor client checks passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
