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
    def test_health_endpoint_is_present(self):
        self.assertTrue(hasattr(server, 'H'))

if __name__ == '__main__':
    unittest.main()
