import unittest
from unittest import mock

from ortools.sat.python import cp_model

import solver
from solver import _classify, _normalize_cell, generate_shift

FIRST_LINE = "条件を満たす勤務表が見つかりませんでした。設定または固定希望を確認してください。"
LAST_LINE = "（上記は条件を満たせない箇所の一例です。いずれかを見直すと作成できる可能性があります。）"

SETTINGS = {
    "year": 2026,
    "month": 11,
    "day_leader_count": 3,
    "night_leader_count": 8,
    "night_eligible_count": 17,
    "max_night_shifts": 5,
}
STAFF_COUNT = 19
DAY_COUNT = 30


def staff_ids():
    return [str(i + 1) for i in range(STAFF_COUNT)]


def blank_schedule():
    return [[""] * DAY_COUNT for _ in range(STAFF_COUNT)]


def run(schedule):
    return generate_shift(
        staff_ids(), [3] * STAFF_COUNT, 2026, 11, schedule, SETTINGS
    )


def day_leader_blocked_schedule():
    # 10日: 日勤リーダー候補（上から3人）が 公・委・休 で、誰も日勤に入れない
    schedule = blank_schedule()
    schedule[0][9] = "公"
    schedule[1][9] = "委"
    schedule[2][9] = "休"
    return schedule


def single_star_candidate_schedule():
    # 10日と12日: ★候補のうち上から1人目を除く7人が公休（前後の9〜11日も★不可になる）。
    # 1人目は10日に★を入れると12日が公休になるため、両日は埋められない。
    schedule = blank_schedule()
    for s in range(1, 8):
        schedule[s][9] = "公"
        schedule[s][11] = "公"
    return schedule


class DiagnosisTests(unittest.TestCase):
    def test_reports_day_leader_shortage(self):
        _, warnings, _ = run(day_leader_blocked_schedule())
        self.assertEqual(warnings[0], FIRST_LINE)
        self.assertTrue(
            any(
                w.startswith("10日: 日勤リーダーを置けません。")
                and "上から3人" in w
                for w in warnings[1:]
            ),
            warnings,
        )
        self.assertEqual(warnings[-1], LAST_LINE)

    def test_reports_star_shortage_when_one_candidate_remains(self):
        _, warnings, _ = run(single_star_candidate_schedule())
        self.assertEqual(warnings[0], FIRST_LINE)
        self.assertTrue(
            any(
                "夜勤リーダー（★）を置けません" in w
                and ("10日" in w or "12日" in w)
                and "上から8人" in w
                for w in warnings[1:]
            ),
            warnings,
        )

    def test_feasible_input_does_not_run_diagnosis(self):
        with mock.patch.object(solver, "diagnose_infeasibility") as diagnose:
            _, warnings, _ = run(blank_schedule())
        diagnose.assert_not_called()
        self.assertFalse(any("見つかりませんでした" in w for w in warnings), warnings)

    def test_returns_empty_when_relaxed_model_has_no_solution(self):
        # 緩和モデルが解けない場合は診断なしで従来どおりの警告だけを返す
        with mock.patch.object(solver, "diagnose_infeasibility", return_value=[]):
            _, warnings, _ = run(day_leader_blocked_schedule())
        self.assertEqual(warnings[0], FIRST_LINE)
        self.assertNotIn(LAST_LINE, warnings)

    def test_timeout_does_not_run_diagnosis(self):
        class UnknownSolver(cp_model.CpSolver):
            def Solve(self, model, *args, **kwargs):
                return cp_model.UNKNOWN

        with mock.patch.object(solver.cp_model, "CpSolver", UnknownSolver), \
                mock.patch.object(solver, "diagnose_infeasibility") as diagnose:
            _, warnings, _ = run(blank_schedule())
        diagnose.assert_not_called()
        self.assertEqual(warnings[0], FIRST_LINE)
        self.assertNotIn(LAST_LINE, warnings)

    def test_diagnosis_failure_keeps_main_result(self):
        real_build = solver._build_model

        def failing_when_relaxed(*args, **kwargs):
            if kwargs.get("relax") or (len(args) > 7 and args[7]):
                raise RuntimeError("diagnosis broke")
            return real_build(*args, **kwargs)

        schedule = day_leader_blocked_schedule()
        with mock.patch.object(solver, "_build_model", failing_when_relaxed), \
                self.assertLogs(solver.logger, level="ERROR"):
            result, warnings, _ = run(schedule)
        self.assertEqual(warnings[0], FIRST_LINE)
        self.assertNotIn(LAST_LINE, warnings)
        # 返すのは補完前の正規化済み勤務表（休→公）で、解の結果は含まない
        expected = solver.precheck_schedule(
            staff_ids(), 2026, 11, schedule, SETTINGS
        ).pre_completion_normalized
        self.assertEqual(result, expected)

    def test_reports_over_capacity_from_fixed_nights_and_after(self):
        # 9日に固定の★と☆があり、10日に別の職員の固定の明 → 9日の夜勤が3人必要になる
        schedule = blank_schedule()
        schedule[0][8] = "★"
        schedule[1][8] = "☆"
        schedule[2][9] = "明"
        _, warnings, _ = run(schedule)
        self.assertEqual(warnings[0], FIRST_LINE)
        self.assertTrue(
            any(
                w.startswith("9日: ") and "が2人必要になり、1日1人を超えます" in w
                for w in warnings[1:]
            ),
            warnings,
        )

    def test_reports_over_capacity_when_afters_are_outside_star_group(self):
        # ★可能は上から8人。範囲外の2人の固定の明 → 9日が☆2人になる
        schedule = blank_schedule()
        schedule[10][9] = "明"
        schedule[11][9] = "明"
        _, warnings, _ = run(schedule)
        self.assertEqual(warnings[0], FIRST_LINE)
        self.assertTrue(
            any(
                w.startswith("9日: 夜勤（☆）が2人必要になり、1日1人を超えます")
                for w in warnings[1:]
            ),
            warnings,
        )


class FullWidthNormalizationTests(unittest.TestCase):
    def test_full_width_ascii_becomes_half_width(self):
        self.assertEqual(_normalize_cell("7ｂ"), "7b")
        self.assertEqual(_normalize_cell("Ｆ"), "F")
        self.assertEqual(_normalize_cell(" ７ｂ "), "7b")

    def test_other_characters_are_unchanged(self):
        self.assertEqual(_normalize_cell("ℓ"), "ℓ")
        self.assertEqual(_normalize_cell("★"), "★")
        self.assertEqual(_normalize_cell(""), "")

    def test_full_width_7b_is_classified_as_day(self):
        self.assertEqual(_classify(_normalize_cell("7ｂ")), "day")

    def test_full_width_7b_is_fixed_as_day_in_precheck(self):
        schedule = blank_schedule()
        schedule[3][4] = "7ｂ"
        result = solver.precheck_schedule(staff_ids(), 2026, 11, schedule, SETTINGS)
        self.assertEqual(result.normalized[3][4], "7b")
        self.assertEqual(result.fixed_types[3][4], "day")


if __name__ == "__main__":
    unittest.main()
