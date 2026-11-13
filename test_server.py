import json
import threading
import unittest
from datetime import date, datetime, timedelta
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.request import urlopen
from urllib.error import HTTPError
import server


def records(n=80):
    first = date(2026, 7, 1)
    return {(first + timedelta(days=i)).isoformat():
            {'date': (first + timedelta(days=i)).isoformat(), 'close': 100+i, 'volume': 1000+i}
            for i in range(n)}


class IndicatorTests(unittest.TestCase):
    def test_ema_constant(self):
        self.assertEqual(server.ema([10.0]*40, 12)[-1], 10.0)

    def test_rsi_reference(self):
        # Wilder's classic 14-day example, expected first RSI 70.46.
        values = [44.34,44.09,44.15,43.61,44.33,44.83,45.10,45.42,45.84,46.08,45.89,46.03,45.61,46.28,46.28]
        self.assertAlmostEqual(server.rsi(values,14),70.46,places=2)
        self.assertEqual(server.rsi(list(range(40)),5),100)
        self.assertEqual(server.rsi(list(range(40,0,-1)),10),0)
        self.assertEqual(server.rsi([10.]*40,10),50)
        self.assertIsNone(server.rsi([10.]*5,5))

    def test_metrics_and_trend(self):
        rows = records()
        result = server.build_result('2330', rows, 'TWSE', '台積電', datetime(2026,9,20,tzinfo=server.TZ_TAIPEI), [])
        self.assertEqual(result['ma5'], 177)
        self.assertEqual(result['ma20'], 169.5)
        self.assertTrue(result['trend_pass'])
        self.assertEqual(result['rsi10'], 100)
        self.assertEqual(result['rsi10_overheat_days'], 70)
        self.assertEqual(result['volume_shares'],1079)
        self.assertEqual(result['version'], server.VERSION)

    def test_rsi5_boundary_consistent(self):
        args = ([100.]*20+[110.], [100.]*21,105,100)
        result = server.signal_metrics(*args,90,89,1.,1.,0.)
        self.assertFalse(result['overheating'])
        self.assertTrue(server.signal_metrics(*args,90.01,89,1.,1.,0.)['overheating'])

    def test_breakout_and_distribution(self):
        result = server.signal_metrics([100.]*20+[110.],[100.]*21,105,100,75,70,2.5,1,0)
        self.assertTrue(result['breakout20'])
        self.assertFalse(result['distribution_warning'])
        result = server.signal_metrics([100.]*19+[105.,90.],[100.]*21,98,100,40,45,2.5,-1,0)
        self.assertTrue(result['distribution_warning'])

    def test_stale_and_missing_history_warnings(self):
        result = server.build_result('2330',records(),'TWSE','台積電',datetime(2026,11,13,tzinfo=server.TZ_TAIPEI),['failed'])
        self.assertEqual(len(result['data_warnings']),2)
        with self.assertRaises(server.DataUnavailable):
            server.build_result('2330',records(10),'TWSE','台積電',datetime.now(server.TZ_TAIPEI),[])


class SourceTests(unittest.TestCase):
    def setUp(self):
        server.CACHE.clear()

    def test_tpex_gregorian_url(self):
        url = server.month_url('1815',2026,11,'TPEx')
        self.assertIn('date=2026%2F11%2F01',url)
        self.assertNotIn('115',url)
        self.assertIn('code=1815',url)

    def test_twse_redirect_uses_official_fallback(self):
        payload = {'stat':'OK', 'title':'115年11月 6456 GIS-KY 各日成交資訊',
                   'data':[['115/11/02','1,000','1','1','1','1','99.5']]}
        with patch.object(server,'request_json',side_effect=[OSError('redirect'), payload]) as request:
            rows, name = server.fetch_month('6456',2026,11,'TWSE')
        self.assertEqual(name,'GIS-KY')
        self.assertEqual(rows['2026-11-02']['close'],99.5)
        self.assertIn('www.twse.com.tw/exchangeReport/STOCK_DAY',request.call_args_list[1].args[0])

    def test_exchange_parsing_and_volume_units(self):
        rows=[['115/11/02','1,234','9','10','11','9','10.50']]
        tpex=server.parse_month({'stat':'ok','tables':[{'data':rows}]},2026,11,'TPEx')
        twse=server.parse_month({'stat':'OK','data':rows},2026,11,'TWSE')
        self.assertEqual(tpex['2026-11-02']['volume'],1234000)
        self.assertEqual(twse['2026-11-02']['volume'],1234)
        self.assertEqual(tpex['2026-11-02']['close'],10.5)

    def test_invalid_rows_excluded(self):
        rows=[['115/10/01','100','1','1','1','1','5'],['115/11/01','100','1','1','1','1','NaN'],
              ['115/11/03','100','1','1','1','1','0'],['115/11/04','0','1','1','1','1','5'],
              ['115/11/05','100','1','1','1','1','--'],['115/11/30','100','1','1','1','1','5']]
        self.assertEqual(server.parse_month({'data':rows},2026,11,'TWSE',date(2026,11,13)),{})
        with self.assertRaises(server.DataUnavailable):
            server.parse_month({'stat':'參數輸入錯誤'},2026,11,'TPEx')

    def test_tpex_direct_routing_and_cache(self):
        with patch.object(server,'fetch_month',return_value=(records(),'富喬')) as fetch:
            result=server.get('1815')
            self.assertEqual(result['market'],'TPEx')
            self.assertTrue(all(c.args[-1]=='TPEx' for c in fetch.call_args_list))
            self.assertEqual(server.get('1815')['cache'],'hit')
            self.assertEqual(fetch.call_count,5)
            server.get('1815',refresh=True)
            self.assertEqual(fetch.call_count,10)

    def test_explicit_market_never_mixes(self):
        with patch.object(server,'fetch_month',return_value=(records(),'台積電')) as fetch:
            self.assertEqual(server.get('2330','tpex')['market'],'TPEx')
            self.assertTrue(all(c.args[-1]=='TPEx' for c in fetch.call_args_list))

    def test_empty_and_unavailable_are_not_cached(self):
        with patch.object(server,'fetch_month',return_value=({},'')):
            with self.assertRaises(server.DataUnavailable):server.get('9999')
        self.assertEqual(server.CACHE,{})
        with patch.object(server,'fetch_month',side_effect=TimeoutError('timeout')):
            with self.assertRaisesRegex(server.DataUnavailable,'來源下載異常'):server.get('2330')

    def test_catalog_has_both_markets(self):
        self.assertGreater(len(server.CATALOG['stocks']),1500)
        self.assertEqual(server.CATALOG['stocks']['1815']['market'],'TPEx')
        self.assertEqual(server.CATALOG['stocks']['2330']['name'],'台積電')


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http=ThreadingHTTPServer(('127.0.0.1',0),server.H)
        cls.base='http://127.0.0.1:'+str(cls.http.server_address[1])
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.thread.join()

    def read(self,path):
        try:
            with urlopen(self.base+path) as response:return response.status,response.read(),response.headers
        except HTTPError as exc:return exc.code,exc.read(),exc.headers

    def test_health_and_static_versions(self):
        status,body,headers=self.read('/health')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['version'],'5.0.0')
        self.assertIn('no-store',headers['Cache-Control'])
        self.assertIn(b'5.0.0',self.read('/app.js')[1])
        self.assertIn(b'/app.js',self.read('/')[1])

    def test_validation_and_private_files(self):
        for path in ['/api/stocks?code=abc','/api/stocks?code=2330&market=wrong']:
            self.assertEqual(self.read(path)[0],400)
        for path in ['/server.py','/.git/config','/render.yaml','/not-found','/../server.py']:
            self.assertEqual(self.read(path)[0],404)

    def test_quote_and_failure_json(self):
        with patch.object(server,'get',return_value={'code':'1815','market':'TPEx'}):
            self.assertEqual(json.loads(self.read('/api/stocks?code=1815')[1])['market'],'TPEx')
        with patch.object(server,'get',side_effect=server.DataUnavailable('官方來源無法連線')):
            status,body,_=self.read('/api/stocks?code=1815')
            self.assertEqual(status,502)
            self.assertIn('官方來源',json.loads(body)['error'])

if __name__=='__main__':unittest.main()
