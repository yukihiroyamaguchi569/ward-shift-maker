import unittest
from unittest.mock import patch

from ortools.sat.python import cp_model

from solver import _solve_time_limit_seconds, generate_shift


class _StopSolve(Exception):
    pass


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


class GenerateShiftTimeLimitTests(unittest.TestCase):
    def test_generate_shift_passes_env_limit_to_cp_sat(self):
        recorded = []

        class RecordingSolver(cp_model.CpSolver):
            def Solve(self, model, *args, **kwargs):
                recorded.append(self.parameters.max_time_in_seconds)
                raise _StopSolve  # 実際には探索を回さない

        settings = {
            "day_leader_count": 10,
            "night_leader_count": 8,
            "night_eligible_count": 17,
            "max_night_shifts": 5,
        }
        ids = [str(i + 1) for i in range(19)]
        schedule = [[""] * 30 for _ in ids]
        with patch.dict("os.environ", {"SOLVER_TIME_LIMIT_SECONDS": "7"}), patch(
            "solver.cp_model.CpSolver", RecordingSolver
        ):
            with self.assertRaises(_StopSolve):
                generate_shift(ids, 2026, 9, schedule, settings)
        self.assertEqual(recorded, [7])
