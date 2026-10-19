import time
import unittest


class TestSlow(unittest.TestCase):
    def test_slow_20s(self):
        time.sleep(20)
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
