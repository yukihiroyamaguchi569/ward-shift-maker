import calendar
import copy
import json
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


FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "valid_schedule.json")


class CheckerDetectsViolationTests(unittest.TestCase):
    """固定フィクスチャ（正しい勤務表）を1か所ずつ壊し、狙ったルールの違反だけが出ることを確かめる。

    フィクスチャは tests/make_fixture.py で作る。作り直したら下の (職員, 日) を見直す
    （すべて0始まりのインデックス）。ソルバーは呼ばないので毎回同じ結果になる。
    """

    @classmethod
    def setUpClass(cls):
        with open(FIXTURE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        cls.year, cls.month = data["year"], data["month"]
        cls.ids, cls.settings = data["staff_ids"], data["settings"]
        cls.schedule, cls.base, cls.leaders = data["input"], data["result"], data["day_leaders"]
        cls.count = len(cls.ids)

    def problems(self, result=None, leaders=None, settings=None):
        return check_schedule(
            self.schedule,
            result if result is not None else self.base,
            leaders if leaders is not None else self.leaders,
            self.year, self.month,
            settings if settings is not None else self.settings,
            self.ids,
        )

    def broken(self, *edits):
        result = copy.deepcopy(self.base)
        for s, d, mark in edits:
            result[s][d] = mark
        return result

    def assertOnly(self, problems, *keywords):
        """違反が出ていて、すべて keywords のいずれかのルールのものであること。"""
        self.assertTrue(problems, "違反が検出されませんでした")
        for p in problems:
            self.assertTrue(any(k in p for k in keywords), problems)
        for k in keywords:
            self.assertTrue(any(k in p for p in problems), (k, problems))

    def test_base_is_clean(self):
        self.assertEqual(self.problems(), [])

    def test_integer_strings_in_settings(self):
        settings = {k: str(v) for k, v in self.settings.items()}
        self.assertEqual(self.problems(settings=settings), [])

    def test_blank_cell(self):
        self.assertOnly(self.problems(self.broken((7, 14, ""))), "空欄")

    def test_row_count(self):
        self.assertOnly(self.problems(self.base[:-1]), "行数")

    def test_column_count(self):
        r = self.broken()
        r[0] = r[0][:-1]
        self.assertOnly(self.problems(r), "列数")

    def test_fixed_cell_changed(self):
        self.assertEqual(self.schedule[3][10], "希")
        self.assertOnly(self.problems(self.broken((3, 10, "公休"))), "固定セル")

    def test_two_leaders(self):
        # 18日に職員2を ★ にして、夜勤セット（明・公休）まで整える
        r = self.broken((1, 17, "★"), (1, 18, "明"), (1, 19, "公休"))
        self.assertOnly(self.problems(r), "★が2人")

    def test_night_outside_eligible(self):
        r = self.broken((18, 17, "☆"), (18, 18, "明"), (18, 19, "公休"))
        self.assertOnly(self.problems(r), "夜勤候補の範囲外", "☆が2人")

    def test_leader_outside_leader_candidates(self):
        r = self.broken((10, 17, "★"), (10, 18, "明"), (10, 19, "公休"))
        self.assertOnly(self.problems(r), "リーダー候補の範囲外", "★が2人")

    def test_after_replaced_by_day(self):
        self.assertEqual(self.base[0][3], "明")
        self.assertOnly(self.problems(self.broken((0, 3, "日"))), "翌日が明ではありません")

    def test_after_without_night(self):
        self.assertOnly(self.problems(self.broken((1, 17, "明"))), "明の前日が夜勤ではありません")

    def test_second_day_after_night_not_off(self):
        # 3日の夜勤（職員1）の翌々日(5日)を日にし、休みの数は別の日(2日)を休みにして保つ
        r = self.broken((0, 4, "日"), (0, 1, "公休"))
        self.assertOnly(self.problems(r), "翌々日が休みではありません")

    def test_day_shortage(self):
        r = self.broken()
        day = 14
        plain = [s for s in range(self.count)
                 if r[s][day] == "日" and self.ids[s] != self.leaders[day]]
        working = sum(r[s][day] in ("日", "7b") for s in range(self.count))
        for s in plain[: working - 4]:
            r[s][day] = "公休"
        self.assertOnly(self.problems(r), "必要人数")

    def test_month_start_after_not_fixed(self):
        self.assertEqual(self.schedule[1][0], "")
        self.assertOnly(self.problems(self.broken((1, 0, "明"))), "前月持ち越しではありません")

    def test_day_after_month_start_after_not_off(self):
        self.assertEqual(self.schedule[4][0], "明")
        r = self.broken((4, 1, "日"), (4, 2, "公休"))
        self.assertOnly(self.problems(r), "月初の明の翌日")

    def test_unexpected_mark_in_blank_cell(self):
        self.assertOnly(self.problems(self.broken((1, 17, "委"))), "想定外の記号")

    def test_missing_7b_on_weekday(self):
        self.assertEqual(self.base[0][14], "7b")
        self.assertOnly(self.problems(self.broken((0, 14, "日"))), "7bが0人")

    def test_two_7b_on_weekday(self):
        self.assertOnly(self.problems(self.broken((0, 0, "7b"))), "7bが2人")

    def test_7b_on_sunday(self):
        self.assertEqual(calendar.weekday(2026, 9, 13), 6)
        self.assertOnly(self.problems(self.broken((0, 12, "7b"))), "固定ではない7b")

    def test_day_leader_outside_candidates(self):
        leaders = list(self.leaders)
        leaders[0] = self.ids[-1]
        self.assertOnly(self.problems(leaders=leaders), "候補の範囲外")

    def test_day_leader_not_working_day(self):
        leaders = list(self.leaders)
        self.assertEqual(self.base[0][4], "公休")
        leaders[4] = self.ids[0]
        self.assertOnly(self.problems(leaders=leaders), "日/7bではありません")

    def test_one_less_day_off(self):
        self.assertOnly(self.problems(self.broken((0, 9, "日"))), "休みが")

    def test_six_consecutive_work_days(self):
        # 休みの数は保ったまま、職員1の27日からの連勤を6日以上にする
        r = self.broken((0, 26, "日"), (0, 0, "公休"))
        self.assertOnly(self.problems(r), "6連勤")

    def test_night_limit(self):
        settings = {**self.settings, "max_night_shifts": 1}
        self.assertOnly(self.problems(settings=settings), "上限")


if __name__ == "__main__":
    unittest.main()
