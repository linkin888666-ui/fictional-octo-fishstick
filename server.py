from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from urllib.request import Request,urlopen
from urllib.parse import urlparse,parse_qs
from datetime import date
from pathlib import Path
import json,os
ROOT=Path(__file__).resolve().parent
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
def get(code):
 today=date.today();rows={}
 for k in range(5):
  m=today.year*12+today.month-1-k;y,mm=divmod(m,12);mm+=1
  url=f'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={y}{mm:02d}01&stockNo={code}&response=json'
  req=Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'})
  with urlopen(req,timeout=15) as res: data=json.load(res)
  if data.get('stat')!='OK':continue
  for r in data.get('data',[]):
   try:
    yy,mo,dd=map(int,r[0].split('/'));dt=f'{yy+1911:04d}-{mo:02d}-{dd:02d}'
    rows[dt]={'date':dt,'close':float(r[6].replace(',','')),'volume':float(r[1].replace(',',''))}
   except (ValueError,IndexError,TypeError):continue
 a=[rows[x] for x in sorted(rows)]
 if len(a)<35:raise ValueError('歷史資料不足，無法計算')
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
 return {'code':code,'name':NAMES[code],'date':a[-1]['date'],'close':c[-1],'change':round((c[-1]/c[-2]-1)*100,2),'ma5':round(ma5,2),'ma20':round(ma20,2),'rsi5':r5,'rsi10':r10,'dif':round(dif[-1],3),'macd_hist':round(dif[-1]-sig[-1],3),'volume_ratio':round(vr,2),'score':max(0,min(100,score)),'tags':tags,'series':c[-30:]}
class H(SimpleHTTPRequestHandler):
 def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT),**kwargs)
 def do_GET(self):
  p=urlparse(self.path)
  if p.path=='/health':self.send_json({'ok':True});return
  if p.path=='/api/stocks':
   code=parse_qs(p.query).get('code',[''])[0]
   if code not in NAMES:self.send_json({'error':'不支援此代碼，目前僅部分上市股票'},400);return
   try:self.send_json(get(code))
   except Exception as e:self.send_json({'error':str(e),'code':code},502)
   return
  return super().do_GET()
 def send_json(self,data,status=200):
  body=json.dumps(data,ensure_ascii=False).encode()
  self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
if __name__=='__main__':ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT',8765))),H).serve_forever()
