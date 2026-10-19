import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from calculator import add, div, mul, sub  # noqa: E402


class TestCalculator(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)

    def test_sub(self):
        self.assertEqual(sub(5, 3), 2)

    def test_mul(self):
        self.assertEqual(mul(4, 3), 12)

    def test_div(self):
        self.assertEqual(div(10, 2), 5)
        with self.assertRaises(ZeroDivisionError):
            div(1, 0)


if __name__ == "__main__":
    unittest.main()
