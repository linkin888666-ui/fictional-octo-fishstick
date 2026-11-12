import unittest
from unittest.mock import patch
import server

class IndicatorTests(unittest.TestCase):
    def test_ema_constant(self):
        self.assertEqual(server.ema([10.0]*40, 12)[-1], 10.0)
    def test_rsi_rising(self):
        self.assertEqual(server.rsi(list(range(1, 41)), 5), 100)
    def test_rsi_flat(self):
        self.assertEqual(server.rsi([10.0]*40, 10), 50)
    def test_rsi_falling(self):
        self.assertEqual(server.rsi(list(range(40, 0, -1)), 10), 0)
    def test_stock_whitelist(self):
        self.assertIn('1802', server.NAMES)
        self.assertNotIn('9999', server.NAMES)
    def test_breakout_signal(self):
        close=[100.0]*20+[110.0]
        volume=[100.0]*20+[250.0]
        x=server.signal_metrics(close,volume,105,100,75,70,2.5,1,0)
        self.assertTrue(x['breakout20'])
        self.assertFalse(x['distribution_warning'])
    def test_distribution_signal(self):
        close=[100.0]*19+[105.0,90.0]
        volume=[100.0]*20+[250.0]
        x=server.signal_metrics(close,volume,98,100,40,45,2.5,-1,0)
        self.assertTrue(x['distribution_warning'])
        self.assertFalse(x['breakout20'])
    def test_health_endpoint_is_present(self):
        self.assertTrue(hasattr(server, 'H'))

if __name__ == '__main__':
    unittest.main()
