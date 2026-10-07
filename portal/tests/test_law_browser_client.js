const assert=require('node:assert/strict'), vm=require('node:vm'), fs=require('node:fs');
class Node {
  constructor(tag, cls='', text='') {this.tagName=tag.toUpperCase();this.classes=new Set(cls.split(' '));this.ownText=text;this.children=[];this.dataset={};this.events={};this.hidden=false;this.open=false;this.value='';this.classList={contains:c=>this.classes.has(c),remove:c=>this.classes.delete(c),add:c=>this.classes.add(c),toggle:(c,on)=>on?this.classes.add(c):this.classes.delete(c)};}
  get textContent(){return this.ownText+this.children.map(c=>c.textContent).join(' ');}
  set textContent(t){this.ownText=t;}
  append(...nodes){nodes.forEach(n=>{this.children.push(n);n.parentElement=this;});return this;}
  addEventListener(name,fn){(this.events[name] ||= []).push(fn);}
  dispatch(name){(this.events[name]||[]).forEach(fn=>fn({}));}
  focus(){}
  matches(s){return s[0]==='.'?this.classes.has(s.slice(1)):s[0]==='#'?this.id===s.slice(1):s==='[data-law-expand]'?this.dataset.lawExpand!==undefined:this.tagName===s.toUpperCase();}
  querySelectorAll(s){return this.children.flatMap(c=>(c.matches(s)?[c]:[]).concat(c.querySelectorAll(s)));}
  querySelector(s){return this.querySelectorAll(s)[0]||null;}
}
const browser=new Node('section'), tools=new Node('div','lex-browser-tools'), input=new Node('input'), count=new Node('div'), clear=new Node('button'), expand=new Node('button'), collapse=new Node('button');
input.id='law-tree-filter';expand.dataset.lawExpand='1';collapse.dataset.lawExpand='0';tools.append(input,clear,expand,collapse,count);browser.append(tools);
const root=new Node('details','lex-branch');root.dataset.level='root';root.open=true;root.append(new Node('summary','','Verbandsgemeinde'));
function branch(name,id,open){const b=new Node('details','lex-branch');b.dataset.level=id;b.open=open;b.append(new Node('summary','',name));root.append(b);return b;}
const a=branch('Gemeinde A','a',false), b=branch('Gemeinde B','b',true), empty=branch('Leere Gemeinde','empty',false), grave=new Node('li','lex-doc','Friedhofssatzung'), main=new Node('li','lex-doc','Hauptsatzung'), other=new Node('li','lex-doc','Hundesteuersatzung');a.append(grave,main);b.append(other);browser.append(root);
const query=browser.querySelector.bind(browser);browser.querySelector=s=>s==='[data-law-count]'?count:s==='[data-law-filter-clear]'?clear:query(s);
const printEvents={}, saved={};const context={document:{querySelector:s=>s==='[data-law-browser]'?browser:null,querySelectorAll:()=>[],getElementById:()=>null},window:{addEventListener:(name,fn)=>{printEvents[name]=fn;}},location:{pathname:'/recht',hash:''},sessionStorage:{getItem:()=>null,setItem:(key,val)=>{saved[key]=JSON.parse(val);}},localStorage:{getItem:()=>null}};
vm.runInNewContext(fs.readFileSync('portal/app/static/laws.js','utf8'),context);
assert.equal(tools.hidden,false);
input.value='Friedhof';input.dispatch('input');assert.equal(grave.hidden,false);assert.equal(main.hidden,true);assert.equal(other.hidden,true);assert.equal(a.open,true);assert.equal(root.hidden,false);assert.equal(b.hidden,true);assert.equal(expand.disabled,true);
clear.dispatch('click');assert.equal(a.open,false);assert.equal(b.open,true);assert.equal(main.hidden,false);assert.equal(expand.disabled,false);
input.value='Gemeinde A';input.dispatch('input');assert.equal(main.hidden,false);assert.equal(grave.hidden,false);assert.equal(other.hidden,true);
input.value='Leere Gemeinde';input.dispatch('input');assert.equal(empty.hidden,false);assert.equal(root.hidden,false,'keep parent of a matching empty editor level');
clear.dispatch('click');collapse.dispatch('click');assert.equal(a.open,false);assert.equal(root.open,false);assert.equal(saved['law-tree:/'+'recht'].b,false);
expand.dispatch('click');assert.equal(a.open,true);assert.equal(b.open,true);assert.equal(empty.open,true);
collapse.dispatch('click');printEvents.beforeprint();assert.equal(a.open,true);printEvents.afterprint();assert.equal(a.open,false);
console.log('Hierarchy filtering, expansion restoration, group matches and print restoration passed.');
