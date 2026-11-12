// Dependency-free API/DOM smoke checks; run: node verify.mjs
import vm from 'node:vm';
import fs from 'node:fs';
import assert from 'node:assert/strict';
class Element {
 constructor(tag){this.tagName=tag;this.children=[];this.value='';this.disabled=false;}
 append(...items){this.children.push(...items);}
 replaceChildren(...items){this.children=items;}
 get options(){return this.children;}
 setAttribute(k,v){this[k]=v;}
 scrollIntoView(){}
 remove(){}
}
async function scenario(isAdmin){
 const nodes=Object.fromEntries(['content','nav','notice','workspace'].map(x=>['#'+x,new Element('div')]));
 const calls=[];const plan={id:'trial',name:'Trial',char_limit:1000,job_max_chars:500,max_api_keys:2,price_minor:0,enabled:true,is_draft:false};
 const response={user:{id:'u1',email:'a@example.test',status:'active',plan_id:'trial'},plan,usage:{used:10,reserved:5,remaining:985,limit:1000},api_keys:[],session_csrf:'test-csrf'};
 let loggedIn=false;
 const context=vm.createContext({console,Node:Element,document:{querySelector:s=>nodes[s],createElement:t=>new Element(t),createTextNode:t=>t},location:{pathname:isAdmin?'/saas/admin':'/saas/'},window:{addEventListener(){}},URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},navigator:{clipboard:{writeText:async()=>{}}},Blob,confirm:()=>true,FormData:class{},fetch:async(url,options)=>{
  calls.push({url,...options});let value={};let status=200;
  if(url.endsWith('/config'))value={registration_enabled:false,currency:'JPY',billing_mode:'manual'};
  else if(url.endsWith('/me')){if(!loggedIn)status=401;else value=response;}
  else if(url.endsWith('/login')){loggedIn=true;value=response;}
  else if(url.endsWith('/voices'))value={voices:[{id:'v1',name:'Giọng Nhật',language:'ja'},{id:'v2',name:'Giọng Trung',language:'zh'}]};
  else if(url.endsWith('/admin/overview'))value={users_count:1,active_users:1,used_characters:10,jobs_count:1};
  else if(url.endsWith('/admin/plans'))value={items:[plan]};
  else if(url.endsWith('/admin/users'))value={items:[response.user]};
  else if(url.endsWith('/usage'))value={items:[]};
  return {ok:status===200,status,headers:{get:()=> 'application/json'},json:async()=>value};
 }});
 vm.runInContext(fs.readFileSync(new URL('./app.js',import.meta.url),'utf8'),context);
 await new Promise(r=>setTimeout(r,0));
 const run=code=>vm.runInContext(code,context);
 if(isAdmin){
  await run('adminUsers()');await run('adminPlans()');run('editPlan(null)');
  run("plans=[{id:'trial',enabled:false},{id:'pro',enabled:false},{id:'business',enabled:false}]");
  assert.equal(run('planOptions().length'),1);
  await run("api('/admin/settings','PATCH',{registration_enabled:true})");
  const call=calls.at(-1);assert.equal(call.headers['X-Requested-With'],'CIT-SaaS');assert.equal(call.headers['Content-Type'],'application/json');
 }else{
  assert.equal(run('config.registration_enabled'),false);
  await run("api('/login','POST',{email:'a@example.test',password:'test'})");
  await run('loadMe()');await run('keys()');await run('ledger()');await run('studio()');
  const flatten=e=>[e,...(e.children||[]).flatMap(x=>typeof x==='object'?flatten(x):[])];
  const elements=flatten(nodes['#content']);const language=elements.find(e=>e.name==='language'),voice=elements.find(e=>e.name==='voice_id');
  assert.equal(language.value,'ja');assert.equal(language.readOnly,true);voice.value='v2';voice.onchange();assert.equal(language.value,'zh');
  await run("api('/keys','POST',{name:'integration'})");assert.equal(calls.at(-1).headers['X-CSRF-Token'],'test-csrf');
  assert.equal(run('price({is_draft:true,price_minor:null})'),'Giá nháp · chưa công bố');
  assert.equal(run('price({is_draft:false,price_minor:null})'),'Chưa đặt giá');
 }
 assert.equal(run('timestamp(1700000000).toISOString()'), '2023-11-14T22:13:20.000Z');
 assert.equal(run("timestamp('2023-11-14T22:13:20Z').toISOString()"), '2023-11-14T22:13:20.000Z');
 assert.equal(run("(()=>{const f=el('form');const p=field(f,'Password','password','password');return p.minLength===12&&p.maxLength===256;})()"),true);
 assert.ok(nodes['#content'].children.length);
 assert.ok(calls.every(x=>x.credentials==='same-origin'));
}
await scenario(false);await scenario(true);
console.log('PASS: user/admin rendering, closed registration, real API data paths, draft/unset prices, cookie credentials, CSRF and admin mutation headers.');

const base=new URL('.',import.meta.url);
for(const name of ['index.html','admin.html','admin/index.html']){const html=fs.readFileSync(new URL(name,base),'utf8');assert.ok(html.includes('<script>'+fs.readFileSync(new URL('app.js',base),'utf8')+'</script>'),name+' JS out of sync');assert.ok(html.includes('<style>'+fs.readFileSync(new URL('style.css',base),'utf8')+'</style>'),name+' CSS out of sync');}
console.log('PASS: Unix/ISO dates, password bounds, voice languages ja/zh, disabled-plan choices, and all inline copies.');
