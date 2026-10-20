import asyncio
import unittest

from fastapi import HTTPException

from main import GenerateRequest, check, generate
from solver import (
    SettingsValidationError,
    diagnose_infeasibility,
    generate_shift,
    precheck_schedule,
    validate_settings,
)

YEAR = 2026
MONTH = 11  # 2026年11月は1日が日曜（日曜 = 1, 8, 15, 22, 29日）
STAFF_COUNT = 19
DAY_COUNT = 30
SUNDAY_INDEX = 0  # 1日（日曜）。前日の夜勤明けが無い月初にして人数勘定を単純にする
SETTINGS = {
    "year": YEAR,
    "month": MONTH,
    "day_leader_count": 10,
    "night_leader_count": 8,
    "night_eligible_count": 17,
    "max_night_shifts": 5,
}


def staff_ids():
    return [str(i + 1) for i in range(STAFF_COUNT)]


def tight_sunday_schedule():
    # 1日（日曜）に後ろ13人が公休 → 配置可能 6人 = 日勤4人＋夜勤2人がちょうど
    schedule = [[""] * DAY_COUNT for _ in range(STAFF_COUNT)]
    for s in range(6, STAFF_COUNT):
        schedule[s][SUNDAY_INDEX] = "公休"
    return schedule


def day_shift_count(schedule, d):
    return sum(1 for row in schedule if row[d] in {"日", "7b"})


class SundayDayCountTests(unittest.TestCase):
    def test_sunday_four_passes_precheck_and_generates(self):
        settings = {**SETTINGS, "sunday_day_required_count": 4}
        schedule = tight_sunday_schedule()
        result = precheck_schedule(staff_ids(), YEAR, MONTH, schedule, settings)
        self.assertEqual(result.conflict_warnings, [])

        table, warnings, _ = generate_shift(
            staff_ids(), YEAR, MONTH, schedule, settings
        )
        self.assertFalse(
            any(w.startswith("条件を満たす勤務表が見つかりません") for w in warnings),
            warnings,
        )
        self.assertGreaterEqual(day_shift_count(table, SUNDAY_INDEX), 4)

    def test_sunday_five_stops_precheck_on_the_sunday(self):
        settings = {**SETTINGS, "sunday_day_required_count": 5}
        result = precheck_schedule(
            staff_ids(), YEAR, MONTH, tight_sunday_schedule(), settings
        )
        self.assertTrue(
            any(
                w.startswith("1日: 日勤5人と夜勤2人を確保できません")
                for w in result.conflict_warnings
            ),
            result.conflict_warnings,
        )

    def test_other_days_use_day_required_count(self):
        settings = {**SETTINGS, "sunday_day_required_count": 4}
        table, _, _ = generate_shift(
            staff_ids(), YEAR, MONTH, tight_sunday_schedule(), settings
        )
        for d in range(DAY_COUNT):
            if d % 7 == 0:  # 日曜
                continue
            self.assertGreaterEqual(day_shift_count(table, d), 5, f"{d + 1}日")

    def test_diagnosis_shows_required_count_for_the_sunday(self):
        settings = {**SETTINGS, "sunday_day_required_count": 5}
        # 夜勤を固定して、不足が日勤にだけ出るようにする（★/☆で代わりに不足させない）
        schedule = tight_sunday_schedule()
        schedule[0][SUNDAY_INDEX] = "★"
        schedule[1][SUNDAY_INDEX] = "☆"
        precheck = precheck_schedule(staff_ids(), YEAR, MONTH, schedule, settings)
        messages = diagnose_infeasibility(
            staff_ids(),
            YEAR,
            MONTH,
            precheck.normalized,
            precheck.fixed_types,
            precheck.validated_settings,
        )
        self.assertIn("1日: 日勤が1人不足します（必要 5人）。", messages)


class SundaySettingValidationTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "day_leader_count": 1,
            "night_leader_count": 1,
            "night_eligible_count": 2,
            "max_night_shifts": 5,
            "day_required_count": 1,
        }

    def test_defaults_to_five(self):
        validated = validate_settings(self.settings, staff_count=6, day_count=30)
        self.assertEqual(validated["sunday_day_required_count"], 5)

    def test_rejects_zero_and_more_than_staff_count(self):
        for value in (0, 7):
            with self.assertRaises(SettingsValidationError):
                validate_settings(
                    {**self.settings, "sunday_day_required_count": value},
                    staff_count=6,
                    day_count=30,
                )

    def test_api_returns_400_for_invalid_value(self):
        request = GenerateRequest(
            staff_ids=staff_ids(),
            dates=list(range(1, DAY_COUNT + 1)),
            schedule=tight_sunday_schedule(),
            settings={**SETTINGS, "sunday_day_required_count": 0},
        )
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(generate(request))
        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("sunday_day_required_count", raised.exception.detail)


class LegacyStaffFloorsTests(unittest.TestCase):
    def build_request(self):
        return GenerateRequest(
            staff_ids=staff_ids(),
            staff_floors=[3] * STAFF_COUNT,
            dates=list(range(1, DAY_COUNT + 1)),
            schedule=[[""] * DAY_COUNT for _ in range(STAFF_COUNT)],
            settings=SETTINGS,
        )

    def test_request_model_ignores_staff_floors(self):
        self.assertFalse(hasattr(self.build_request(), "staff_floors"))

    def test_check_accepts_old_request(self):
        result = asyncio.run(check(self.build_request()))
        self.assertEqual(result["conflicts"], [])

    def test_generate_accepts_old_request(self):
        result = asyncio.run(generate(self.build_request()))
        self.assertIn("schedule", result)


if __name__ == "__main__":
    unittest.main()
