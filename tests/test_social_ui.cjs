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
 setAttribute(k,v){this.attributes[k]=v;if(k==='class')this.className=v;}
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
 const document={head,querySelectorAll:()=>[slot],createElement:t=>new Node(t),createElementNS:(_namespace,t)=>new Node(t),createTextNode:text=>{const n=new Node('#text');n.textContent=text;return n;}};
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

 const xc={id:'45678',author_id:'777',author:'Real <Author>',username:'real_author',author_url:'https://x.com/real_author',author_image_url:'https://pbs.twimg.com/profile_images/avatar.jpg',text:'Hello <script>bad</script> 😀 @friend https://t.co/abc #Art $USD',published_at:now,source_url:'https://x.com/real_author/status/45678',entities:{mentions:[{username:'friend',start:28,end:35}],urls:[{url:'https://t.co/abc',expanded_url:'https://example.com/story'}],hashtags:[{tag:'Art'}],cashtags:[{tag:'USD'}]}};
 const snapshot={mode:'one_time',updated_at:old,metrics:{like_count:4,reply_count:null},comments:[xc]};
 r=await run({schema_version:1,x:{'12345':snapshot},youtube:{}});
 assert.equal(r.head.children.length,0);assert.equal(r.slot.querySelectorAll('.x-comment').length,1);
 assert.equal(r.slot.querySelectorAll('.load-embed').length,0);assert(!r.slot.textContent.includes('not live'));assert(r.slot.querySelector('.platform-metrics').children[0].title.includes('not live'));assert(!r.slot.textContent.includes('refreshed weekly'));
 assert.equal(r.slot.querySelector('.platform-panel').hidden,false);
 const xcomment=r.slot.querySelector('.x-comment');
 assert.equal(xcomment.querySelector('.sample-avatar').src,xc.author_image_url);assert.equal(xcomment.querySelector('.sample-avatar').referrerPolicy,'no-referrer');
 assert(xcomment.textContent.includes('Real <Author>'));assert(xcomment.textContent.includes('@real_author'));assert(xcomment.textContent.includes('View on X'));
 const textNode=xcomment.querySelector('.x-comment-text');
 assert.equal(textNode.children.map(n=>n.textContent).join(''),xc.text);
 const textLinks=textNode.children.filter(n=>n.tag==='a');assert.equal(textLinks.length,4);assert(textLinks.some(n=>n.href==='https://t.co/abc'));
 assert.equal(r.slot.querySelectorAll('.x-panel-brand').length,0);
 const brandLogo=r.slot.querySelector('.platform-tabs').querySelector('.x-tab-logo');
 assert(brandLogo);assert.equal(brandLogo.alt,'X');assert.equal(brandLogo.width,14);assert.equal(brandLogo.height,14);
 assert.equal(r.slot.querySelector('.platform-tabs').children[0].attributes['aria-label'],'X');
 assert(!r.timers.some(t=>t.ms>10000),'one-time snapshots have no expiry timer');
 const xTabs=r.slot.querySelector('.platform-tabs').children;for(let i=0;i<3;i++){xTabs[1].events.click();xTabs[0].events.click();}
 assert.equal(r.slot.querySelectorAll('.x-comment').length,1);
 assert.equal(r.slot.querySelectorAll('.x-tab-logo').length,1);assert.equal(r.slot.querySelectorAll('.x-panel-brand').length,0);
 for(const changes of [{author:''},{author_id:''},{username:''},{author_image_url:'javascript:alert(1)'},{author_image_url:'https://pbs.twimg.com.evil.test/a'},{author_image_url:'https://user:pass@pbs.twimg.com/a'},{author_url:'https://evil.test/real_author'},{published_at:'bad'},{id:'bad'},{text:null}]){
   r=await run({schema_version:1,x:{'12345':{...snapshot,comments:[{...xc,...changes}]}},youtube:{}});
   assert.equal(r.slot.querySelectorAll('.x-comment').length,0);assert(r.slot.textContent.includes('4'));
 }
 // Both exact UTF-16 and Unicode codepoint entity offsets preserve original text.
 for(const start of [3,2]){
   const text='😀 @friend and @friend';
   r=await run({schema_version:1,x:{'12345':{...snapshot,comments:[{...xc,text,entities:{mentions:[{username:'friend',start,end:start+7}]}}]}},youtube:{}});
   const p=r.slot.querySelector('.x-comment-text');assert.equal(p.children.map(n=>n.textContent).join(''),text);assert.equal(p.children.filter(n=>n.tag==='a').length,1);
 }
 // Unsafe URLs, invalid entities and ambiguous fallback stay literal, not HTML.
 const unsafeText='https://t.co/x @friend @friend <img src=x onerror=bad>';
 r=await run({schema_version:1,x:{'12345':{...snapshot,comments:[{...xc,text:unsafeText,entities:{urls:[{url:'https://t.co/x',expanded_url:'javascript:alert(1)'},null],mentions:[{username:'friend',start:99,end:106}],hashtags:[null,{tag:'<bad>'}]}}]}},youtube:{}});
 assert.equal(r.slot.querySelector('.x-comment-text').children.filter(n=>n.tag==='a').length,1);
 assert.equal(r.slot.querySelector('.x-comment-text').children.find(n=>n.tag==='a').href,'https://t.co/x');
 assert.equal(r.slot.querySelector('.x-comment-text').children.map(n=>n.textContent).join(''),unsafeText);
 r=await run({schema_version:1,x:{'12345':{...snapshot,comments:[{...xc,author_image_url:'https://abs.twimg.com/default.png'}]}},youtube:{}});
 assert.equal(r.slot.querySelectorAll('.x-comment').length,1);
 // One-time retention applies only to X and requires a valid, nonfuture timestamp.
 for(const updated_at of ['bad',new Date(Date.now()+864e5).toISOString()]){
   r=await run({schema_version:1,x:{'12345':{...snapshot,updated_at}},youtube:{}});assert.equal(r.slot.querySelectorAll('.x-comment').length,0);
 }
 r=await run({schema_version:1,x:{'12345':{...snapshot,mode:undefined}},youtube:{}});assert.equal(r.slot.querySelectorAll('.x-comment').length,0);
 r=await run({schema_version:1,x:{},youtube:{abcdefghijk:{...yt,mode:'one_time',updated_at:old}}});assert.equal(r.slot.querySelectorAll('.sample-comment').length,0);
 r=await run({schema_version:1,x:{'12345':snapshot},youtube:{}},{list:true});assert(r.slot.querySelector('.summary-metric-likes').title.includes('not live'));
 // Legacy API zeros do not mean zero reach. The list names unlike reach measures explicitly.
 for(const list of [false,true]){
   r=await run({schema_version:1,x:{'12345':{...snapshot,metrics:{like_count:0,impression_count:0}}},youtube:{}},{list,yt:''});
   assert(!r.slot.textContent.includes('views'));assert(!r.slot.textContent.includes('impressions'));
   if(list){assert.equal(r.slot.querySelectorAll('.summary-metric-views').length,0);assert.equal(r.slot.querySelector('.summary-metric-likes').textContent.trim(),'0');}
   else assert(r.slot.textContent.includes('likes'));
   const verified={...snapshot,metrics:{like_count:674,impression_count:76284},impressions_status:'owner_verified',impressions_source:{source_kind:'owner_analytics_screenshot',verified_on:'2026-11-10'}};
   r=await run({schema_version:1,x:{'12345':verified},youtube:{}},{list,yt:''});
   assert(r.slot.textContent.includes('76,284'));
   const description=list?r.slot.querySelector('.summary-metric-views').title:r.slot.querySelector('.platform-metrics').children.map(n=>n.title).join(' ');
   assert(description.includes('impressions'));assert(description.includes("owner's X Analytics screenshot, verified Nov 10, 2026"));
   if(list)assert(description.includes('not unique viewers'));else {assert(description.includes('X views (post impressions, not video plays or unique viewers)'));assert(!r.slot.textContent.includes("owner's X Analytics"));}
   r=await run({schema_version:1,x:{'12345':{...snapshot,metrics:{impression_count:55}}},youtube:{}},{list,yt:''});
   assert(r.slot.textContent.includes('55'));assert((list?r.slot.querySelector('.summary-metric-views').title:r.slot.querySelector('.platform-metrics').children[0].title).includes('impressions'));
 }
 assert(!script.includes('youtubeLegalLinks'));assert(!script.includes('metrics-legend'));assert(!script.includes('social-legal'));
 assert(!script.includes('innerHTML'));assert(!script.includes('widgets.js'));assert(!script.includes('createTweet'));
 r=await run({schema_version:1,x:{'12345':{updated_at:now,metrics:{like_count:12}}},youtube:{abcdefghijk:yt}},{list:true});
 assert.equal(r.slot.querySelectorAll('.platform-stat-line').length,0);assert.equal(r.slot.hidden,false);
 assert.equal(r.slot.querySelector('.summary-metric-views').querySelector('.metric-count').textContent,'20+');
 assert.equal(r.slot.querySelector('.summary-metric-likes').querySelector('.metric-count').textContent,'12');
 assert.equal(r.slot.querySelectorAll('.summary-metric-comments').length,0);
 assert.equal(r.slot.beforeNodes,undefined);assert.equal(r.slot.afterNodes,undefined,'No disclosure or legend block below the tutorial list');
 r=await run({schema_version:1,x:{},youtube:{}},{list:true});assert.equal(r.slot.hidden,true);assert.equal(r.slot.attributes['aria-label'],undefined);
 r=await run({schema_version:1,x:{},youtube:{abcdefghijk:yt}},{list:true});
 assert.equal(r.slot.attributes['aria-label'],undefined);assert(!r.slot.textContent.includes('YouTube'));assert(r.slot.textContent.includes('20+'));
 assert(r.slot.querySelector('.summary-metric-views').attributes['aria-label'].includes('X post impressions unavailable'));
 assert(r.slot.querySelector('.summary-metric-views').attributes['aria-label'].includes('YouTube video views'));
 // Three compact, accessible icons sum only existing, valid metrics.
 const completeX={...snapshot,metrics:{impression_count:76284,like_count:674,reply_count:13,retweet_count:50,quote_count:8},impressions_status:'owner_verified',impressions_source:{source_kind:'owner_analytics_screenshot',verified_on:'2026-11-10'}};
 const completeY={...yt,metrics:{view_count:16998,like_count:691,comment_count:19}};
 r=await run({schema_version:1,x:{'12345':completeX},youtube:{abcdefghijk:completeY}},{list:true});
 assert.equal(r.slot.querySelectorAll('.summary-metric').length,3);
 assert.deepEqual(r.slot.querySelectorAll('.metric-count').map(n=>n.textContent),['93,282','1,365','32']);
 assert(!/X|YouTube|reposts|quotes|views|likes|comments/.test(r.slot.textContent));
 for(const metric of r.slot.querySelectorAll('.summary-metric')){
   assert.equal(metric.attributes.role,'img');assert.equal(metric.title,metric.attributes['aria-label']);assert(!metric.title.includes('unavailable'));
   assert.equal(metric.querySelector('.metric-count').attributes['aria-hidden'],'true');
   const icon=metric.querySelector('.metric-icon');assert.equal(icon.tag,'svg');assert.equal(icon.attributes['aria-hidden'],'true');assert.equal(icon.attributes.focusable,'false');
 }
 const reach=r.slot.querySelector('.summary-metric-views');
 assert(reach.title.includes('X post impressions and YouTube video views'));assert(reach.title.includes('not unique viewers'));assert(reach.title.includes('76,284'));assert(reach.title.includes('16,998'));
 assert(reach.title.includes('Snapshot from'));assert(reach.title.includes('not live'));assert(reach.title.includes('Updated'));
 // Owner Analytics uses an abbreviated count: preserve uncertainty everywhere.
 const roundedX={...completeX,metrics:{impression_count:394700,like_count:4080,reply_count:35},impressions_source:{...completeX.impressions_source,precision:'rounded',rounding_increment:100,source_display:'394,7 mil'}};
 const wallsY={...completeY,metrics:{view_count:63965,like_count:1653,comment_count:72}};
 const pageX={...roundedX,impressions_source:{...roundedX.impressions_source,source_kind:'owner_analytics_page'}};
 r=await run({schema_version:1,x:{'12345':pageX},youtube:{}},{yt:''});
 assert(r.slot.textContent.includes('≈394,700'));assert(!r.slot.textContent.includes("owner's X Analytics page, verified"));assert(r.slot.querySelector('.platform-metrics').children.some(n=>n.title.includes("owner's X Analytics page, verified")));
 assert(!r.slot.textContent.includes('screenshot'));
 r=await run({schema_version:1,x:{'12345':roundedX},youtube:{abcdefghijk:wallsY}});
 assert(r.slot.textContent.includes('≈394,700'));assert(!r.slot.textContent.includes('X displays “394,7 mil”, not an exact count'));assert(r.slot.querySelector('.platform-metrics').children.some(n=>n.title.includes('X displays “394,7 mil”, not an exact count')));
 assert(r.slot.querySelector('.platform-metrics').children.some(n=>n.attributes['aria-label'].startsWith('Approximately 394,700 X views (post impressions, not video plays or unique viewers)')));
 assert(!r.slot.textContent.includes('87,912'));
 r=await run({schema_version:1,x:{'12345':roundedX},youtube:{abcdefghijk:wallsY}},{list:true});
 assert.deepEqual(r.slot.querySelectorAll('.metric-count').map(n=>n.textContent),['≈458,700','5,733','107']);
 const roundedReach=r.slot.querySelector('.summary-metric-views');
 assert(roundedReach.title.startsWith('Approximately 458,700'));
 assert(roundedReach.title.includes('X post impressions: approximately 394,700'));
 assert(roundedReach.title.includes('YouTube video views: 63,965'));
 assert.equal(roundedReach.title,roundedReach.attributes['aria-label']);
 assert.equal(r.slot.afterNodes,undefined);
 for(const ytId of ['', 'abcdefghijk']){
   r=await run({schema_version:1,x:{'12345':roundedX},youtube:{}},{list:true,yt:ytId});
   assert.equal(r.slot.querySelector('.metric-count').textContent,'≈394,700'+(ytId?'+':''));
   assert(r.slot.querySelector('.summary-metric-views').title.startsWith('Approximately '+(ytId?'at least ':'')+'394,700'));
 }
 // An unlinked platform is not missing data; genuine zero is not missing data.
 for(const platform of ['x','youtube']){
   const data={schema_version:1,x:{},youtube:{}};
   data[platform][platform==='x'?'12345':'abcdefghijk']={updated_at:now,metrics:platform==='x'?{impression_count:0,like_count:0,reply_count:0}:{view_count:0,like_count:0,comment_count:0},impressions_status:'owner_verified'};
   r=await run(data,{list:true,x:platform==='x'?'12345':'',yt:platform==='youtube'?'abcdefghijk':''});
   assert.deepEqual(r.slot.querySelectorAll('.metric-count').map(n=>n.textContent),['0','0','0']);
   assert(!r.slot.querySelector('.summary-metric-views').title.includes('unavailable'));
 }
 // Malformed counts are omitted and marked partial, never coerced into zero.
 for(const value of [null,undefined,'42',-1,1.5,Number.MAX_SAFE_INTEGER+1]){
   r=await run({schema_version:1,x:{'12345':{...completeX,metrics:{impression_count:value,like_count:value,reply_count:value}}},youtube:{abcdefghijk:completeY}},{list:true});
   assert.deepEqual(r.slot.querySelectorAll('.metric-count').map(n=>n.textContent),['16,998+','691+','19+']);
   assert(r.slot.querySelector('.summary-metric-views').title.includes('At least 16,998'));
   assert(r.slot.querySelector('.summary-metric-views').title.includes('+ indicates an unavailable contribution, not zero'));
 }
 // A safe individual count can still produce an unsafe sum; do not display it.
 r=await run({schema_version:1,x:{'12345':{...snapshot,metrics:{like_count:Number.MAX_SAFE_INTEGER}}},youtube:{abcdefghijk:{...yt,metrics:{like_count:1}}}},{list:true});
 assert.equal(r.slot.hidden,true);
 // Expiring data re-renders the list as partial without duplicating icons or legal links.
 const nearListExpiry={...completeY,updated_at:new Date(Date.now()-14*864e5+5000).toISOString()};
 r=await run({schema_version:1,x:{'12345':completeX},youtube:{abcdefghijk:nearListExpiry}},{list:true});
 const listExpiry=r.timers.find(t=>t.ms>1 && t.ms<10000);assert(listExpiry);
 const listNow=Date.now();r.context.Date=class extends Date{static now(){return listNow+20000;}};listExpiry.fn();
 assert.deepEqual(r.slot.querySelectorAll('.metric-count').map(n=>n.textContent),['76,284+','674+','13+']);
 assert.equal(r.slot.querySelectorAll('.summary-metric').length,3);assert.equal(r.slot.afterNodes,undefined);
 assert(r.slot.querySelector('.summary-metric-views').title.includes('YouTube video views unavailable'));
 r=await run({}, {fail:true,x:'',yt:''});assert(r.slot.textContent.includes('No social sources'));assert.equal(r.slot.querySelectorAll('.platform-tabs').length,0);
 r=await run({schema_version:1,x:{},youtube:{}},{yt:''});assert.equal(r.slot.querySelector('.platform-tabs').children.length,1);assert(!r.slot.textContent.includes('YouTube'));
 const single=r.slot.querySelector('.platform-tabs').children[0];for(const key of ['ArrowRight','ArrowLeft','Home','End'])single.events.keydown({key,preventDefault(){}});assert.equal(single.attributes['aria-selected'],'true');
 r=await run({schema_version:1,x:{},youtube:{}},{x:''});assert.equal(r.slot.querySelector('.platform-tabs').children.length,1);assert.equal(r.slot.querySelector('.platform-tabs').children[0].textContent,'YouTube');
 const withAvatar={...yt,comments:[{...yt.comments[0],author_image_url:'https://yt3.ggpht.com/avatar'}]};
 r=await run({schema_version:1,x:{},youtube:{abcdefghijk:withAvatar}});
 assert.equal(r.slot.querySelector('.platform-tabs').children.find(n=>n.textContent==='YouTube').attributes['aria-selected'],'true');
 assert.equal(r.slot.querySelectorAll('.sample-comment').length,1);assert.equal(r.slot.querySelectorAll('.sample-avatar').length,1);assert(r.slot.textContent.includes('20'));assert(!r.slot.textContent.includes('Privacy'));
 assert.equal(r.slot.querySelectorAll('.sample-avatar').filter(n=>n.tag==='img').length,0);
 assert.equal(r.slot.querySelectorAll('.youtube-consent').length,0);assert(!r.slot.textContent.includes('Agree and show YouTube'));
 assert.equal(r.slot.querySelectorAll('.social-legal').length,0);assert(!r.slot.textContent.includes('Updated'));assert(!r.slot.textContent.includes('refreshed weekly'));assert(r.slot.querySelectorAll('.platform-metrics').some(n=>n.children.some(c=>c.title.includes('Updated'))));assert.equal(r.head.children.length,0);assert.deepEqual(r.requests,['/data/social.json']);
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
 assert.equal(r.slot.querySelectorAll('.sample-comment').length,0);assert(r.slot.textContent.includes('currently unavailable'));assert(!r.slot.textContent.includes('YouTube terms'));
 console.log('PASS: unavailable, stale, zero-vs-missing, unsafe text/URLs, comments, tabs, custom X metadata/security/entities/one-time retention, direct YouTube statistics/comments/listing, compact three-icon sums with explicit reach measures/partial data/overflow/expiry, no remote YouTube avatars, reload/repeat/expiry, no sources/offline');
})().catch(e=>{console.error(e);process.exitCode=1});
