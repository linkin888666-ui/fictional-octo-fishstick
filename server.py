"""BRUCE: official exchange daily data, deterministic indicators, no invented quotes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone, timedelta
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode
from urllib.request import Request, urlopen
import json
import math
import os
import re
import threading
import time

ROOT = Path(__file__).resolve().parent
VERSION = '5.0.0'
CACHE = {}
CACHE_LOCK = threading.Lock()
CACHE_SECONDS = 900
TZ_TAIPEI = timezone(timedelta(hours=8))
UPSTREAM_LIMIT = threading.BoundedSemaphore(4)
STOCK_LOCKS = [threading.Lock() for _ in range(64)]
try:
    CATALOG = json.loads((ROOT / 'catalog.json').read_text())
except (OSError, ValueError):
    CATALOG = {'stocks': {}, 'fetched_at': None, 'sources': {}}
NAMES = {code: item['name'] for code, item in CATALOG['stocks'].items()}

class DataUnavailable(ValueError):
    pass


def valid_code(code):
    return bool(re.fullmatch(r'[0-9]{4}', code))


def ema(a, n):
    out = []
    v = a[0]
    k = 2 / (n + 1)
    for x in a:
        v += (x - v) * k
        out.append(v)
    return out


def rsi(a, n):
    """Wilder RSI, seed with the mean of the first n changes."""
    if len(a) <= n:
        return None
    changes = [a[i] - a[i - 1] for i in range(1, len(a))]
    gain = sum(max(x, 0) for x in changes[:n]) / n
    loss = sum(max(-x, 0) for x in changes[:n]) / n
    for x in changes[n:]:
        gain = (gain * (n - 1) + max(x, 0)) / n
        loss = (loss * (n - 1) + max(-x, 0)) / n
    return round(100 - 100 / (1 + gain / loss), 2) if loss else (100 if gain else 50)


def signal_metrics(close, volume, ma5, ma20, r5, r10, vr, dif, sig):
    # These levels use closing prices, not intraday highs/lows.
    recent_high = max(close[-21:-1])
    recent_low = min(close[-21:-1])
    change = (close[-1] / close[-2] - 1) * 100
    breakout = close[-1] > recent_high and vr >= 1.5
    distribution = change < 0 and vr >= 2 and close[-1] < ma5
    overheating = r5 > 90 or r10 >= 90
    alerts = []
    if breakout:
        alerts.append('突破前20日收盤高點且放量')
    if distribution:
        alerts.append('放量下跌警示')
    if overheating:
        alerts.append('RSI過熱警示')
    if close[-1] < ma20:
        alerts.append('跌破20MA')
    return {'alerts': alerts, 'breakout20': breakout,
            'distribution_warning': distribution, 'overheating': overheating,
            'reference_high20': round(recent_high, 2), 'reference_low20': round(recent_low, 2),
            'signal_note': '日線規則；20日突破以收盤價計算，不代表盤中訊號或主力行為'}


def request_json(url):
    with UPSTREAM_LIMIT:
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
        with urlopen(req, timeout=10) as response:
            return json.load(response)


def month_url(code, year, month, market):
    if market == 'TPEx':
        # Modern TPEx API requires Gregorian dates; ROC dates return 參數輸入錯誤.
        return 'https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock?' + urlencode(
            {'date': f'{year}/{month:02d}/01', 'code': code, 'response': 'json'})
    return 'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?' + urlencode(
        {'date': f'{year}{month:02d}01', 'stockNo': code, 'response': 'json'})


def parse_month(payload, year, month, market, today=None):
    """Reject wrong-month data, invalid prices, and non-trading rows. Volume is shares."""
    if not isinstance(payload, dict):
        raise DataUnavailable('官方資料不是預期的 JSON 物件')
    status = str(payload.get('stat', '')).lower()
    if status and status != 'ok':
        if '參數' in status or 'error' in status:
            raise DataUnavailable('官方資料參數或格式錯誤：' + status[:100])
        return {}
    blocks = payload.get('tables', []) if market == 'TPEx' else [payload]
    result = {}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        for row in block.get('data', []):
            try:
                yy, mm, dd = map(int, str(row[0]).replace('*', '').replace('＊', '').strip().split('/'))
                if yy < 1911:
                    yy += 1911
                dt = date(yy, mm, dd)
                close = float(str(row[6]).replace(',', ''))
                volume = float(str(row[1]).replace(',', '')) * (1000 if market == 'TPEx' else 1)
                if (yy, mm) != (year, month) or (today and dt > today):
                    continue
                if not math.isfinite(close) or close <= 0 or not math.isfinite(volume) or volume <= 0:
                    continue
                result[dt.isoformat()] = {'date': dt.isoformat(), 'close': close, 'volume': volume}
            except (IndexError, ValueError, TypeError):
                continue
    return result


def fetch_month(code, year, month, market):
    url = month_url(code, year, month, market)
    try:
        payload = request_json(url)
    except Exception:
        # One bounded retry handles transient timeouts. For TWSE, use the
        # official legacy report to escape repeated rwd redirects.
        time.sleep(0.2)
        fallback = ('https://www.twse.com.tw/exchangeReport/STOCK_DAY?' + urlencode(
            {'response': 'json', 'date': f'{year}{month:02d}01', 'stockNo': code})) if market == 'TWSE' else url
        payload = request_json(fallback)
    rows = parse_month(payload, year, month, market, datetime.now(TZ_TAIPEI).date())
    name = payload.get('name', '') if isinstance(payload, dict) else ''
    if not name and isinstance(payload, dict):
        match = re.search(r'\b' + re.escape(code) + r'\s+(.+?)\s+各日', payload.get('title', ''))
        name = match.group(1).strip() if match else ''
    return rows, name


def parse_otc_month(code, y, mm):
    return fetch_month(code, y, mm, 'TPEx')[0]


def build_result(code, rows, market, name, now, errors):
    a = [rows[x] for x in sorted(rows)]
    if len(a) < 35:
        raise DataUnavailable(f'{code} 官方有效日線僅 {len(a)} 筆，至少需要35筆；可能是新上市、代碼無效或官方服務異常。')
    c, v = [r['close'] for r in a], [r['volume'] for r in a]
    ma5, ma20, old20 = sum(c[-5:]) / 5, sum(c[-20:]) / 20, sum(c[-21:-1]) / 20
    dif = [x - y for x, y in zip(ema(c, 12), ema(c, 26))]
    sig = ema(dif, 9)
    r5, r10 = rsi(c, 5), rsi(c, 10)
    vr = v[-1] / (sum(v[-21:-1]) / 20)
    score = 50 + (15 if c[-1] > ma20 and ma20 > old20 else -15) + (10 if ma5 > ma20 else -8) + (10 if dif[-1] > sig[-1] else -10) + (8 if vr > 1.2 else 0)
    tags = []
    if c[-1] > ma20 and ma20 > old20:
        tags.append('20MA上升')
    if ma5 > ma20:
        tags.append('5MA>20MA')
    if r5 > 90:
        tags.append('RSI5過熱')
    if r10 >= 90:
        tags.append('RSI10過熱')
    if vr > 1.2:
        tags.append('量能放大')
    age = (now.date() - date.fromisoformat(a[-1]['date'])).days
    warnings = []
    if errors:
        warnings.append('部分月份下載失敗，指標可能受歷史缺漏影響')
    if age > 5:
        warnings.append('最新日線已超過5個日曆日；可能停牌、長假或資料尚未更新')
    result = {'version': VERSION, 'code': code, 'name': name or NAMES.get(code, code),
              'date': a[-1]['date'], 'close': c[-1], 'change': round((c[-1] / c[-2] - 1) * 100, 2),
              'ma5': round(ma5, 2), 'ma20': round(ma20, 2), 'ma20_previous': round(old20, 2),
              'trend_pass': c[-1] > ma20 and ma20 > old20 and ma5 > ma20,
              'rsi5': r5, 'rsi10': r10, 'rsi10_overheat_days': 0,
              'dif': round(dif[-1], 3), 'macd_hist': round(dif[-1] - sig[-1], 3),
              'volume_ratio': round(vr, 2), 'volume_shares': v[-1], 'score': max(0, min(100, score)),
              'tags': tags, 'series': c[-30:], 'series_dates': [r['date'] for r in a[-30:]],
              'data_source': market + ' official daily', 'market': market,
              'source_url': month_url(code, int(a[-1]['date'][:4]), int(a[-1]['date'][5:7]), market),
              'fetched_at': now.isoformat(), 'cache': 'miss', 'history_days': len(a),
              'partial_month_errors': errors, 'data_warnings': warnings, 'data_age_days': age,
              'trend_score': max(0, min(100, 50 + (25 if c[-1] > ma20 else -25) + (25 if ma5 > ma20 else -25))),
              'momentum_score': max(0, min(100, 50 + (25 if dif[-1] > sig[-1] else -25) + (15 if vr > 1.2 else 0))),
              'risk_level': '高' if r5 > 90 or r10 >= 90 or abs((c[-1] / ma20 - 1) * 100) > 20 else '中' if r5 > 80 or vr > 3 else '一般',
              'support20': round(min(c[-20:]), 2), 'resistance20': round(max(c[-20:]), 2)}
    for end in range(len(c), 10, -1):
        if rsi(c[:end], 10) < 90:
            break
        result['rsi10_overheat_days'] += 1
    result.update(signal_metrics(c, v, ma5, ma20, r5, r10, vr, dif[-1], sig[-1]))
    return result


def get(code, market='auto', refresh=False):
    if not valid_code(code):
        raise ValueError('請輸入4位上市／上櫃股票代碼')
    if market not in ('auto', 'twse', 'tpex'):
        raise ValueError('market 只支援 auto、twse、tpex')
    key = code + ':' + market
    # Bounded lock stripes deduplicate simultaneous requests without unbounded lock storage.
    with STOCK_LOCKS[int(code) % len(STOCK_LOCKS)]:
        with CACHE_LOCK:
            cached = CACHE.get(key)
            if not refresh and cached and time.time() - cached['at'] < CACHE_SECONDS:
                return dict(cached['value'], cache='hit')
        now = datetime.now(TZ_TAIPEI)
        months = []
        for k in range(5):
            y, mm = divmod(now.year * 12 + now.month - 1 - k, 12)
            months.append((y, mm + 1))
        known = CATALOG['stocks'].get(code, {}).get('market')
        markets = [market.upper() if market == 'twse' else 'TPEx'] if market != 'auto' else ([known] if known else ['TWSE', 'TPEx'])
        errors = []
        for source in markets:
            rows, name, source_errors = {}, '', []
            def job(ym):
                y, mm = ym
                try:
                    records, stock_name = fetch_month(code, y, mm, source)
                    return records, stock_name, None
                except Exception as exc:
                    return {}, '', f'{source} {y}-{mm:02d}: {type(exc).__name__}: {str(exc)[:100]}'
            with ThreadPoolExecutor(max_workers=2) as executor:
                for records, stock_name, error in executor.map(job, months):
                    rows.update(records)
                    name = name or stock_name
                    if error:
                        source_errors.append(error)
            if len(rows) >= 35:
                result = build_result(code, rows, source, name, now, source_errors)
                with CACHE_LOCK:
                    if len(CACHE) >= 512:
                        del CACHE[min(CACHE, key=lambda k: CACHE[k]['at'])]
                    CACHE[key] = {'at': time.time(), 'value': result}
                return result
            errors.extend(source_errors)
        raise DataUnavailable(f'{code} 查無足夠官方日線，請確認代碼或稍後重試。' + (' 來源下載異常：' + '; '.join(errors[:2]) if errors else ' 新上市股票可能尚未滿35個交易日。'))


class H(SimpleHTTPRequestHandler):
    def do_GET(self):
        p = urlparse(self.path)
        query = parse_qs(p.query)
        if p.path == '/health':
            self.send_json({'ok': True, 'version': VERSION,
                            'revision': os.environ.get('RENDER_GIT_COMMIT', 'local'),
                            'server_time': datetime.now(TZ_TAIPEI).isoformat()})
            return
        if p.path == '/api/catalog':
            self.send_json(dict(CATALOG, version=VERSION, codes=NAMES, coverage='上市／上櫃4位公司代碼；不含ETF、權證與興櫃'))
            return
        if p.path == '/api/stocks':
            code = query.get('code', [''])[0]
            market = query.get('market', ['auto'])[0]
            if not valid_code(code) or market not in ('auto', 'twse', 'tpex'):
                self.send_json({'error': '請輸入4位股票代碼；market 只支援 auto、twse、tpex', 'code': code}, 400)
                return
            try:
                self.send_json(get(code, market, query.get('refresh', ['0'])[0] == '1'))
            except DataUnavailable as exc:
                self.send_json({'error': str(exc), 'code': code}, 502)
            except Exception as exc:
                self.log_error('quote failure %s: %s', code, exc)
                self.send_json({'error': '官方行情暫時無法取得，請稍後重試', 'code': code}, 502)
            return
        # Serve only public assets. Never expose Python source, .git, or deployment config.
        assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/index.html': ('index.html', 'text/html; charset=utf-8'),
                  '/app.js': ('app.js', 'text/javascript; charset=utf-8')}
        if p.path not in assets:
            self.send_json({'error': '找不到此資源'}, 404)
            return
        filename, content_type = assets[p.path]
        self.send_bytes((ROOT / filename).read_bytes(), content_type)

    def send_bytes(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_json(self, data, status=200):
        self.send_bytes(json.dumps(data, ensure_ascii=False, allow_nan=False).encode(),
                        'application/json; charset=utf-8', status)

    def do_HEAD(self):
        if urlparse(self.path).path not in ('/', '/index.html', '/app.js', '/health'):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT', 8765))), H).serve_forever()
