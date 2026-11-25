"""Read-only deployment smoke test. Use --live to fetch actual exchange history."""
import argparse
import json
import time
from urllib.request import urlopen

parser = argparse.ArgumentParser()
parser.add_argument('--base-url', default='http://127.0.0.1:8765')
parser.add_argument('--live', action='store_true')
parser.add_argument('--live-burst', action='store_true')
args = parser.parse_args()
base = args.base_url.rstrip('/')

def read(path):
    with urlopen(base + path, timeout=90) as response:
        return json.load(response)

health = read('/health')
assert health['ok'] and health['version'] == '5.1.0', health
catalog = read('/api/catalog')
assert catalog['stocks']['1815']['market'] == 'TPEx'
assert len(catalog['stocks']) > 1500
print(json.dumps({'health':health, 'catalog_companies':len(catalog['stocks'])}, ensure_ascii=False))
if args.live:
    for code, market in [('2330','TWSE'),('1815','TPEx'),('5475','TPEx'),('6456','TWSE')]:
        quote = read('/api/stocks?code=' + code)
        assert quote['market'] == market and quote['close'] > 0 and quote['history_days'] >= 35, quote
        assert not quote['partial_month_errors'], quote['partial_month_errors']
        print(json.dumps({key:quote[key] for key in ['code','name','market','date','close','ma5','ma20','rsi5','rsi10','history_days']},ensure_ascii=False),flush=True)

if args.live_burst:
    deadline = time.monotonic() + 150
    while True:
        report = read('/api/burst-radar')
        snapshot = report['snapshot']
        if snapshot and set(snapshot['markets']) == {'TWSE', 'TPEx'}:
            assert len(snapshot['rows']) > 1000, snapshot['scanned']
            print(json.dumps({'date': snapshot['date'], 'scanned': snapshot['scanned']}, ensure_ascii=False))
            break
        if not report['loading'] or time.monotonic() >= deadline:
            raise AssertionError({key: report[key] for key in ('loading', 'target_date', 'unavailable_markets')})
        time.sleep(3)
