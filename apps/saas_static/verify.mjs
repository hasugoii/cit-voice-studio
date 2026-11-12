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
 let loggedIn=isAdmin;
 const context=vm.createContext({console,Node:Element,document:{querySelector:s=>nodes[s],createElement:t=>new Element(t),createTextNode:t=>t},location:{pathname:isAdmin?'/saas/admin':'/saas/',origin:'https://voice.test',replace(){}},URLSearchParams,window:{addEventListener(){}},URL:class extends URL {static createObjectURL(){return 'blob:test';}static revokeObjectURL(){}},navigator:{clipboard:{writeText:async()=>{}}},Blob,confirm:()=>true,FormData:class{},fetch:async(url,options)=>{
  calls.push({url,...options});let value={};let status=200;
  if(url.endsWith('/config'))value={registration_enabled:false,currency:'JPY',billing_mode:'manual'};
  else if(url.endsWith('/me')){if(!loggedIn)status=401;else value=isAdmin?{admin:{id:'a1',username:'owner',name:'Owner',status:'active'},session_csrf:'admin-csrf'}:response;}
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
  const call=calls.at(-1);assert.equal(call.headers['X-CSRF-Token'],'admin-csrf');assert.equal(calls[0].url,'/saas/api/admin-auth/me');assert.equal(call.headers['X-Requested-With'],'CIT-SaaS');assert.equal(call.headers['Content-Type'],'application/json');
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

// Isolated admin sessions: exercise actual form handlers, failures and redirects.
const source=fs.readFileSync(new URL('./app.js',import.meta.url),'utf8');
const flatten=e=>[e,...(e.children||[]).flatMap(x=>typeof x==='object'?flatten(x):[])];
async function adminSession({login=false,expired=false,search='',hash=''}={}){
 const nodes=Object.fromEntries(['content','nav','notice','workspace'].map(x=>['#'+x,new Element('div')]));
 const calls=[],redirects=[];let failLogin=false,failRequest=false,wrongPassword=false;
 const location={pathname:login?'/saas/admin/login':'/saas/admin',origin:'https://voice.test',search,hash,replace:url=>redirects.push(url)};
 const context=vm.createContext({Node:Element,document:{querySelector:s=>nodes[s],createElement:t=>new Element(t),createTextNode:t=>t},location,URL,URLSearchParams,window:{addEventListener(){}},FormData:class{constructor(form){this.items=flatten(form).filter(x=>x.name).map(x=>[x.name,x.value]);}[Symbol.iterator](){return this.items[Symbol.iterator]();}},fetch:async(url,options)=>{
  calls.push({url,...options});let status=200,value={};
  if(url.endsWith('/admin-auth/login')){if(failLogin)status=401;else value={admin:{id:'a',username:'owner',name:'Owner',status:'active'},session_csrf:'owner-csrf'};}
  else if(url.endsWith('/admin-auth/me')){if(expired)status=401;else value={admin:{id:'a',username:'owner',name:'Owner',status:'active'},session_csrf:'owner-csrf'};}
  else if(wrongPassword&&url.endsWith('/admin-auth/password')){status=401;value={detail:'Mật khẩu hiện tại không đúng.'};}
  else if(failRequest)status=401;
  else if(url.endsWith('/config'))value={registration_enabled:false};
  else if(url.endsWith('/admin-auth/password'))value={ok:true,login_required:true};
  else if(url.endsWith('/admin-auth/logout'))value={ok:true};
  return {ok:status===200,status,headers:{get:()=> 'application/json'},json:async()=>value};
 }});
 const run=code=>vm.runInContext(code,context);
 run(source);await new Promise(r=>setTimeout(r,0));
 return {nodes,calls,redirects,run,location,setFailLogin:v=>failLogin=v,setWrongPassword:v=>wrongPassword=v,setFailRequest:()=>failRequest=true};
}
const signedOut=await adminSession({expired:true,hash:'#account'});
assert.equal(signedOut.calls.length,1);assert.match(signedOut.redirects[0],/^\/saas\/admin\/login\?next=/);assert.equal(signedOut.nodes['#content'].children.length,0);
const signIn=await adminSession({login:true,search:'?next=%2Fsaas%2Fadmin%23account'});
assert.equal(signIn.calls.length,0);
for(const unsafe of ['https://evil.test','//evil.test','/\\evil.test','/saas/admin/login','/a\nb','javascript:alert(1)'])assert.equal(signIn.run(`safeAdminNext(${JSON.stringify(unsafe)})`),'/saas/admin');
assert.equal(signIn.run("safeAdminNext('/saas/admin?tab=users#list')"),'/saas/admin?tab=users#list');
let elements=flatten(signIn.nodes['#content']),form=elements.find(x=>x.tagName==='form'),password=elements.find(x=>x.name==='password'),username=elements.find(x=>x.name==='username'),submit=elements.find(x=>x.type==='submit');
assert.equal(password.type,'password');assert.equal(password.minLength,12);assert.equal(password.maxLength,256);
username.value='owner';password.value='test-password-123';signIn.setFailLogin(true);
const attempt=form.onsubmit({preventDefault(){}});assert.equal(submit.disabled,true);await form.onsubmit({preventDefault(){}});await attempt;
assert.equal(signIn.calls.length,1);assert.match(signIn.nodes['#notice'].textContent,/Tên đăng nhập hoặc mật khẩu không đúng/);assert.equal(password.value,'');assert.equal(submit.disabled,false);assert.equal(signIn.redirects.length,0);
signIn.setFailLogin(false);password.value='test-password-123';await form.onsubmit({preventDefault(){}});
assert.equal(signIn.redirects.at(-1),'/saas/admin#account');assert.equal(signIn.calls.at(-1).headers['X-CSRF-Token'],undefined);
const owner=await adminSession();assert.ok(flatten(owner.nodes['#nav']).some(x=>x.textContent==='owner'));
for(const [path,method]of [['/admin/settings','PATCH'],['/admin/users','POST'],['/admin/users/u1','PATCH'],['/admin/plans/p1','DELETE']]){
 await owner.run(`api('${path}','${method}',{})`);assert.equal(owner.calls.at(-1).headers['X-CSRF-Token'],'owner-csrf');
}
owner.run('adminAccount()');elements=flatten(owner.nodes['#content']);form=elements.find(x=>x.tagName==='form');
for(const name of ['current_password','new_password']){const input=elements.find(x=>x.name===name);input.value='test-password-123';assert.equal(input.type,'password');assert.equal(input.maxLength,256);}
await form.onsubmit({preventDefault(){}});const change=owner.calls.at(-1);assert.equal(change.url,'/saas/api/admin-auth/password');assert.equal(change.headers['X-CSRF-Token'],'owner-csrf');assert.deepEqual(JSON.parse(change.body),{current_password:'test-password-123',new_password:'test-password-123'});assert.match(owner.redirects.at(-1),/reason=password-changed/);
const logout=await adminSession();await flatten(logout.nodes['#nav']).find(x=>x.textContent==='Đăng xuất').onclick();assert.equal(logout.calls.at(-1).url,'/saas/api/admin-auth/logout');assert.equal(logout.calls.at(-1).headers['X-CSRF-Token'],'owner-csrf');assert.ok(logout.redirects.length);
const expiry=await adminSession();expiry.setFailRequest();await assert.rejects(expiry.run("api('/admin/users')"));assert.ok(expiry.redirects.length);assert.equal(expiry.nodes['#content'].children.length,0);
const missingCsrf=await adminSession();missingCsrf.run("csrf=''");const before=missingCsrf.calls.length;await assert.rejects(missingCsrf.run("api('/admin/settings','PATCH',{})"));assert.equal(missingCsrf.calls.length,before);
assert.ok(!/localStorage|sessionStorage|console\./.test(source));
console.log('PASS: admin session gate, safe redirects, login errors/busy/password clearing, account password revocation flow, logout, expiry and CSRF on mutations.');

const retryPassword=await adminSession({hash:'#account'});
retryPassword.setWrongPassword(true);
const accountElements=flatten(retryPassword.nodes['#content']);
const passwordForm=accountElements.find(x=>x.tagName==='form');
for(const name of ['current_password','new_password'])accountElements.find(x=>x.name===name).value='test-password-123';
await passwordForm.onsubmit({preventDefault(){}});
assert.equal(retryPassword.nodes['#notice'].textContent,'Mật khẩu hiện tại không đúng.');
assert.equal(retryPassword.redirects.length,0);
assert.equal(retryPassword.run('csrf'),'owner-csrf');
assert.equal(retryPassword.run('adminIdentity.username'),'owner');
assert.equal(accountElements.find(x=>x.type==='submit').disabled,false);
retryPassword.setWrongPassword(false);
for(const name of ['current_password','new_password'])accountElements.find(x=>x.name===name).value='test-password-456';
await passwordForm.onsubmit({preventDefault(){}});
assert.equal(retryPassword.calls.at(-1).headers['X-CSRF-Token'],'owner-csrf');
assert.match(retryPassword.redirects.at(-1),/reason=password-changed/);
for(const session of [signIn,owner,logout,expiry,retryPassword]){
 assert.ok(session.calls.every(call=>call.headers.Authorization===''&&call.credentials==='same-origin'));
}
console.log('PASS: wrong current password preserves session and displays server message; retry succeeds; admin fetch overrides cached HTTP Authorization while retaining cookies.');
