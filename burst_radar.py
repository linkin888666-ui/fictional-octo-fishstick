"""Build a post-close stock ranking from official market-wide daily reports."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from functools import lru_cache
import math
import re
import threading
import time
from urllib.parse import urlencode

MARKETS = ('TWSE', 'TPEx')
LOOKBACK = 20
BURST_RATIO = 2
SOURCES = {
    'TWSE': 'https://www.twse.com.tw/zh/trading/historical/mi-index.html',
    'TPEx': 'https://www.tpex.org.tw/zh-tw/mainboard/trading/info/pricing.html',
}
FIELD_NAMES = {
    'code': ('證券代號', '股票代號', '代號'),
    'close': ('收盤價', '收盤'),
    'high': ('最高價', '最高'),
    'low': ('最低價', '最低'),
    'amount': ('成交金額', '成交金額(元)', '成交金額（元）'),
}


def parse_daily(payload, day, market, catalog):
    status = str(payload.get('stat', '')).strip()
    if status and status.upper() not in ('OK', 'SUCCESS'):
        if any(word in status for word in ('沒有符合', '查無資料', '無交易資料')):
            return {}
        raise ValueError('官方報表狀態異常')
    reported = str(payload.get('date') or '')
    if reported:
        digits = re.sub(r'[^0-9]', '', reported)
        if digits not in (day.strftime('%Y%m%d'), f'{day.year - 1911}{day:%m%d}'):
            raise ValueError('官方報表日期不符')
    tables = payload.get('tables', [])
    if not tables:
        tables = [{'fields': payload[key], 'data': payload.get('data' + key[6:], [])}
                  for key in payload if re.fullmatch(r'fields\d*', key)]
    if not tables:
        if payload.get('tables') == [] and (reported or status.upper() == 'OK'):
            return {}
        raise ValueError('官方報表缺少行情欄位')
    found = False
    quotes = {}
    for table in tables:
        fields = [re.sub(r'\s+', '', str(value)) for value in table.get('fields', [])]
        indices = {key: next((fields.index(name) for name in names if name in fields), None)
                   for key, names in FIELD_NAMES.items()}
        if None in indices.values():
            continue
        found = True
        for row in table.get('data', []):
            try:
                code = str(row[indices['code']]).strip()
                if catalog.get(code, {}).get('market') != market:
                    continue
                close, high, low, amount = (
                    float(str(row[indices[key]]).replace(',', ''))
                    for key in ('close', 'high', 'low', 'amount')
                )
                if all(math.isfinite(x) for x in (close, high, low, amount)) and 0 < low <= close <= high and amount > 0:
                    quotes.setdefault(code, (close, high, low, amount))
            except (IndexError, ValueError, TypeError):
                continue
    if not found and any(table.get('data') for table in tables):
        raise ValueError('官方報表欄位異常')
    return quotes


def rank_rows(sessions, market, catalog):
    previous = defaultdict(list)
    for session in sessions[1:]:
        for code, row in session.items():
            previous[code].append(row)
    ranked = []
    for code, (close, high, low, amount) in sessions[0].items():
        history = previous[code]
        if len(history) != LOOKBACK:
            continue
        prior_closes = [row[0] for row in history]
        ma5 = (close + sum(prior_closes[:4])) / 5
        ma20 = (close + sum(prior_closes[:19])) / 20
        old20 = sum(prior_closes) / 20
        ratio = amount / (sum(row[3] for row in history) / LOOKBACK)
        close_position = (close - low) / (high - low) if high > low else None
        signal = 'neutral'
        if ratio >= BURST_RATIO and close_position is not None:
            if close_position >= 0.75:
                signal = 'strong'
            elif close_position <= 0.25:
                signal = 'weak'
        ranked.append({
            'code': code, 'name': catalog[code]['name'], 'market': market,
            'close': close, 'amount': amount, 'amount_ratio': ratio,
            'close_position': close_position, 'signal': signal,
            'ma5': round(ma5, 2), 'ma20': round(ma20, 2),
            'trend_pass': close > ma20 and ma5 > ma20 and ma20 > old20,
        })
    return ranked


class BurstRadar:
    def __init__(self, fetch, catalog):
        self.fetch = fetch
        self.catalog = catalog
        self.lock = threading.Lock()
        self.running = False
        self.last_attempt = 0
        self.last_target = None
        self.snapshot = None
        self.errors = []

    @lru_cache(maxsize=128)
    def past_report(self, day, market):
        rows = self.report(day, market)
        if not rows:
            # Empty responses can be transient. Cache published rows only.
            raise NoSession
        return rows

    def report(self, day, market):
        if market == 'TWSE':
            query = urlencode({'date': day.strftime('%Y%m%d'), 'type': 'ALLBUT0999', 'response': 'json'})
            try:
                payload = self.fetch('https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?' + query)
            except Exception:
                payload = self.fetch('https://www.twse.com.tw/exchangeReport/MI_INDEX?' + query)
        else:
            query = urlencode({'date': day.strftime('%Y/%m/%d'), 'type': 'DailyClose', 'response': 'json'})
            payload = self.fetch('https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?' + query)
        return parse_daily(payload, day, market, self.catalog)

    def scan_market(self, target, market):
        sessions = []
        latest = None
        for offset in range(55):
            day = target - timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            try:
                rows = self.report(day, market) if offset == 0 else self.past_report(day, market)
            except NoSession:
                continue
            if not rows:
                continue
            latest = latest or day
            sessions.append(rows)
            if len(sessions) == LOOKBACK + 1:
                return latest.isoformat(), rank_rows(sessions, market, self.catalog)
        raise ValueError('交易日歷史資料不足')

    def refresh(self, target):
        results = {}
        errors = []
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                tasks = {market: executor.submit(self.scan_market, target, market) for market in MARKETS}
                for market, task in tasks.items():
                    try:
                        results[market] = task.result()
                    except Exception as exc:
                        print(f'Burst radar {market}: {type(exc).__name__}: {exc}', flush=True)
                        errors.append(market)
            if results:
                latest = max(value[0] for value in results.values())
                covered = {market: value[1] for market, value in results.items() if value[0] == latest}
                errors.extend(market for market in results if market not in covered)
                rows = sorted((row for entries in covered.values() for row in entries),
                              key=lambda row: (-row['amount_ratio'], -row['amount'], row['code']))
                snapshot = {'date': latest, 'markets': list(covered),
                            'scanned': {market: len(entries) for market, entries in covered.items()},
                            'rows': rows, 'sources': SOURCES}
                with self.lock:
                    current = self.snapshot
                    if (current is None or latest > current['date'] or
                            (latest == current['date'] and len(covered) >= len(current['markets']))):
                        self.snapshot = snapshot
        finally:
            with self.lock:
                self.errors = errors
                self.last_attempt = time.monotonic()
                self.running = False

    def get(self, now):
        target = now.date() if now.hour >= 15 else now.date() - timedelta(days=1)
        while target.weekday() >= 5:
            target -= timedelta(days=1)
        with self.lock:
            interval = 300 if self.errors else 900
            if not self.running and (target != self.last_target or time.monotonic() - self.last_attempt >= interval):
                self.running = True
                self.last_target = target
                threading.Thread(target=self.refresh, args=(target,), daemon=True).start()
            return {'loading': self.running, 'target_date': target.isoformat(),
                    'unavailable_markets': self.errors, 'snapshot': self.snapshot}


class NoSession(Exception):
    pass
