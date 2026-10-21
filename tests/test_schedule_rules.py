import calendar
import copy
import os
import random
import unittest

from schedule_rules import check_schedule
from solver import generate_shift

NOT_FOUND = "見つかりませんでした"
BASE_SETTINGS = {
    "day_leader_count": 10,
    "night_leader_count": 8,
    "night_eligible_count": 17,
    "max_night_shifts": 5,
}


def staff_ids(count):
    return [str(i + 1) for i in range(count)]


def empty_schedule(count, year, month):
    return [[""] * calendar.monthrange(year, month)[1] for _ in range(count)]


def solve_and_check(test, schedule, year, month, settings, count):
    ids = staff_ids(count)
    result, warnings, day_leaders = generate_shift(ids, year, month, schedule, settings)
    test.assertFalse(any(NOT_FOUND in w for w in warnings), warnings)
    test.assertEqual(check_schedule(schedule, result, day_leaders, year, month, settings, ids), [])
    return result, day_leaders


class GeneratedScheduleTests(unittest.TestCase):
    def test_30_days_19_staff_blank(self):
        solve_and_check(self, empty_schedule(19, 2026, 9), 2026, 9, BASE_SETTINGS, 19)

    def test_february_17_staff(self):
        settings = {**BASE_SETTINGS, "night_eligible_count": 15, "night_leader_count": 7}
        solve_and_check(self, empty_schedule(17, 2026, 2), 2026, 2, settings, 17)

    def test_31_days_sunday_four(self):
        settings = {**BASE_SETTINGS, "sunday_day_required_count": 4}
        solve_and_check(self, empty_schedule(19, 2026, 10), 2026, 10, settings, 19)

    def test_with_fixed_cells(self):
        schedule = fixed_cells_schedule()
        solve_and_check(self, schedule, 2026, 9, BASE_SETTINGS, 19)

    def test_tight_settings(self):
        settings = {
            "day_leader_count": 6,
            "night_leader_count": 6,
            "night_eligible_count": 13,
            "max_night_shifts": 5,
        }
        solve_and_check(self, empty_schedule(19, 2026, 9), 2026, 9, settings, 19)

    @unittest.skipUnless(os.environ.get("RUN_SLOW_TESTS") == "1", "RUN_SLOW_TESTS=1 で実行")
    def test_random_inputs(self):
        for seed in range(10):
            with self.subTest(seed=seed):
                rng = random.Random(seed)
                year, month = 2026, rng.choice([2, 4, 9, 10, 12])
                count = rng.randint(17, 21)
                schedule = empty_schedule(count, year, month)
                days = len(schedule[0])
                for s in range(count):
                    for d in rng.sample(range(2, days), 2):
                        schedule[s][d] = rng.choice(["希", "有", "公休"])
                for d in rng.sample(range(2, days), 3):
                    schedule[rng.randrange(count)][d] = rng.choice(["委", "研"])
                settings = {**BASE_SETTINGS, "sunday_day_required_count": rng.choice([4, 5])}
                solve_and_check(self, schedule, year, month, settings, count)


def fixed_cells_schedule():
    # 2026年9月: 希望休・月初の明・固定の ★/☆・委/研・固定の 7b
    schedule = empty_schedule(19, 2026, 9)
    for s, d in [(3, 10), (5, 20), (9, 5), (12, 15), (15, 25)]:
        schedule[s][d] = "希"
    schedule[4][0] = "明"
    schedule[2][7] = "★"
    schedule[13][13] = "☆"
    schedule[6][17] = "委"
    schedule[8][22] = "研"
    schedule[10][11] = "7b"
    return schedule


class CheckerDetectsViolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.year, cls.month, cls.count = 2026, 9, 19
        cls.schedule = fixed_cells_schedule()
        cls.ids = staff_ids(cls.count)
        cls.base, cls.leaders = generate_shift(
            cls.ids, cls.year, cls.month, cls.schedule, BASE_SETTINGS
        )[0::2]

    def problems(self, result=None, leaders=None, settings=None, schedule=None):
        return check_schedule(
            schedule if schedule is not None else self.schedule,
            result if result is not None else self.base,
            leaders if leaders is not None else self.leaders,
            self.year, self.month,
            settings if settings is not None else BASE_SETTINGS,
            self.ids,
        )

    def broken(self):
        return copy.deepcopy(self.base)

    def assertDetected(self, problems, keyword):
        self.assertTrue(any(keyword in p for p in problems), problems)

    def test_base_is_clean(self):
        self.assertEqual(self.problems(), [])

    def test_blank_cell(self):
        r = self.broken()
        r[7][14] = ""
        self.assertDetected(self.problems(r), "空欄")

    def test_row_count(self):
        self.assertDetected(self.problems(self.broken()[:-1]), "行数")

    def test_column_count(self):
        r = self.broken()
        r[0] = r[0][:-1]
        self.assertDetected(self.problems(r), "列数")

    def test_fixed_cell_changed(self):
        r = self.broken()
        r[3][10] = "公休"
        self.assertDetected(self.problems(r), "固定セル")

    def test_two_leaders(self):
        r = self.broken()
        s = next(s for s in range(self.count) if r[s][14] == "日")
        r[s][14] = "★"
        self.assertDetected(self.problems(r), "★が2人")

    def test_night_outside_eligible(self):
        r = self.broken()
        r[18][14] = "☆"
        self.assertDetected(self.problems(r), "夜勤候補の範囲外")

    def test_leader_outside_leader_candidates(self):
        r = self.broken()
        r[10][14] = "★"
        self.assertDetected(self.problems(r), "リーダー候補の範囲外")

    def test_after_replaced_by_day(self):
        r = self.broken()
        d = next(d for d in range(1, 29) if r[0][d] == "明")
        r[0][d] = "日"
        self.assertDetected(self.problems(r), "翌日が明ではありません")

    def test_after_without_night(self):
        r = self.broken()
        s, d = next((s, d) for s in range(self.count) for d in range(3, 28) if r[s][d] == "日" and r[s][d - 1] == "日")
        r[s][d] = "明"
        self.assertDetected(self.problems(r), "明の前日が夜勤ではありません")

    def test_second_day_after_night_not_off(self):
        r = self.broken()
        s, d = next((s, d) for s in range(self.count) for d in range(27) if r[s][d] in "★☆" and self.schedule[s][d] == "")
        r[s][d + 2] = "日"
        self.assertDetected(self.problems(r), "翌々日が休みではありません")

    def test_day_shortage(self):
        r = self.broken()
        for s in range(self.count):
            if r[s][14] in ("日", "7b"):
                r[s][14] = "公休"
        self.assertDetected(self.problems(r), "必要人数")

    def test_missing_7b_on_weekday(self):
        r = self.broken()
        s, d = next((s, d) for s in range(self.count) for d in range(30)
                    if r[s][d] == "7b" and self.schedule[s][d] == "" and calendar.weekday(2026, 9, d + 1) != 6)
        r[s][d] = "日"
        self.assertDetected(self.problems(r), "7bが0人")

    def test_7b_on_sunday(self):
        r = self.broken()
        d = next(d for d in range(30) if calendar.weekday(2026, 9, d + 1) == 6)
        s = next(s for s in range(self.count) if r[s][d] == "日")
        r[s][d] = "7b"
        self.assertDetected(self.problems(r), "固定ではない7b")

    def test_day_leader_outside_candidates(self):
        leaders = list(self.leaders)
        leaders[0] = self.ids[-1]
        self.assertDetected(self.problems(leaders=leaders), "候補の範囲外")

    def test_day_leader_not_working_day(self):
        leaders = list(self.leaders)
        s = next(s for s in range(10) if self.base[s][14] not in ("日", "7b"))
        leaders[14] = self.ids[s]
        self.assertDetected(self.problems(leaders=leaders), "日/7bではありません")

    def test_one_less_day_off(self):
        r = self.broken()
        s = next(s for s in range(self.count) if sum(m in ("公休", "希", "有") for m in r[s]) == 9)
        d = next(d for d in range(30) if r[s][d] == "公休" and self.schedule[s][d] == "")
        r[s][d] = "日"
        self.assertDetected(self.problems(r), "休みが8日")

    def test_six_consecutive_work_days(self):
        r = self.broken()
        for d in range(6):
            r[18][d + 9] = "日"
        self.assertDetected(self.problems(r), "6連勤")

    def test_night_limit(self):
        settings = {**BASE_SETTINGS, "max_night_shifts": 1}
        self.assertDetected(self.problems(settings=settings), "上限")


if __name__ == "__main__":
    unittest.main()
