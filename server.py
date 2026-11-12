from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from urllib.request import Request,urlopen
from urllib.parse import urlparse,parse_qs
from datetime import date
from pathlib import Path
import json,os,time,threading
from urllib.error import URLError,HTTPError
from datetime import datetime,timezone,timedelta
ROOT=Path(__file__).resolve().parent
CACHE={}
CACHE_LOCK=threading.Lock()
CACHE_SECONDS=900
TZ_TAIPEI=timezone(timedelta(hours=8))
NAMES={'1802':'台玻','1815':'富喬','1303':'南亞','2330':'台積電','2317':'鴻海','2409':'友達','3481':'群創'}
def ema(a,n):
 out=[];v=a[0];k=2/(n+1)
 for x in a:v=v+(x-v)*k;out.append(v)
 return out
def rsi(a,n):
 if len(a)<=n:return None
 d=[a[i]-a[i-1] for i in range(1,len(a))]
 g=sum(max(x,0) for x in d[:n])/n;l=sum(max(-x,0) for x in d[:n])/n
 for x in d[n:]:g=(g*(n-1)+max(x,0))/n;l=(l*(n-1)+max(-x,0))/n
 return round(100-100/(1+g/l),2) if l else (100 if g else 50)
def signal_metrics(close, volume, ma5, ma20, r5, r10, vr, dif, sig):
 recent_high=max(close[-21:-1])
 recent_low=min(close[-21:-1])
 change=(close[-1]/close[-2]-1)*100
 breakout=close[-1]>recent_high and vr>=1.5
 distribution=(change<0 and vr>=2 and close[-1]<ma5)
 overheating=(r5 is not None and r5>=90) or (r10 is not None and r10>=90)
 alerts=[]
 if breakout:alerts.append('20日突破放量')
 if distribution:alerts.append('放量下跌警示')
 if overheating:alerts.append('RSI過熱警示')
 if close[-1]<ma20:alerts.append('跌破20MA')
 return {'alerts':alerts,'breakout20':breakout,'distribution_warning':distribution,'overheating':overheating,'reference_high20':round(recent_high,2),'reference_low20':round(recent_low,2),'signal_note':'訊號僅依日線規則判定，不是盤中點火或主力出貨證據'}

def get(code):
 now=datetime.now(TZ_TAIPEI)
 with CACHE_LOCK:
  cached=CACHE.get(code)
  if cached and time.time()-cached['at']<CACHE_SECONDS:
   return dict(cached['value'],cache='hit')
 today=now.date();rows={};failed_months=[]
 for k in range(5):
  m=today.year*12+today.month-1-k;y,mm=divmod(m,12);mm+=1
  url=f'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={y}{mm:02d}01&stockNo={code}&response=json'
  req=Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'})
  data=None
  for attempt in range(3):
   try:
    with urlopen(req,timeout=12) as res:data=json.load(res)
    break
   except (URLError,HTTPError,TimeoutError,ValueError) as exc:
    if attempt==2:failed_months.append(f'{y}-{mm:02d}: {type(exc).__name__}')
    else:time.sleep(0.35*(attempt+1))
  if data is None:continue
  if data.get('stat')!='OK':continue
  for r in data.get('data',[]):
   try:
    yy,mo,dd=map(int,r[0].split('/'));dt=f'{yy+1911:04d}-{mo:02d}-{dd:02d}'
    rows[dt]={'date':dt,'close':float(r[6].replace(',','')),'volume':float(r[1].replace(',',''))}
   except (ValueError,IndexError,TypeError):continue
 a=[rows[x] for x in sorted(rows)]
 if len(a)<35:raise ValueError(f'無法取得足夠的 TWSE 上市日線；可能為上櫃股票、代碼無效或官方資料暫時無法取得。歷史資料不足（{len(a)}筆），下載失敗月份：{", ".join(failed_months) or "無"}')
 c=[r['close'] for r in a];v=[r['volume'] for r in a]
 ma5=sum(c[-5:])/5;ma20=sum(c[-20:])/20;old20=sum(c[-21:-1])/20
 dif=[x-y for x,y in zip(ema(c,12),ema(c,26))];sig=ema(dif,9)
 r5=rsi(c,5);r10=rsi(c,10);vr=v[-1]/(sum(v[-21:-1])/20) if sum(v[-21:-1]) else 0
 score=50+(15 if c[-1]>ma20 and ma20>old20 else -15)+(10 if ma5>ma20 else -8)+(10 if dif[-1]>sig[-1] else -10)+(8 if vr>1.2 else 0)
 tags=[]
 if c[-1]>ma20 and ma20>old20:tags.append('20MA上升')
 if ma5>ma20:tags.append('5MA>20MA')
 if r5>90:tags.append('RSI5過熱')
 if r10>=90:tags.append('RSI10嚴重過熱')
 if vr>1.2:tags.append('量能放大')
 result={'code':code,'name':NAMES.get(code,code),'date':a[-1]['date'],'close':c[-1],'change':round((c[-1]/c[-2]-1)*100,2),'ma5':round(ma5,2),'ma20':round(ma20,2),'rsi5':r5,'rsi10':r10,'dif':round(dif[-1],3),'macd_hist':round(dif[-1]-sig[-1],3),'volume_ratio':round(vr,2),'score':max(0,min(100,score)),'tags':tags,'series':c[-30:],'data_source':'TWSE STOCK_DAY','market':'TWSE','fetched_at':now.isoformat(),'cache':'miss','history_days':len(a),'partial_month_errors':failed_months,'trend_score':max(0,min(100,50+(25 if c[-1]>ma20 else -25)+(25 if ma5>ma20 else -25))),'momentum_score':max(0,min(100,50+(25 if dif[-1]>sig[-1] else -25)+(15 if vr>1.2 else 0))),'risk_level':('高' if r5>90 or r10>=90 or abs((c[-1]/ma20-1)*100)>20 else '中' if r5>80 or vr>3 else '一般'),'support20':round(min(c[-20:]),2),'resistance20':round(max(c[-20:]),2)}
 result.update(signal_metrics(c,v,ma5,ma20,r5,r10,vr,dif[-1],sig[-1]))
 with CACHE_LOCK:CACHE[code]={'at':time.time(),'value':result}
 return result
class H(SimpleHTTPRequestHandler):
 def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT),**kwargs)
 def do_GET(self):
  p=urlparse(self.path)
  if p.path=='/health':self.send_json({'ok':True,'version':'4.4','server_time':datetime.now(TZ_TAIPEI).isoformat()});return
  if p.path=='/api/catalog':self.send_json({'codes':NAMES,'version':'4.4','coverage':'部分上市股票'});return
  if p.path=='/api/stocks':
   code=parse_qs(p.query).get('code',[''])[0]
   if not (len(code)==4 and code.isascii() and code.isdigit()):self.send_json({'error':'請輸入4位數上市股票代碼','code':code},400);return
   try:self.send_json(get(code))
   except Exception as e:self.send_json({'error':str(e),'code':code},502)
   return
  return super().do_GET()
 def end_headers(self):
  if self.path.split('?')[0] in ('/','/index.html'):
   self.send_header('Cache-Control','no-store, no-cache, must-revalidate, max-age=0')
   self.send_header('Pragma','no-cache')
   self.send_header('Expires','0')
  super().end_headers()
 def send_json(self,data,status=200):
  body=json.dumps(data,ensure_ascii=False).encode()
  self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
if __name__=='__main__':ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT',8765))),H).serve_forever()
