"""Read-only deployment smoke test. Use --live to fetch actual exchange history."""
import argparse
import json
from urllib.request import urlopen

parser = argparse.ArgumentParser()
parser.add_argument('--base-url', default='http://127.0.0.1:8765')
parser.add_argument('--live', action='store_true')
args = parser.parse_args()
base = args.base_url.rstrip('/')

def read(path):
    with urlopen(base + path, timeout=90) as response:
        return json.load(response)

health = read('/health')
assert health['ok'] and health['version'] == '5.0.0', health
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
