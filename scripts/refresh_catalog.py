"""Refresh the company-name/market snapshot from official exchange OpenAPI feeds."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
import json

SOURCES = {
    'TWSE': 'https://openapi.twse.com.tw/v1/opendata/t187ap03_L',
    'TPEx': 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O',
}

def download(item):
    market, url = item
    with urlopen(Request(url, headers={'User-Agent': 'BRUCE-Stock-Radar/5.0'}), timeout=30) as response:
        records = json.load(response)
    stocks = {}
    for row in records:
        code = row.get('公司代號', row.get('SecuritiesCompanyCode', '')).strip()
        name = row.get('公司簡稱', row.get('CompanyAbbreviation', '')).strip()
        if len(code) == 4 and code.isascii() and code.isdigit() and name:
            stocks[code] = {'name': name, 'market': market}
    if not stocks:
        raise ValueError(f'Empty {market} company catalog; retaining existing snapshot')
    return stocks

if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=2) as executor:
        parts = list(executor.map(download, SOURCES.items()))
    stocks = {code: row for part in parts for code, row in part.items()}
    target = Path(__file__).resolve().parents[1] / 'catalog.json'
    target.write_text(json.dumps({'fetched_at': datetime.now(timezone.utc).isoformat(),
                                 'sources': SOURCES, 'stocks': stocks}, ensure_ascii=False, indent=2) + '\n')
    print(f'Saved {len(stocks)} official company names and markets')
