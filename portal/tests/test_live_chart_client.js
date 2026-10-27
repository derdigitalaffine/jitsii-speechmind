'use strict';
// Render the actual cloud code: long/untrusted terms must fit and remain plain text.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../app/static/live-chart.js'),'utf8');
const context = {
  window:{},
  document:{documentElement:{},createElement:()=>({getContext:()=>({font:'',measureText(text){
    const pixels=Number(this.font.match(/([0-9.]+)px/)[1]);
    return {width:Array.from(text).length*pixels*.7};
  }})})},
  getComputedStyle:()=>({fontSize:'16px',fontFamily:'Arial',getPropertyValue:()=>''})
};
vm.runInNewContext(source,context);
const term='Zusammenhalt';
const q={kind:'words',chart:'cloud',results:{total:4,rows:[{label:term,count:3},{label:'<script>alert("x")</script>',count:1}]}};
for (const width of [280,960]) {
  const box={clientWidth:width,innerHTML:''};
  context.window.LiveChart.render(box,q,{});
  assert.ok(!box.innerHTML.includes('<script>'));
  assert.ok(box.innerHTML.includes('&lt;script&gt;'));
  assert.ok(box.innerHTML.includes('(3)'));
  const longTag=box.innerHTML.match(/<span role="listitem" style="font-size:([0-9.]+)rem[^>]+title="Zusammenhalt/);
  assert.ok(longTag,'long term stays present');
  assert.ok(Number(longTag[1])*16*Array.from(term).length*.7 <= width,'long term fits its container');
}
const empty={clientWidth:280,innerHTML:''};
context.window.LiveChart.render(empty,{...q,results:{total:0,rows:[]}},{});
assert.ok(empty.innerHTML.includes('Noch keine Begriffe'));
console.log('Cloud rendering passed: responsive long terms, escaping, counts and empty state.');

// The initial moderator state comes from a JSON script node. Even numeric-looking
// properties must not become HTML when that state is malformed or manipulated.
const attack='<img src=x onerror=alert(1)>';
for (const kind of ['qa','quiz','rank','words']) {
  const target={clientWidth:280,innerHTML:''};
  const question={kind,chart:kind==='words'?'table':'table',options:[{id:'a',label:attack}],solution:['a'],
    score:attack,settings:{points:attack},scoreboard:[{name:attack,points:attack}],
    entries:[{text:attack,upvotes:attack,approved:true,hidden:false}],
    results:{total:1,pending:attack,rows:[{label:attack,count:attack,pct:attack,avg_rank:attack}]}};
  context.window.LiveChart.render(target,question,{});
  assert.ok(!target.innerHTML.includes('<img'),kind+' keeps data out of markup');
  assert.ok(target.innerHTML.includes('&lt;img'),kind+' shows untrusted values as text');
}
console.log('Q&A, quiz and ranking rendering passed: untrusted numeric and text fields stay escaped.');
