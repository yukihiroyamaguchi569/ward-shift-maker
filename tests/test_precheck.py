import asyncio
import unittest

from fastapi import HTTPException

from main import GenerateRequest, check
from solver import generate_shift, precheck_schedule

SETTINGS = {
    "year": 2026,
    "month": 11,
    "day_leader_count": 10,
    "night_leader_count": 8,
    "night_eligible_count": 17,
    "max_night_shifts": 5,
}

DAY_29_MESSAGE = "29日: 日勤5人と夜勤2人を確保できません（配置可能 5人 / 必要 6人"


def blank_schedule(staff_count, day_count):
    return [[""] * day_count for _ in range(staff_count)]


def overbooked_day_29_schedule():
    # 17人中、29日に 委 が1人、公 が11人 → 配置可能 5人 / 必要 6人
    schedule = blank_schedule(17, 30)
    schedule[0][28] = "委"
    for s in range(1, 12):
        schedule[s][28] = "公"
    return schedule


def staff_ids(count):
    return [str(i + 1) for i in range(count)]


class PrecheckScheduleTests(unittest.TestCase):
    def test_reports_day_with_too_many_fixed_offs(self):
        result = precheck_schedule(
            staff_ids(17), 2026, 11, overbooked_day_29_schedule(), SETTINGS
        )
        self.assertTrue(
            any(DAY_29_MESSAGE in w for w in result.conflict_warnings),
            result.conflict_warnings,
        )

    def test_reports_day_count_mismatch_first(self):
        result = precheck_schedule(
            staff_ids(19), 2026, 10, blank_schedule(19, 30), SETTINGS
        )
        self.assertEqual(
            result.conflict_warnings[0],
            "ファイルの日数（30日）と対象月（2026年10月: 31日）の日数が一致しません。"
            "対象月を確認してください。",
        )

    def test_clean_input_has_no_conflicts(self):
        result = precheck_schedule(
            staff_ids(19), 2026, 11, blank_schedule(19, 30), SETTINGS
        )
        self.assertEqual(result.conflict_warnings, [])

    def test_generate_shift_returns_precheck_conflicts_early(self):
        schedule = overbooked_day_29_schedule()
        result_schedule, warnings, day_leaders = generate_shift(
            staff_ids(17), [3] * 17, 2026, 11, schedule, SETTINGS
        )
        self.assertTrue(any(DAY_29_MESSAGE in w for w in warnings), warnings)
        self.assertEqual(result_schedule, schedule)
        self.assertEqual(day_leaders, [None] * 30)

    def test_generate_shift_still_fills_clean_input(self):
        result_schedule, _, _ = generate_shift(
            staff_ids(19), [3] * 19, 2026, 11, blank_schedule(19, 30), SETTINGS
        )
        self.assertTrue(all(cell != "" for row in result_schedule for cell in row))


class CheckEndpointTests(unittest.TestCase):
    def build_request(self, schedule, staff_count, settings):
        return GenerateRequest(
            staff_ids=staff_ids(staff_count),
            staff_floors=[3] * staff_count,
            dates=list(range(1, 31)),
            schedule=schedule,
            settings=settings,
        )

    def test_returns_400_on_invalid_settings(self):
        request = self.build_request(
            blank_schedule(19, 30), 19, {**SETTINGS, "night_leader_count": 0}
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(check(request))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("設定エラー", ctx.exception.detail)

    def test_returns_400_on_missing_setting(self):
        settings = {k: v for k, v in SETTINGS.items() if k != "month"}
        request = self.build_request(blank_schedule(19, 30), 19, settings)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(check(request))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_returns_conflicts_and_notices(self):
        request = self.build_request(overbooked_day_29_schedule(), 17, SETTINGS)
        result = asyncio.run(check(request))
        self.assertTrue(any(DAY_29_MESSAGE in w for w in result["conflicts"]))
        self.assertEqual(result["notices"], [])

    def test_clean_input_returns_no_conflicts(self):
        request = self.build_request(blank_schedule(19, 30), 19, SETTINGS)
        result = asyncio.run(check(request))
        self.assertEqual(result, {"conflicts": [], "notices": []})


if __name__ == "__main__":
    unittest.main()
