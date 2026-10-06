import asyncio
import unittest

from unittest.mock import patch

from fastapi import HTTPException

from main import GenerateRequest, generate
from solver import SettingsValidationError, validate_settings


class SolverSettingsValidationTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "day_leader_count": 1,
            "night_leader_count": 1,
            "night_eligible_count": 2,
            "max_night_shifts": 5,
            "day_required_count": 1,
            "days_off_count": 9,
        }

    def test_rejects_invalid_setting_boundaries_and_relations(self):
        invalid_values = {
            "day_leader_count": 0,
            "night_leader_count": 0,
            "night_eligible_count": 1,
            "max_night_shifts": 0,
            "day_required_count": 0,
            "days_off_count": 32,
        }
        for key, value in invalid_values.items():
            with self.subTest(key=key):
                settings = {**self.settings, key: value}
                with self.assertRaisesRegex(SettingsValidationError, key):
                    validate_settings(settings, staff_count=2, day_count=31)

        settings = {**self.settings, "night_leader_count": 3, "night_eligible_count": 2}
        with self.assertRaisesRegex(SettingsValidationError, "night_leader_count"):
            validate_settings(settings, staff_count=3, day_count=31)

        settings = {**self.settings, "day_required_count": 3}
        with self.assertRaisesRegex(SettingsValidationError, "day_required_count"):
            validate_settings(settings, staff_count=2, day_count=31)

        settings = {**self.settings, "days_off_count": -1}
        with self.assertRaisesRegex(SettingsValidationError, "days_off_count"):
            validate_settings(settings, staff_count=2, day_count=31)

    def test_candidate_counts_are_clamped_to_staff_count(self):
        settings = {
            **self.settings,
            "day_leader_count": 5,
            "night_leader_count": 3,
            "night_eligible_count": 5,
        }
        validated = validate_settings(settings, staff_count=3, day_count=31)
        self.assertEqual(validated["day_leader_count"], 3)
        self.assertEqual(validated["night_leader_count"], 3)
        self.assertEqual(validated["night_eligible_count"], 3)

    def test_api_returns_a_specific_setting_error_before_solving(self):
        request = GenerateRequest(
            staff_ids=["001", "002"],
            staff_floors=[3, 3],
            dates=list(range(1, 32)),
            schedule=[[""] * 31, [""] * 31],
            settings={
                **self.settings,
                "year": 2026,
                "month": 9,
                "day_leader_count": 0,
            },
        )

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(generate(request))

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("day_leader_count", raised.exception.detail)

    def _request(self, **overrides):
        return GenerateRequest(
            staff_ids=["001", "002"],
            staff_floors=[3, 3],
            dates=list(range(1, 32)),
            schedule=[[""] * 31, [""] * 31],
            settings={**self.settings, "year": 2026, "month": 9, **overrides},
        )

    def test_api_returns_400_for_non_numeric_year(self):
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(generate(self._request(year="abc")))

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("設定エラー", raised.exception.detail)

    def test_api_returns_500_when_solver_raises_plain_value_error(self):
        with patch("main.generate_shift", side_effect=ValueError("internal bug")):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(generate(self._request()))

        self.assertEqual(raised.exception.status_code, 500)


if __name__ == "__main__":
    unittest.main()
