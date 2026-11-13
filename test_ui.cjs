const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const html = fs.readFileSync('index.html','utf8');
const js = fs.readFileSync('app.js','utf8');
const seed = code => ({version:'5.0.0',code,name:code==='1815'?'富喬':code==='5475'?'德宏':'台積電',market:code==='1815'||code==='5475'?'TPEx':'TWSE',
 date:'2026-11-12',close:137,change:1,score:70,tags:['20MA上升','5MA>20MA'],series:[100,110,120],
 rsi5:70,rsi10:65,rsi10_overheat_days:0,ma5:120,ma20:110,volume_ratio:1.5,macd_hist:2,
 trend_pass:true,risk_level:'一般',data_warnings:[],source_url:'https://www.tpex.org.tw/',history_days:91});
async function setup({corrupt=false,deny=false,fail=false,stock=null}={}){
 const dom=new JSDOM(html,{url:'https://test.invalid' + (stock ? '?stock=' + stock : ''),runScripts:'outside-only'});
 const w=dom.window;
 w.scrollTo=()=>{};
 w.matchMedia=()=>({matches:false});
 if(corrupt)w.localStorage.setItem('bruce-favorites','{invalid-json');
 if(deny)Object.defineProperty(w,'localStorage',{get(){throw new Error('Storage denied');}});
 const calls=[];
 w.fetch=async url=>{
  calls.push(url);
  if(url==='/health')return {ok:true,json:async()=>({version:'5.0.0'})};
  if(url==='/api/catalog')return {ok:true,json:async()=>({stocks:{'1815':{name:'富喬',market:'TPEx'},'5475':{name:'德宏',market:'TPEx'}},fetched_at:'2026-11-13'})};
  const code=new URL(url,'https://test.invalid').searchParams.get('code');
  if(code==='9999')return {ok:false,status:502,json:async()=>({error:'查無官方日線'})};
  if(code==='8888')throw Object.assign(new Error('timeout'),{name:'AbortError'});
  if(fail&&!url.includes('refresh=1'))return {ok:false,status:502,json:async()=>({error:'暫時無法連線'})};
  return {ok:true,json:async()=>seed(code)};
 };
 w.eval(js);
 await settle();
 return {dom,w,calls,$:s=>w.document.querySelector(s),click:s=>w.document.querySelector(s).click()};
}
async function settle(){for(let i=0;i<8;i++)await new Promise(r=>setImmediate(r));}
test('tabs remain usable with corrupt or unavailable storage',async()=>{
 for(const opts of [{corrupt:true},{deny:true}]){
  const {dom,$,click}=await setup(opts);
  for(const tab of ['radar-tab','indicators','settings','home']){
   click(`[data-tab="${tab}"]`); assert.equal($('#'+tab).classList.contains('hidden'),false);
  }
  click('#home-list [data-fav]');
  dom.window.close();
 }
});
test('company-name search adds out-of-watchlist TPEx and survives rendering',async()=>{
 const {dom,$,click,calls}=await setup();
 click('[data-tab="radar-tab"]');$('#search').value='德宏';click('#search-submit');await settle();
 assert.ok(calls.includes('/api/stocks?code=5475'));
 assert.match($('#search-status').textContent,/已載入 5475 德宏（TPEx）/);
 assert.match($('#radar-list').textContent,/德宏/);
 assert.ok(JSON.parse(dom.window.localStorage.getItem('bruce-watchlist')).includes('5475'));
 dom.window.close();
});
test('indicator result-card expand/favorite redraws and filters update immediately',async()=>{
 const {dom,$,click}=await setup();
 click('[data-tab="indicators"]');
 assert.match($('#filter-status').textContent,/符合 7 檔/);
 click('#filter-results [data-expand]');assert.ok($('#filter-results article').classList.contains('open'));
 click('#filter-results [data-fav]');assert.match($('#filter-results [data-fav]').textContent,/已收藏/);
 $('#f-volume').checked=true;$('#f-volume-limit').value='2';click('#filter-apply');
 assert.match($('#filter-status').textContent,/符合 0 檔/);
 $('#f-volume-limit').value='';click('#filter-apply');assert.match($('#filter-status').textContent,/門檻/);
 click('#filter-reset');assert.match($('#filter-status').textContent,/符合 7 檔/);
 dom.window.close();
});
test('invalid codes, upstream errors, timeouts and retry are visible and recoverable',async()=>{
 const {dom,$,click}=await setup({fail:true});
 assert.match($('#status').textContent,/0\/7 檔成功/);
 click('#home-list [data-retry]');await settle();assert.match($('#home-list').textContent,/查看分析/);
 click('[data-tab="radar-tab"]');
 for(const [query,expected] of [['abc',/請輸入4位/],['9999',/查無官方日線/],['8888',/查詢逾時/]]){
  $('#search').value=query;click('#search-submit');await settle();assert.match($('#search-status').textContent,expected);assert.equal($('#search-submit').disabled,false);
 }
 dom.window.close();
});
test('duplicate lookups deduplicate requests and favorites-only cannot hide results',async()=>{
 const {dom,$,click,calls}=await setup();
 $('#favorites-only').checked=true;
 click('[data-tab="radar-tab"]');$('#search').value='5475';click('#search-submit');click('#search-submit');await settle();
 assert.equal(calls.filter(x=>x==='/api/stocks?code=5475').length,1);
 assert.equal($('#favorites-only').checked,false);
 assert.match($('#radar-list').textContent,/德宏/);
 dom.window.close();
});

test('deep link loads a new TPEx once; custom stock can be removed',async()=>{
 const {dom,$,click,calls}=await setup({stock:'5475'});
 assert.equal($('#radar-tab').classList.contains('hidden'),false);
 assert.equal(calls.filter(x=>x==='/api/stocks?code=5475').length,1);
 click('#radar-list [data-remove="5475"]');
 assert.equal($('#radar-list [data-code="5475"]'),null);
 dom.window.close();
});
