"""検出テスト用の固定フィクスチャ（正しい勤務表）を作り直すスクリプト。

使い方: venv/bin/python tests/make_fixture.py
生成結果は毎回変わるため、作り直したら test_schedule_rules.py の変異対象
（職員・日）を見直すこと。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from schedule_rules import check_schedule  # noqa: E402
from solver import generate_shift  # noqa: E402
from test_schedule_rules import BASE_SETTINGS, fixed_cells_schedule  # noqa: E402

YEAR, MONTH, COUNT = 2026, 9, 19


def main():
    ids = [str(i + 1) for i in range(COUNT)]
    schedule = fixed_cells_schedule()
    result, warnings, leaders = generate_shift(ids, YEAR, MONTH, schedule, BASE_SETTINGS)
    problems = check_schedule(schedule, result, leaders, YEAR, MONTH, BASE_SETTINGS, ids)
    if warnings and any("見つかりませんでした" in w for w in warnings) or problems:
        raise SystemExit(f"正しい勤務表になりません: {warnings} {problems}")
    path = os.path.join(os.path.dirname(__file__), "fixtures", "valid_schedule.json")
    data = {
        "year": YEAR, "month": MONTH, "staff_ids": ids, "settings": BASE_SETTINGS,
        "input": schedule, "result": result, "day_leaders": leaders,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
