"""勤務表がルールを守っているかを検査するチェッカー（テスト専用）。

ソルバーの制約コードや記号集合には依存せず、ルールをここに素直に書く。
入力の表記ゆれの正規化だけは solver._normalize_cell を使う（変換であり制約ではない）。
"""

import calendar
from typing import Dict, List, Optional

from solver import _normalize_cell

NIGHT_LEADER = "★"
NIGHT_PAIR = "☆"
AFTER = "明"
OFF_MARKS = {"公休", "希", "有"}
DAY_MARKS = {"日", "7b"}
NIGHT_MARKS = {NIGHT_LEADER, NIGHT_PAIR}
KNOWN_MARKS = OFF_MARKS | DAY_MARKS | NIGHT_MARKS | {AFTER}


def _is_fixed_day_like(mark: str) -> bool:
    """委・研など、日勤扱いの固定記号。"""
    return mark != "" and mark not in KNOWN_MARKS


def _is_work(mark: str) -> bool:
    return mark in DAY_MARKS or mark in NIGHT_MARKS or mark == AFTER or _is_fixed_day_like(mark)


def _normalized_input(input_schedule: List[List[str]], staff_count: int, day_count: int):
    rows = []
    for s in range(staff_count):
        row = list(input_schedule[s]) if s < len(input_schedule) else []
        row = (row + [""] * day_count)[:day_count]
        rows.append([_normalize_cell(cell) for cell in row])
    return rows


def _check_shape(result, staff_count, day_count) -> List[str]:
    problems = []
    if len(result) != staff_count:
        problems.append(f"行数が職員数と一致しません（{len(result)} / {staff_count}）")
    for s, row in enumerate(result):
        if len(row) != day_count:
            problems.append(f"職員{s + 1}: 列数が日数と一致しません（{len(row)} / {day_count}）")
    for s, row in enumerate(result):
        for d, mark in enumerate(row):
            if mark == "":
                problems.append(f"職員{s + 1}: {d + 1}日が空欄です")
    return problems


def _check_fixed_cells(fixed, result, staff_count, day_count) -> List[str]:
    return [
        f"職員{s + 1}: {d + 1}日の固定セル「{fixed[s][d]}」が「{result[s][d]}」に変わりました"
        for s in range(staff_count)
        for d in range(day_count)
        if fixed[s][d] != "" and result[s][d] != fixed[s][d]
    ]


def _check_night_people(fixed, result, staff_count, day_count, rule) -> List[str]:
    problems = []
    for d in range(day_count):
        leaders = sum(1 for s in range(staff_count) if result[s][d] == NIGHT_LEADER)
        pairs = sum(1 for s in range(staff_count) if result[s][d] == NIGHT_PAIR)
        if leaders != 1 or pairs != 1:
            problems.append(f"{d + 1}日: ★が{leaders}人、☆が{pairs}人です（各1人のはず）")
    eligible = min(rule["night_eligible_count"], staff_count)
    leader_ok = min(rule["night_leader_count"], staff_count)
    for s in range(staff_count):
        for d in range(day_count):
            if fixed[s][d] != "":
                continue
            if result[s][d] in NIGHT_MARKS and s >= eligible:
                problems.append(f"職員{s + 1}: {d + 1}日の夜勤が夜勤候補の範囲外です")
            if result[s][d] == NIGHT_LEADER and s >= leader_ok:
                problems.append(f"職員{s + 1}: {d + 1}日の★がリーダー候補の範囲外です")
    return problems


def _check_night_sets(result, staff_count, day_count) -> List[str]:
    problems = []
    for s in range(staff_count):
        for d in range(day_count):
            if result[s][d] in NIGHT_MARKS:
                if d + 1 < day_count and result[s][d + 1] != AFTER:
                    problems.append(f"職員{s + 1}: {d + 1}日の夜勤の翌日が明ではありません")
                if d + 2 < day_count and result[s][d + 2] not in OFF_MARKS:
                    problems.append(f"職員{s + 1}: {d + 1}日の夜勤の翌々日が休みではありません")
            if result[s][d] == AFTER and d > 0 and result[s][d - 1] not in NIGHT_MARKS:
                problems.append(f"職員{s + 1}: {d + 1}日の明の前日が夜勤ではありません")
    return problems


def _required_day_count(year, month, d, rule) -> int:
    base = rule.get("day_required_count", 5)
    if calendar.weekday(year, month, d + 1) == 6:
        return rule.get("sunday_day_required_count", base)
    return base


def _check_day_staffing(fixed, result, year, month, staff_count, day_count, rule) -> List[str]:
    problems = []
    for d in range(day_count):
        is_sunday = calendar.weekday(year, month, d + 1) == 6
        working = sum(
            1 for s in range(staff_count)
            if result[s][d] in DAY_MARKS or _is_fixed_day_like(result[s][d])
        )
        need = _required_day_count(year, month, d, rule)
        if working < need:
            problems.append(f"{d + 1}日: 日勤が{working}人で必要人数{need}人に足りません")
        sevens = [s for s in range(staff_count) if result[s][d] == "7b"]
        if is_sunday:
            extra = [s for s in sevens if fixed[s][d] != "7b"]
            if extra:
                problems.append(f"{d + 1}日(日曜): 固定ではない7bがあります")
        elif len(sevens) != 1:
            problems.append(f"{d + 1}日: 7bが{len(sevens)}人です（1人のはず）")
    return problems


def _check_day_leaders(result, day_leaders, staff_ids, day_count, rule) -> List[str]:
    problems = []
    leader_range = staff_ids[: min(rule["day_leader_count"], len(staff_ids))]
    if len(day_leaders) != day_count:
        return [f"day_leaders の長さが日数と一致しません（{len(day_leaders)}）"]
    for d, leader in enumerate(day_leaders):
        if leader is None or leader not in staff_ids:
            problems.append(f"{d + 1}日: 日勤リーダーが決まっていません")
            continue
        if leader not in leader_range:
            problems.append(f"{d + 1}日: 日勤リーダー{leader}が候補の範囲外です")
        if result[staff_ids.index(leader)][d] not in DAY_MARKS:
            problems.append(f"{d + 1}日: 日勤リーダー{leader}が日/7bではありません")
    return problems


def _check_per_staff(fixed, result, staff_count, day_count, rule, off_target) -> List[str]:
    problems = []
    for s in range(staff_count):
        offs = sum(1 for m in result[s] if m in OFF_MARKS)
        fixed_offs = sum(1 for m in fixed[s] if m in OFF_MARKS)
        need = max(off_target, fixed_offs)
        if offs < need:
            problems.append(f"職員{s + 1}: 休みが{offs}日で最低{need}日に足りません")
        for d in range(day_count - 5):
            if sum(1 for m in result[s][d:d + 6] if _is_work(m)) > 5:
                problems.append(f"職員{s + 1}: {d + 1}日からの6日間に6連勤があります")
        nights = sum(1 for m in result[s] if m in NIGHT_MARKS)
        if nights > rule["max_night_shifts"]:
            problems.append(f"職員{s + 1}: 夜勤が{nights}回で上限{rule['max_night_shifts']}回を超えています")
    return problems


def check_schedule(
    input_schedule: List[List[str]],
    result: List[List[str]],
    day_leaders: List[Optional[str]],
    year: int,
    month: int,
    settings: Dict,
    staff_ids: List[str],
) -> List[str]:
    """違反の説明の一覧を返す（空なら合格）。"""
    staff_count = len(staff_ids)
    day_count = calendar.monthrange(year, month)[1]
    problems = _check_shape(result, staff_count, day_count)
    if problems:
        return problems
    fixed = _normalized_input(input_schedule, staff_count, day_count)
    rule = dict(settings)
    off_target = int(settings.get("days_off_count", 8 if month == 2 else 9))

    problems += _check_fixed_cells(fixed, result, staff_count, day_count)
    problems += _check_night_people(fixed, result, staff_count, day_count, rule)
    problems += _check_night_sets(result, staff_count, day_count)
    problems += _check_day_staffing(fixed, result, year, month, staff_count, day_count, rule)
    problems += _check_day_leaders(result, day_leaders, staff_ids, day_count, rule)
    problems += _check_per_staff(fixed, result, staff_count, day_count, rule, off_target)
    return problems
