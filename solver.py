"""
夜勤セットだけを組む勤務表ソルバー。

night-only-rule.md に合わせて、`★/☆/明/公` の夜勤3日セットのみを生成する。
それ以外の未入力セルは空欄のまま残す。
"""

import calendar
from typing import Dict, List, Tuple

from ortools.sat.python import cp_model

BLANK = ""
HOLIDAY = "公"
AFTER = "明"
LEADER_NIGHT = "★"
PAIR_NIGHT = "☆"

OFF_TYPES = {"公", "希", "休", "有"}
LEADER_MARKS = {LEADER_NIGHT}
PAIR_MARKS = {PAIR_NIGHT, "夜"}  # 既存データ互換
AFTER_MARKS = {AFTER, "～", "～⋆", "〜", "〜⋆"}


def _normalize_cell(text: str) -> str:
    value = text.strip()
    if value == "":
        return BLANK
    if value == "休":
        return HOLIDAY
    if value in LEADER_MARKS:
        return LEADER_NIGHT
    if value in PAIR_MARKS:
        return PAIR_NIGHT
    if value in AFTER_MARKS:
        return AFTER
    return value


def _classify(text: str) -> str:
    if text == BLANK:
        return "blank"
    if text in LEADER_MARKS:
        return "leader_night"
    if text in PAIR_MARKS:
        return "pair_night"
    if text in AFTER_MARKS:
        return "after"
    if text in OFF_TYPES:
        return "off"
    return "fixed_other"


def generate_shift(
    staff_ids: List[str],
    staff_floors: List[int],
    staff_sections: List[str],
    year: int,
    month: int,
    schedule: List[List[str]],
    settings: Dict,
) -> Tuple[List[List[str]], List[str]]:
    del staff_floors
    del staff_sections

    staff_count = len(staff_ids)
    day_count = calendar.monthrange(year, month)[1]
    warnings: List[str] = []

    night_leader_count = min(int(settings["night_leader_count"]), staff_count)
    night_eligible_count = min(int(settings["night_eligible_count"]), staff_count)
    max_night_shifts = int(settings["max_night_shifts"])

    normalized = []
    for row in schedule:
        padded = list(row) + [BLANK] * max(0, day_count - len(row))
        normalized.append([_normalize_cell(cell) for cell in padded[:day_count]])
    while len(normalized) < staff_count:
        normalized.append([BLANK] * day_count)

    fixed_types = [
        [_classify(normalized[s][d]) for d in range(day_count)]
        for s in range(staff_count)
    ]

    # 固定夜勤がある場合は、空欄にだけ「明」「公」を補完する。
    for s in range(staff_count):
        for d in range(day_count):
            if fixed_types[s][d] not in {"leader_night", "pair_night"}:
                continue
            if d + 1 < day_count and fixed_types[s][d + 1] == "blank":
                fixed_types[s][d + 1] = "after"
                normalized[s][d + 1] = AFTER
            if d + 2 < day_count and fixed_types[s][d + 2] == "blank":
                fixed_types[s][d + 2] = "off"
                normalized[s][d + 2] = HOLIDAY

    model = cp_model.CpModel()

    is_blank = {
        (s, d): model.NewBoolVar(f"blank_{s}_{d}")
        for s in range(staff_count)
        for d in range(day_count)
    }
    is_off = {
        (s, d): model.NewBoolVar(f"off_{s}_{d}")
        for s in range(staff_count)
        for d in range(day_count)
    }
    is_after = {
        (s, d): model.NewBoolVar(f"after_{s}_{d}")
        for s in range(staff_count)
        for d in range(day_count)
    }
    is_leader = {
        (s, d): model.NewBoolVar(f"leader_{s}_{d}")
        for s in range(staff_count)
        for d in range(day_count)
    }
    is_pair = {
        (s, d): model.NewBoolVar(f"pair_{s}_{d}")
        for s in range(staff_count)
        for d in range(day_count)
    }

    for s in range(staff_count):
        for d in range(day_count):
            model.AddExactlyOne(
                [
                    is_blank[s, d],
                    is_off[s, d],
                    is_after[s, d],
                    is_leader[s, d],
                    is_pair[s, d],
                ]
            )

    fixed_map = {
        "blank": is_blank,
        "off": is_off,
        "after": is_after,
        "leader_night": is_leader,
        "pair_night": is_pair,
        "fixed_other": is_blank,
    }
    for s in range(staff_count):
        for d in range(day_count):
            fixed_type = fixed_types[s][d]
            if fixed_type == "blank":
                continue
            model.Add(fixed_map[fixed_type][s, d] == 1)

    # 夜勤可能人数外は夜勤に入れない。
    for s in range(night_eligible_count, staff_count):
        for d in range(day_count):
            model.Add(is_leader[s, d] == 0)
            model.Add(is_pair[s, d] == 0)

    # 夜勤リーダー可能人数外は ★ に入れない。
    for s in range(night_leader_count, staff_count):
        for d in range(day_count):
            model.Add(is_leader[s, d] == 0)

    # 毎日 1 人の ★ と 1 人の ☆ を配置。
    for d in range(day_count):
        model.Add(sum(is_leader[s, d] for s in range(staff_count)) == 1)
        model.Add(sum(is_pair[s, d] for s in range(staff_count)) == 1)

    # 夜勤3日セット: 夜勤 -> 明け -> 公休
    for s in range(staff_count):
        for d in range(day_count):
            if d + 1 < day_count:
                model.AddImplication(is_leader[s, d], is_after[s, d + 1])
                model.AddImplication(is_pair[s, d], is_after[s, d + 1])
            if d + 2 < day_count:
                model.AddImplication(is_leader[s, d], is_off[s, d + 2])
                model.AddImplication(is_pair[s, d], is_off[s, d + 2])

    # 明けは前日夜勤の翌日のみ。ただし月初の固定明けは前月またぎとして許容。
    for s in range(staff_count):
        for d in range(day_count):
            if fixed_types[s][d] == "after":
                continue
            if d == 0:
                model.Add(is_after[s, d] == 0)
            else:
                model.Add(is_after[s, d] <= is_leader[s, d - 1] + is_pair[s, d - 1])

    # 公休は夜勤の2日後のみ。固定公休はそのまま許容。
    for s in range(staff_count):
        for d in range(day_count):
            if fixed_types[s][d] == "off":
                continue
            if d < 2:
                model.Add(is_off[s, d] == 0)
            else:
                model.Add(is_off[s, d] <= is_leader[s, d - 2] + is_pair[s, d - 2])

    # 固定セルが夜勤セットと衝突するなら、その前日は夜勤不可。
    for s in range(staff_count):
        for d in range(day_count):
            if fixed_types[s][d] != "blank":
                continue
            if d + 1 < day_count and fixed_types[s][d + 1] not in {"blank", "after"}:
                model.Add(is_leader[s, d] == 0)
                model.Add(is_pair[s, d] == 0)
            if d + 2 < day_count and fixed_types[s][d + 2] not in {"blank", "off"}:
                model.Add(is_leader[s, d] == 0)
                model.Add(is_pair[s, d] == 0)

    # 月間夜勤上限
    night_counts = []
    for s in range(staff_count):
        night_count = model.NewIntVar(0, day_count, f"night_count_{s}")
        model.Add(
            night_count == sum(is_leader[s, d] + is_pair[s, d] for d in range(day_count))
        )
        model.Add(night_count <= max_night_shifts)
        night_counts.append(night_count)

    objective_terms = []

    eligible_staff = list(range(night_eligible_count))
    if eligible_staff:
        max_nights = model.NewIntVar(0, max_night_shifts, "max_nights")
        min_nights = model.NewIntVar(0, max_night_shifts, "min_nights")
        model.AddMaxEquality(max_nights, [night_counts[s] for s in eligible_staff])
        model.AddMinEquality(min_nights, [night_counts[s] for s in eligible_staff])
        night_spread = model.NewIntVar(0, max_night_shifts, "night_spread")
        model.Add(night_spread == max_nights - min_nights)
        objective_terms.append(night_spread * 100)

    # ☆ はできるだけリーダー候補外から選ぶ。
    leader_pair_penalty = sum(
        is_pair[s, d]
        for s in range(night_leader_count)
        for d in range(day_count)
    )
    objective_terms.append(leader_pair_penalty * 1000)

    model.Minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    solver.parameters.num_search_workers = 8
    solver.parameters.log_search_progress = False

    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        warnings.append("条件を満たす夜勤表が見つかりませんでした。設定または固定希望を確認してください。")
        total_capacity = night_eligible_count * max_night_shifts
        required_nights = day_count * 2
        if total_capacity < required_nights:
            warnings.append(
                f"夜勤要員不足: 必要 {required_nights} 回、最大 {total_capacity} 回です。"
            )
        return [row[:] for row in normalized], warnings

    result = [[BLANK] * day_count for _ in range(staff_count)]
    for s in range(staff_count):
        for d in range(day_count):
            fixed_value = normalized[s][d]
            fixed_type = fixed_types[s][d]
            if fixed_type == "fixed_other":
                result[s][d] = fixed_value
            elif fixed_value != BLANK:
                result[s][d] = fixed_value
            elif solver.Value(is_leader[s, d]):
                result[s][d] = LEADER_NIGHT
            elif solver.Value(is_pair[s, d]):
                result[s][d] = PAIR_NIGHT
            elif solver.Value(is_after[s, d]):
                result[s][d] = AFTER
            elif solver.Value(is_off[s, d]):
                result[s][d] = HOLIDAY
            else:
                result[s][d] = BLANK

    for d in range(day_count):
        leader_total = sum(1 for s in range(staff_count) if result[s][d] == LEADER_NIGHT)
        pair_total = sum(1 for s in range(staff_count) if result[s][d] == PAIR_NIGHT)
        if leader_total != 1 or pair_total != 1:
            warnings.append(
                f"{d + 1}日: 夜勤内訳が不正です（★ {leader_total}人 / ☆ {pair_total}人）。"
            )

    for s in range(staff_count):
        night_total = sum(
            1 for d in range(day_count) if result[s][d] in {LEADER_NIGHT, PAIR_NIGHT}
        )
        if night_total > max_night_shifts:
            warnings.append(
                f"職員{staff_ids[s]}: 夜勤 {night_total} 回（上限 {max_night_shifts} 回）"
            )

    soft_violation_days = sum(
        1
        for d in range(day_count)
        for s in range(night_leader_count)
        if result[s][d] == PAIR_NIGHT
    )
    if soft_violation_days > 0:
        warnings.append(
            f"リーダー候補同士の夜勤ペアが {soft_violation_days} 日あります。"
        )

    return result, warnings
