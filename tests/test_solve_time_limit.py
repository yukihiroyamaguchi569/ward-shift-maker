import unittest
from unittest.mock import patch

from solver import _solve_time_limit_seconds


class SolveTimeLimitTests(unittest.TestCase):
    def test_unset_uses_default(self):
        with patch.dict("os.environ", {}, clear=False) as env:
            env.pop("SOLVER_TIME_LIMIT_SECONDS", None)
            self.assertEqual(_solve_time_limit_seconds(), 30)

    def test_numeric_value_is_used(self):
        with patch.dict("os.environ", {"SOLVER_TIME_LIMIT_SECONDS": "10"}):
            self.assertEqual(_solve_time_limit_seconds(), 10)

    def test_invalid_values_fall_back_to_default(self):
        for value in ["abc", "", "0", "-5", "nan", "inf"]:
            with self.subTest(value=value):
                with patch.dict("os.environ", {"SOLVER_TIME_LIMIT_SECONDS": value}):
                    self.assertEqual(_solve_time_limit_seconds(), 30)
