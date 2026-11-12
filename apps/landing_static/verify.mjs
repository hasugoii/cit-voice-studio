import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const base=new URL('.',import.meta.url),read=n=>fs.readFileSync(new URL(n,base),'utf8');
const html=read('homepage.html'),source=read('homepage.js'),css=read('homepage.css');
for(const target of ['tinh-nang','nghe-thu','cach-dung','api','faq','bat-dau'])assert.ok(html.includes(`id="${target}"`));
assert.ok(html.includes('Donomi Voice'));assert.ok(html.includes('rel="canonical" href="__PUBLIC_URL__/"'));
assert.ok(!/<audio[^>]*autoplay/i.test(html));assert.ok(!/google-analytics|gtag\(|fbq\(|localStorage|innerHTML/.test(source+html));
for(const m of (html+css).matchAll(/\/saas\/landing-assets\/([a-zA-Z0-9_.-]+)/g))assert.ok(fs.existsSync(new URL(m[1],base)),`Missing ${m[1]}`);
for(const n of ['demo-male.wav','demo-female.wav'])assert.equal(fs.readFileSync(new URL(n,base)).toString('ascii',0,4),'RIFF');
class ClassList{constructor(){this.s=new Set();}add(n){this.s.add(n);}remove(n){this.s.delete(n);}toggle(n,v){v?this.add(n):this.remove(n);}}
class El{constructor(){this.classList=new ClassList();this.handlers={};this.textContent='';this.disabled=true;this.dataset={};this.style={setProperty(){}};}addEventListener(n,f){this.handlers[n]=f;}setAttribute(n,v){this[n]=v;}querySelector(){return new El();}append(){}}
class Media extends El{constructor(id){super();this.id=id;this.paused=true;this.currentTime=0;this.duration=5;}pause(){this.paused=true;this.handlers.pause?.();}async play(){if(this.fail)throw new Error('network');this.paused=false;this.handlers.play?.();}}
function context(){const audios=[new Media('demo-male'),new Media('demo-female')];const buttons=audios.map(a=>{const b=new El();b.dataset.play=a.id;return b;});const form=new El();form.reportValidity=()=>true;form.reset=()=>{form.resets=(form.resets||0)+1;};const result=new El(),submit=new El(),status=new El();const calls=[];let mode='success';const payload={name:'Nguyễn An',email:'an@example.invalid',purpose:'Video',website:''};
 const doc={documentElement:new El(),querySelector:s=>({'#access-form':form,'#request-submit':submit,'#request-status':result,'#audio-status':status}[s]),querySelectorAll:s=>s==='audio[id]'?audios:s==='[data-play]'?buttons:[],getElementById:id=>audios.find(a=>a.id===id),createElement:()=>new El()};
 const ctx=vm.createContext({document:doc,HTMLMediaElement:Media,FormData:class{get(n){return payload[n]}},AbortController,setTimeout,clearTimeout,Error,fetch:async(url,options)=>{calls.push({url,options});return{ok:mode==='success',status:mode==='success'?200:503,json:async()=>mode==='success'?{ok:true,message:'Đã ghi nhận'}:{detail:'Máy chủ đang bận'}};}});vm.runInContext(source,ctx);return{audios,buttons,form,result,submit,status,calls,setMode:m=>{mode=m}};}
const c=context();assert.ok(c.buttons.every(b=>!b.disabled));await c.buttons[0].handlers.click();assert.equal(c.audios[0].paused,false);await c.buttons[1].handlers.click();assert.equal(c.audios[0].paused,true);assert.equal(c.audios[1].paused,false);c.audios[1].pause();c.audios[0].fail=true;await c.buttons[0].handlers.click();assert.ok(c.status.classList.s.has('error'));assert.equal(c.buttons[0].disabled,false);
await c.form.handlers.submit({preventDefault(){}});assert.equal(c.calls[0].url,'/saas/api/access-requests');assert.equal(c.calls[0].options.credentials,'omit');assert.deepEqual(JSON.parse(c.calls[0].options.body),{name:'Nguyễn An',email:'an@example.invalid',purpose:'Video',website:''});assert.equal(c.form.resets,1);assert.equal(c.result.textContent,'Đã ghi nhận');
c.setMode('error');await c.form.handlers.submit({preventDefault(){}});assert.equal(c.form.resets,1);assert.ok(c.result.classList.s.has('error'));assert.equal(c.result.textContent,'Máy chủ đang bận');assert.equal(c.submit.disabled,false);
console.log('PASS: assets/links, real WAVs, single playback, audio error recovery, manual form success/error, no secret storage or tracking.');
