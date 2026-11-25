import unittest
from datetime import date, timedelta
from unittest.mock import patch

from burst_radar import BurstRadar, parse_daily, rank_rows


class BurstRadarTests(unittest.TestCase):
    day = date(2026, 11, 25)
    catalog = {
        '2330': {'name': '台積電', 'market': 'TWSE'},
        '1815': {'name': '富喬', 'market': 'TPEx'},
    }

    def test_market_fields_and_amount_use_actual_dollars(self):
        twse = {'date': '20261125', 'stat': 'OK', 'tables': [{
            'fields': ['證券代號', '最高價', '收盤價', '最低價', '成交金額'],
            'data': [['2330', '2,100', '2,060', '2,040', '7,245,000,001'],
                     ['0050', '90', '87', '86', '500000000']],
        }]}
        tpex = {'date': '115/11/25', 'tables': [{
            'fields': ['代號', '名稱', '收盤', '最高', '最低', '成交金額(元)'],
            'data': [['1815', '富喬', '101.5', '102', '100', '700,500,000']],
        }]}
        self.assertEqual(parse_daily(twse, self.day, 'TWSE', self.catalog),
                         {'2330': (2060, 2100, 2040, 7245000001)})
        self.assertEqual(parse_daily(tpex, self.day, 'TPEx', self.catalog),
                         {'1815': (101.5, 102, 100, 700500000)})
        with self.assertRaisesRegex(ValueError, '日期'):
            parse_daily(tpex, date(2026, 11, 24), 'TPEx', self.catalog)

    def test_anchor_math_and_insufficient_history(self):
        history = [{'2330': (120 - i, 120 - i, 120 - i, 10_000)} for i in range(20)]
        row, = rank_rows([{'2330': (124, 125, 121, 20_000)}, *history], 'TWSE', self.catalog)
        self.assertEqual(row['amount_ratio'], 2)
        self.assertEqual(row['close_position'], 0.75)
        self.assertEqual(row['signal'], 'strong')
        self.assertTrue(row['trend_pass'])
        row, = rank_rows([{'2330': (101, 105, 100, 20_001)}, *history], 'TWSE', self.catalog)
        self.assertEqual(row['signal'], 'weak')
        self.assertFalse(row['trend_pass'])
        row, = rank_rows([{'2330': (101, 101, 101, 20_000)}, *history], 'TWSE', self.catalog)
        self.assertIsNone(row['close_position'])
        self.assertEqual(row['signal'], 'neutral')
        self.assertEqual(rank_rows([{'2330': (124, 125, 121, 20_000)}, *history[:-1]],
                                   'TWSE', self.catalog), [])

    def test_reading_does_not_mix_dates_and_newer_partial_result_is_labeled(self):
        scanner = BurstRadar(None, self.catalog)

        def reports(day, market):
            if market == 'TPEx':
                return (day - timedelta(days=1)).isoformat(), []
            return day.isoformat(), []

        with patch.object(scanner, 'scan_market', side_effect=reports):
            scanner.refresh(self.day)
        self.assertEqual(scanner.snapshot['date'], self.day.isoformat())
        self.assertEqual(scanner.snapshot['markets'], ['TWSE'])
        self.assertEqual(scanner.errors, ['TPEx'])


if __name__ == '__main__':
    unittest.main()
