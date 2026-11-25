const {test} = require('node:test');
const assert = require('node:assert/strict');
const {esc,parseCodes,filterStocks,filterBurstRows} = require('./app.js');
test('corrupt or denied storage cannot break navigation startup',()=>{
  assert.deepEqual(parseCodes('{bad'),[]);
  assert.deepEqual(parseCodes('{"2330":true}'),[]);
  assert.deepEqual(parseCodes('["2330","2330","1815",23,"<script>"]'),['2330','1815']);
});
test('all HTML-sensitive characters escaped',()=>{
  assert.equal(esc("<>&\"'"),'&lt;&gt;&amp;&quot;&#39;');
});
const options={ma:true,rsi:false,volume:false,macd:false,rsiLimit:90,volumeLimit:1.2};
const stocks={
 '2330':{trend_pass:true,rsi5:70,volume_ratio:1.5,macd_hist:2},
 '1815':{trend_pass:false,rsi5:95,volume_ratio:2.5,macd_hist:-1},
 '5475':{trend_pass:true,rsi5:90,volume_ratio:1.1,macd_hist:-.01},
 '9999':{error:'unavailable'},'1234':null,'5678':{loading:true}
};
test('trend filter requires actual trend condition and excludes failed/loading',()=>{
 assert.deepEqual(filterStocks(stocks,options),['2330','5475']);
});
test('RSI threshold, volume and MACD gates work together',()=>{
 assert.deepEqual(filterStocks(stocks,{...options,rsi:true,volume:true,macd:true}),['2330']);
 assert.deepEqual(filterStocks(stocks,{...options,ma:false,rsi:true,rsiLimit:90}),['2330']);
 assert.deepEqual(filterStocks(stocks,{...options,ma:false,volume:true,volumeLimit:2}),['1815']);
});
test('invalid and empty thresholds fail visibly; disabled fields do not block',()=>{
 for(const rsiLimit of [NaN,49,101])assert.throws(()=>filterStocks(stocks,{...options,rsi:true,rsiLimit}));
 for(const volumeLimit of [NaN,-1,101])assert.throws(()=>filterStocks(stocks,{...options,volume:true,volumeLimit}));
 assert.doesNotThrow(()=>filterStocks(stocks,{...options,rsiLimit:NaN,volumeLimit:NaN}));
});

test('burst ranking filters market, trend, strength and amount ratio together', () => {
  const rows = [
    {code:'2330', market:'TWSE', signal:'strong', amount_ratio:2.8, trend_pass:true},
    {code:'1815', market:'TPEx', signal:'strong', amount_ratio:2.1, trend_pass:false},
    {code:'5475', market:'TPEx', signal:'weak', amount_ratio:3, trend_pass:false},
  ];
  const matches = filterBurstRows(rows, {market:'TPEx', signal:'weak', trendOnly:false, minimum:2});
  assert.deepEqual(matches.map(row => row.code), ['5475']);
  assert.deepEqual(filterBurstRows(rows, {market:'all', signal:'strong', trendOnly:true, minimum:3}), []);
});
