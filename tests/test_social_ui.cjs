const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const script=fs.readFileSync(path.join(__dirname,'../tweet-metrics.js'),'utf8');
class Node {
 constructor(tag){this.tag=tag;this.children=[];this.attributes={};this.dataset={};this.events={};this.isConnected=true;this._text='';}
 set textContent(v){this._text=String(v);this.children=[];} get textContent(){return this._text+this.children.map(n=>n.textContent).join(' ');}
 get childNodes(){return this.children;}
 append(...ns){this.children.push(...ns);}
 before(...ns){this.beforeNodes=[...(this.beforeNodes||[]),...ns];}
 after(...ns){this.afterNodes=[...(this.afterNodes||[]),...ns];}
 replaceChildren(...ns){this._text='';this.children=ns;}
 setAttribute(k,v){this.attributes[k]=v;}
 removeAttribute(k){delete this.attributes[k];}
 addEventListener(k,v){this.events[k]=v;}
 closest(){return this.list?this:null;}
 querySelectorAll(q){const result=[];const walk=n=>{for(const c of n.children){if(q[0]==='.' && (c.className||'').split(' ').includes(q.slice(1)))result.push(c);walk(c)}};walk(this);return result;}
 querySelector(q){return this.querySelectorAll(q)[0]||null;}
 insertBefore(n,ref){const i=this.children.indexOf(ref);if(i<0)throw Error('bad insert');this.children.splice(i,0,n);}
 focus(){this.focused=true;}
}
const now=new Date().toISOString(), old=new Date(Date.now()-15*864e5).toISOString();
async function run(data,{list=false,x='12345',yt='abcdefghijk',fail=false}={}){
 const slot=new Node('div');slot.dataset={tweetMetrics:x,youtubeId:yt};slot.list=list;
 slot.setAttribute('aria-label','Engagement on X');
 const head=new Node('head'),timers=[];
 const document={head,querySelectorAll:()=>[slot],createElement:t=>new Node(t)};
 let requests=[];
 const context={document,window:{},URL,AbortController,Date,Number,Promise,console,setTimeout:(fn,ms)=>{timers.push({fn,ms});return timers.length;},clearTimeout:()=>{},fetch:async(url)=>{requests.push(url);if(fail)throw Error('offline');return {ok:true,json:async()=>data}}};
 await vm.runInNewContext(script,context);
 return {slot,head,timers,requests,context};
}
(async()=>{
 let r=await run({schema_version:1,x:{},youtube:{}});assert(r.slot.textContent.includes('currently unavailable'));assert.equal(r.head.children.length,0);assert.deepEqual(r.requests,['/data/social.json']);
 let yt={updated_at:now,metrics:{view_count:20,like_count:0,comment_count:'4'},comments_status:'available',comments:Array.from({length:5},(_,i)=>({id:`Ugy${i}`,author:'<img onerror=bad>',text:'<script>bad</script>\nFull text',published_at:now,author_image_url:'javascript:alert(1)',author_channel_url:'https://evil.test/channel/abc'}))};
 r=await run({schema_version:1,x:{'12345':{updated_at:old,metrics:{like_count:99999}}},youtube:{abcdefghijk:yt}});
 assert(!r.slot.textContent.includes('99999'));assert(r.slot.textContent.includes('20'));assert(r.slot.textContent.includes('0'));assert(!r.slot.textContent.includes('4 comments'));
 assert.equal(r.slot.querySelectorAll('.sample-comment').length,5);assert.equal(r.slot.querySelectorAll('.sample-avatar').filter(n=>n.tag==='img').length,0);
 const panels=r.slot.querySelectorAll('.platform-panel');assert.equal(panels[0].hidden,true);assert.equal(panels[1].hidden,false);
 const buttons=r.slot.querySelector('.platform-tabs').children;buttons[1].events.keydown({key:'Home',preventDefault(){}});assert.equal(panels[0].hidden,false);assert(buttons[0].focused);buttons[0].events.click();assert.equal(r.slot.querySelectorAll('.sample-comment').length,5);
 r=await run({schema_version:1,x:{'12345':{updated_at:now,metrics:{like_count:4,reply_count:null},comments:[{id:'45678'},{id:'javascript:bad'}]}},youtube:{}});
 assert.equal(r.head.children.length,0);assert.equal(r.slot.querySelectorAll('.x-reply').length,1);
 const load=r.slot.querySelector('.load-embed');const pending=load.events.click();assert.equal(r.head.children.length,1);await load.events.click();assert.equal(r.head.children.length,1);r.head.children[0].onerror();await pending;assert(load.textContent.includes('could not load'));
 r=await run({schema_version:1,x:{'12345':{updated_at:now,metrics:{like_count:12}}},youtube:{abcdefghijk:yt}},{list:true});assert.equal(r.slot.querySelectorAll('.platform-stat-line').length,2);assert.equal(r.slot.hidden,false);assert(r.slot.textContent.includes('20 views'));assert.equal(r.slot.beforeNodes,undefined);assert.equal(r.slot.afterNodes[0].className,'social-legal');assert(r.slot.afterNodes[0].textContent.includes('YouTube terms'));
 r=await run({schema_version:1,x:{},youtube:{}},{list:true});assert.equal(r.slot.hidden,true);assert.equal(r.slot.attributes['aria-label'],undefined);
 r=await run({schema_version:1,x:{},youtube:{abcdefghijk:yt}},{list:true});assert.equal(r.slot.attributes['aria-label'],undefined);assert(r.slot.textContent.includes('YouTube'));assert(r.slot.textContent.includes('20 views'));
 r=await run({}, {fail:true,x:'',yt:''});assert(r.slot.textContent.includes('No social sources'));assert.equal(r.slot.querySelectorAll('.platform-tabs').length,0);
 r=await run({schema_version:1,x:{},youtube:{}},{yt:''});assert.equal(r.slot.querySelector('.platform-tabs').children.length,1);assert(!r.slot.textContent.includes('YouTube'));
 const single=r.slot.querySelector('.platform-tabs').children[0];for(const key of ['ArrowRight','ArrowLeft','Home','End'])single.events.keydown({key,preventDefault(){}});assert.equal(single.attributes['aria-selected'],'true');
 r=await run({schema_version:1,x:{},youtube:{}},{x:''});assert.equal(r.slot.querySelector('.platform-tabs').children.length,1);assert.equal(r.slot.querySelector('.platform-tabs').children[0].textContent,'YouTube');
 const withAvatar={...yt,comments:[{...yt.comments[0],author_image_url:'https://yt3.ggpht.com/avatar'}]};
 r=await run({schema_version:1,x:{},youtube:{abcdefghijk:withAvatar}});
 assert.equal(r.slot.querySelector('.platform-tabs').children.find(n=>n.textContent==='YouTube').attributes['aria-selected'],'true');
 assert.equal(r.slot.querySelectorAll('.sample-comment').length,1);assert.equal(r.slot.querySelectorAll('.sample-avatar').length,1);assert(r.slot.textContent.includes('20'));assert(r.slot.textContent.includes('Privacy'));
 assert.equal(r.slot.querySelectorAll('.sample-avatar').filter(n=>n.tag==='img').length,0);
 assert.equal(r.slot.querySelectorAll('.youtube-consent').length,0);assert(!r.slot.textContent.includes('Agree and show YouTube'));
 assert.equal(r.slot.querySelectorAll('.social-legal').length,1);assert.equal(r.head.children.length,0);assert.deepEqual(r.requests,['/data/social.json']);
 // Reloads and multiple tab switches require no agreement and do not duplicate comments.
 r=await run({schema_version:1,x:{},youtube:{abcdefghijk:withAvatar}});
 const repeatedTabs=r.slot.querySelector('.platform-tabs').children;
 for(let i=0;i<3;i++){repeatedTabs[0].events.click();repeatedTabs[1].events.click();}
 assert.equal(r.slot.querySelectorAll('.sample-comment').length,1);assert.equal(r.slot.querySelectorAll('.sample-avatar').filter(n=>n.tag==='img').length,0);
 // A YouTube snapshot that expires on an open page disappears without stale fallback.
 const nearExpiry={...withAvatar,updated_at:new Date(Date.now()-14*864e5+5000).toISOString()};
 r=await run({schema_version:1,x:{},youtube:{abcdefghijk:nearExpiry}});
 assert.equal(r.slot.querySelectorAll('.sample-comment').length,1);
 const expiry=r.timers.find(t=>t.ms>1 && t.ms<10000);assert(expiry,'expiry timer must be scheduled');
 const actualNow=Date.now();r.context.Date=class extends Date{static now(){return actualNow+20000;}};expiry.fn();
 assert.equal(r.slot.querySelectorAll('.sample-comment').length,0);assert(r.slot.textContent.includes('currently unavailable'));assert(r.slot.textContent.includes('YouTube terms'));
 console.log('PASS: unavailable, stale, zero-vs-missing, unsafe text/URLs, comments, tabs, X consent/repeat/failure, direct YouTube statistics/comments/listing, no remote avatars, reload/repeat/expiry, no sources/offline');
})().catch(e=>{console.error(e);process.exitCode=1});
