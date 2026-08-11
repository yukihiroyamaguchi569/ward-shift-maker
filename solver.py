"""
全セルを確定させる勤務表ソルバー。

night-only-rule.md に合わせて、`★/☆/明/公` の夜勤3日セットに加え、
日勤（日/7b）と公休（公）で全セルを確定した勤務表を生成する。
7b はスタッフの属性ではなく日ごとの割り当てで、日曜以外は毎日1人を
日勤者の中からソルバーが選ぶ（同一スタッフが日により日/7bを担当する）。
公休は1人あたり最低9日（2月のみ8日）で、希・有もカウントに含む
（固定の休みがこれを超える場合はその日数を許容し、連勤制限を満たす
ために必要な場合はソルバーが休みを追加できる）。
毎日1人の日勤リーダーを日勤リーダー候補から選び、返り値 day_leaders で明示する
（セルの文字は「日」のまま変更しない）。
"""

import calendar
from typing import Dict, List, Optional, Tuple

from ortools.sat.python import cp_model

BLANK = ""
HOLIDAY = "公"
AFTER = "明"
LEADER_NIGHT = "★"
PAIR_NIGHT = "☆"
DAY_SHIFT = "日"
DAY_SHIFT_7B = "7b"

OFF_TYPES = {"公", "希", "休", "有"}
LEADER_MARKS = {LEADER_NIGHT}
PAIR_MARKS = {PAIR_NIGHT, "夜"}  # 既存データ互換
AFTER_MARKS = {AFTER, "～", "～⋆", "〜", "〜⋆"}
DAY_MARKS = {DAY_SHIFT, DAY_SHIFT_7B}

# 同義語の正規化（出力セルは正規化後の1文字表記になる。既存の 休→公 と同じ挙動）
SYNONYM_MARKS = {
    "休": HOLIDAY,
    "公休": HOLIDAY,
    "希望休": "希",
    "希望": "希",
    "有休": "有",
    "有給": "有",
    "明け": AFTER,
    "夜勤": PAIR_NIGHT,
}


def _normalize_cell(text: str) -> str:
    value = text.strip()
    if value == "":
        return BLANK
    if value in SYNONYM_MARKS:
        return SYNONYM_MARKS[value]
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
    if text in DAY_MARKS:
        return "day"
    return "fixed_other"


def generate_shift(
    staff_ids: List[str],
    staff_floors: List[int],
    year: int,
    month: int,
    schedule: List[List[str]],
    settings: Dict,
) -> Tuple[List[List[str]], List[str], List[Optional[str]]]:
    del staff_floors  # 将来の日曜ルール（階別人数）用に残す

    staff_count = len(staff_ids)
    day_count = calendar.monthrange(year, month)[1]
    warnings: List[str] = []

    night_leader_count = min(int(settings["night_leader_count"]), staff_count)
    night_eligible_count = min(int(settings["night_eligible_count"]), staff_count)
    max_night_shifts = int(settings["max_night_shifts"])
    day_leader_count = min(int(settings["day_leader_count"]), staff_count)
    day_required_count = int(settings.get("day_required_count", 5))
    # 公休日数: 2月のみ8日、他の月は9日（settings で上書き可能）
    off_target = int(settings.get("days_off_count", 8 if month == 2 else 9))

    empty_day_leaders: List[Optional[str]] = [None] * day_count

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

    # 補完（明・公の自動補完）前の状態を保持しておく。ソルバー実行前の警告や
    # INFEASIBLE 時には、入力と異なる表を返さないようこちらを返す。
    pre_completion_normalized = [row[:] for row in normalized]

    # --- 固定入力の事前バリデーション ---
    # モデルを構築する前に、固定★/☆/明などの入力同士や設定と矛盾する箇所を検出する。
    # ここで矛盾が見つかった場合はソルバーを実行せず、原因を特定できる警告とともに
    # 補完前の入力をそのまま返す。
    def _fmt(s: int, d: int, message: str) -> str:
        return f"職員{staff_ids[s]}: {d + 1}日 {message}"

    conflict_warnings: List[str] = []

    # 通常の夜勤候補外に固定★/☆がある場合は、例外勤務として採用する。
    # 空欄セルに対する自動配置は、下の制約で従来どおり候補内に限定する。
    for s in range(staff_count):
        for d in range(day_count):
            fixed_type = fixed_types[s][d]
            if fixed_type == "leader_night":
                if s >= night_eligible_count:
                    warnings.append(
                        _fmt(
                            s,
                            d,
                            f"夜勤可能人数（上から{night_eligible_count}人まで）の対象外ですが、"
                            "固定のリーダー夜勤（★）を例外として採用します。",
                        )
                    )
                elif s >= night_leader_count:
                    warnings.append(
                        _fmt(
                            s,
                            d,
                            f"夜勤リーダー可能人数（上から{night_leader_count}人まで）の対象外ですが、"
                            "固定のリーダー夜勤（★）を例外として採用します。",
                        )
                    )
            elif fixed_type == "pair_night" and s >= night_eligible_count:
                warnings.append(
                    _fmt(
                        s,
                        d,
                        f"夜勤可能人数（上から{night_eligible_count}人まで）の対象外ですが、"
                        "固定の夜勤（☆）を例外として採用します。",
                    )
                )

    # 固定夜勤の翌日・翌々日に、夜勤3日セットと矛盾する固定値がある。
    for s in range(staff_count):
        for d in range(day_count):
            if fixed_types[s][d] not in {"leader_night", "pair_night"}:
                continue
            mark = normalized[s][d]
            if d + 1 < day_count and fixed_types[s][d + 1] not in {"blank", "after"}:
                conflict_warnings.append(
                    _fmt(
                        s,
                        d,
                        f"固定夜勤（{mark}）の翌日（{d + 2}日）に固定「{normalized[s][d + 1]}」"
                        "が入力されており、夜勤明け（明）と矛盾します。",
                    )
                )
            if d + 2 < day_count and fixed_types[s][d + 2] not in {"blank", "off"}:
                conflict_warnings.append(
                    _fmt(
                        s,
                        d,
                        f"固定夜勤（{mark}）の翌々日（{d + 3}日）に固定「{normalized[s][d + 2]}」"
                        "が入力されており、公休と矛盾します。",
                    )
                )

    # 固定夜勤の回数が月間夜勤上限を超えている。
    for s in range(staff_count):
        fixed_night_count = sum(
            1 for d in range(day_count) if fixed_types[s][d] in {"leader_night", "pair_night"}
        )
        if fixed_night_count > max_night_shifts:
            conflict_warnings.append(
                f"職員{staff_ids[s]}: 固定夜勤の回数が{fixed_night_count}回あり、"
                f"月間夜勤上限（{max_night_shifts}回）を超えています。"
            )

    # 同じ日に固定★または固定☆が2人以上いる。
    for d in range(day_count):
        leader_fixed = [s for s in range(staff_count) if fixed_types[s][d] == "leader_night"]
        pair_fixed = [s for s in range(staff_count) if fixed_types[s][d] == "pair_night"]
        if len(leader_fixed) > 1:
            names = "、".join(f"職員{staff_ids[s]}" for s in leader_fixed)
            conflict_warnings.append(
                f"{d + 1}日: 固定★が{len(leader_fixed)}人（{names}）入力されています。1日1人にしてください。"
            )
        if len(pair_fixed) > 1:
            names = "、".join(f"職員{staff_ids[s]}" for s in pair_fixed)
            conflict_warnings.append(
                f"{d + 1}日: 固定☆が{len(pair_fixed)}人（{names}）入力されています。1日1人にしてください。"
            )

    # 同じ日（日曜以外）に固定「7b」が2人以上いる（7b は日曜以外1日1人）。
    for d in range(day_count):
        if calendar.weekday(year, month, d + 1) == 6:  # 日曜
            continue
        seven_b_fixed = [
            s for s in range(staff_count) if normalized[s][d] == DAY_SHIFT_7B
        ]
        if len(seven_b_fixed) > 1:
            names = "、".join(f"職員{staff_ids[s]}" for s in seven_b_fixed)
            conflict_warnings.append(
                f"{d + 1}日: 固定7bが{len(seven_b_fixed)}人（{names}）入力されています。1日1人にしてください。"
            )

    # 月途中の固定「明」の前日が、夜勤になり得ない固定値になっている。
    for s in range(staff_count):
        for d in range(day_count):
            if d == 0 or fixed_types[s][d] != "after":
                continue
            prev_type = fixed_types[s][d - 1]
            if prev_type not in {"blank", "leader_night", "pair_night"}:
                conflict_warnings.append(
                    _fmt(
                        s,
                        d,
                        f"固定の明けですが、前日（{d}日）が固定「{normalized[s][d - 1]}」"
                        "で夜勤になり得ないため矛盾しています。",
                    )
                )

    # 夜勤（★/☆）を置ける候補がいない日を検出する。
    # 空欄セルが夜勤セットを開始できる必要条件: 当日が空欄、翌日が空欄/明、
    # 翌々日が空欄/休（月末をまたぐ場合は当該チェック不要）。
    def _night_open(s: int, d: int) -> bool:
        if fixed_types[s][d] != "blank":
            return False
        if d + 1 < day_count and fixed_types[s][d + 1] not in {"blank", "after"}:
            return False
        if d + 2 < day_count and fixed_types[s][d + 2] not in {"blank", "off"}:
            return False
        return True

    for d in range(day_count):
        star_capable = any(
            fixed_types[s][d] == "leader_night" for s in range(staff_count)
        ) or any(
            _night_open(s, d) for s in range(night_leader_count)
        )
        if not star_capable:
            conflict_warnings.append(
                f"{d + 1}日: 夜勤リーダー候補（上から{night_leader_count}人）の誰も★に入れません。"
                "固定入力または夜勤リーダー可能人数を見直してください。"
            )
        night_capable = sum(
            1
            for s in range(staff_count)
            if fixed_types[s][d] in {"leader_night", "pair_night"}
        ) + sum(
            1
            for s in range(night_eligible_count)
            if _night_open(s, d)
        )
        if night_capable < 2:
            conflict_warnings.append(
                f"{d + 1}日: 夜勤可能候補（上から{night_eligible_count}人）のうち夜勤（★/☆）に"
                f"入れるのが{night_capable}人しかいません（毎日★1人＋☆1人の2人が必要です）。"
                "固定入力または夜勤可能人数を見直してください。"
            )

    # 日勤・夜勤を担える人数が足りない日がないか、単純な人数勘定で確認する。
    # （固定の休み・明けなどで埋まっているスタッフは日勤にも夜勤にも入れない）
    for d in range(day_count):
        fixed_other_count = sum(
            1 for s in range(staff_count) if fixed_types[s][d] == "fixed_other"
        )
        available = sum(
            1
            for s in range(staff_count)
            if fixed_types[s][d] in {"blank", "day", "leader_night", "pair_night"}
        )
        needed = max(0, day_required_count - fixed_other_count) + 2
        if available < needed:
            conflict_warnings.append(
                f"{d + 1}日: 日勤{day_required_count}人と夜勤2人を確保できません"
                f"（配置可能 {available}人 / 必要 {needed}人。固定の休み・明けが多すぎる可能性があります）。"
            )

    # 月全体の人数勘定（厳密ではない下限チェック）。
    # 休みは最低 max(off_target, 固定off数) で、連勤制限などにより実際には
    # さらに増え得るため、これは楽観的な（勤務コマ数を多めに見積もる）下限チェック。
    # 夜勤2人/日＋明け（2日目以降2人/日）＋日勤必要人数＋固定日勤扱いセルの
    # 合計を下回る場合は勤務表を作成できない。
    total_work_cells = sum(
        day_count
        - max(
            off_target,
            sum(1 for d in range(day_count) if fixed_types[s][d] == "off"),
        )
        for s in range(staff_count)
    )
    total_fixed_other = sum(
        1
        for s in range(staff_count)
        for d in range(day_count)
        if fixed_types[s][d] == "fixed_other"
    )
    required_work_cells = 2 * day_count + 2 * max(0, day_count - 1) + total_fixed_other
    for d in range(day_count):
        fixed_other_count = sum(
            1 for s in range(staff_count) if fixed_types[s][d] == "fixed_other"
        )
        required_work_cells += max(0, day_required_count - fixed_other_count)
    if total_work_cells < required_work_cells:
        conflict_warnings.append(
            f"人員不足: 1か月の勤務可能コマ数 {total_work_cells}"
            f"（{staff_count}人、各 {day_count}日 − 休み（最低{off_target}日、固定休が多い場合はその日数））に対し、"
            f"夜勤・明け・日勤で最低 {required_work_cells} コマ必要です。"
        )

    if conflict_warnings:
        return pre_completion_normalized, conflict_warnings, list(empty_day_leaders)

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

    # 月初の固定「明」（前月末の夜勤セットの持ち越し）は、2日目が空欄なら「公」を補完する。
    for s in range(staff_count):
        if fixed_types[s][0] != "after":
            continue
        if day_count > 1 and fixed_types[s][1] == "blank":
            fixed_types[s][1] = "off"
            normalized[s][1] = HOLIDAY

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
    is_day = {
        (s, d): model.NewBoolVar(f"day_{s}_{d}")
        for s in range(staff_count)
        for d in range(day_count)
    }
    # 7b は日勤の一種（人の属性ではなく日ごとの割り当てとしてソルバーが選ぶ）
    is_7b = {
        (s, d): model.NewBoolVar(f"7b_{s}_{d}")
        for s in range(staff_count)
        for d in range(day_count)
    }
    # 日勤リーダー（毎日1人、日勤リーダー候補=上から day_leader_count 人から選ぶ）
    is_day_leader = {
        (s, d): model.NewBoolVar(f"day_leader_{s}_{d}")
        for s in range(day_leader_count)
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
                    is_day[s, d],
                ]
            )

    fixed_map = {
        "blank": is_blank,
        "off": is_off,
        "after": is_after,
        "leader_night": is_leader,
        "pair_night": is_pair,
        "day": is_day,
        # 委/研など日勤扱いの固定セルはソルバー上は空欄扱いにし、前日夜勤の禁止は
        # 「固定セルが夜勤セットと衝突するなら、その前日は夜勤不可」の制約側で担保する。
        # 日勤必要人数のカウントには定数として加算する。
        "fixed_other": is_blank,
    }
    for s in range(staff_count):
        for d in range(day_count):
            fixed_type = fixed_types[s][d]
            if fixed_type == "blank":
                # 空欄は残さない: fixed_other 以外のセルは
                # day/off/after/leader/pair のいずれかに確定させる。
                model.Add(is_blank[s, d] == 0)
                continue
            model.Add(fixed_map[fixed_type][s, d] == 1)

    # 夜勤可能人数外は夜勤に入れない。
    for s in range(night_eligible_count, staff_count):
        for d in range(day_count):
            if fixed_types[s][d] != "leader_night":
                model.Add(is_leader[s, d] == 0)
            if fixed_types[s][d] != "pair_night":
                model.Add(is_pair[s, d] == 0)

    # 夜勤リーダー可能人数外は ★ に入れない。
    for s in range(night_leader_count, staff_count):
        for d in range(day_count):
            if fixed_types[s][d] != "leader_night":
                model.Add(is_leader[s, d] == 0)

    # 毎日 1 人の ★ と 1 人の ☆ を配置。
    for d in range(day_count):
        model.Add(sum(is_leader[s, d] for s in range(staff_count)) == 1)
        model.Add(sum(is_pair[s, d] for s in range(staff_count)) == 1)

    # 日勤配置: 毎日（日曜含む）日勤を day_required_count 人以上確保する。
    # 委/研など日勤扱いの固定セル（fixed_other）は、フロントの日勤計の集計に合わせて
    # 定数としてカウントに含める。
    for d in range(day_count):
        fixed_other_count = sum(
            1 for s in range(staff_count) if fixed_types[s][d] == "fixed_other"
        )
        model.Add(
            sum(is_day[s, d] for s in range(staff_count)) + fixed_other_count
            >= day_required_count
        )

    # 日勤リーダー: 毎日1人。リーダーは実際の日勤（is_day、固定の日/7b 含む）で
    # あること。fixed_other はリーダーには数えない。
    for d in range(day_count):
        model.Add(sum(is_day_leader[s, d] for s in range(day_leader_count)) == 1)
    for s in range(day_leader_count):
        for d in range(day_count):
            model.Add(is_day_leader[s, d] <= is_day[s, d])

    # 7b の割り当て: 7b は日勤の一種で、日曜以外は毎日ちょうど1人。
    # ソルバーは日曜に 7b を置かない（固定「7b」はそのまま尊重する）。
    for s in range(staff_count):
        for d in range(day_count):
            model.Add(is_7b[s, d] <= is_day[s, d])
            if normalized[s][d] == DAY_SHIFT_7B:
                # 固定「7b」: 日勤かつ 7b に固定（is_day == 1 は fixed_map で固定済み）
                model.Add(is_7b[s, d] == 1)
            elif normalized[s][d] == DAY_SHIFT:
                # 固定「日」: 出力の文字が変わらないよう 7b にしない
                model.Add(is_7b[s, d] == 0)
            elif calendar.weekday(year, month, d + 1) == 6:  # 日曜
                model.Add(is_7b[s, d] == 0)
    for d in range(day_count):
        if calendar.weekday(year, month, d + 1) == 6:  # 日曜
            continue
        model.Add(sum(is_7b[s, d] for s in range(staff_count)) == 1)

    # 公休日数: 目標（off_target）は最低限。各スタッフの休み（固定の公・希・有＋
    # ソルバー配置の公）の合計を max(目標, 固定 off 数) 以上にする（下限のみ）。
    # 等式にしないのは、固定休の並びによっては5連勤制限などのハード制約を満たす
    # ために最低ラインを超える休みが必要になるため（等式だと INFEASIBLE になる）。
    # 不要な水増しは下の extra_off ペナルティで抑える。
    min_off_by_staff: List[int] = []
    extra_off_vars = []
    for s in range(staff_count):
        fixed_off_count = sum(
            1 for d in range(day_count) if fixed_types[s][d] == "off"
        )
        min_off = max(off_target, fixed_off_count)
        min_off_by_staff.append(min_off)
        off_sum = sum(is_off[s, d] for d in range(day_count))
        model.Add(off_sum >= min_off)
        extra_off = model.NewIntVar(0, day_count, f"extra_off_{s}")
        model.Add(extra_off == off_sum - min_off)
        extra_off_vars.append(extra_off)

    # 夜勤3日セット: 夜勤 -> 明け -> 公休
    for s in range(staff_count):
        for d in range(day_count):
            if d + 1 < day_count:
                model.AddImplication(is_leader[s, d], is_after[s, d + 1])
                model.AddImplication(is_pair[s, d], is_after[s, d + 1])
            if d + 2 < day_count:
                model.AddImplication(is_leader[s, d], is_off[s, d + 2])
                model.AddImplication(is_pair[s, d], is_off[s, d + 2])

    # 明けは前日夜勤の翌日のみ。ただし月初の固定明けは前月またぎとして許容する。
    # 月途中の固定明けは、前日に夜勤（★/☆）が入ることを制約として強制する
    # （前日が夜勤になり得ない固定値の場合は事前バリデーションで検出済み）。
    for s in range(staff_count):
        for d in range(day_count):
            if fixed_types[s][d] == "after":
                if d > 0:
                    model.Add(is_after[s, d] <= is_leader[s, d - 1] + is_pair[s, d - 1])
                continue
            if d == 0:
                model.Add(is_after[s, d] == 0)
            else:
                model.Add(is_after[s, d] <= is_leader[s, d - 1] + is_pair[s, d - 1])

    # 公休は一般の休みとして自由に配置できる（「夜勤の2日後のみ」の制約は撤廃）。
    # 夜勤セットの implication（夜勤→翌々日公）は上で維持している。

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

    # 連続勤務制限（緩い方を先行導入）: 連続する任意の6日間で勤務は5日まで
    # （5連勤まで）。勤務 = 日勤 + 夜勤 + 明け + 固定日勤扱い（委/研など、定数1）。
    for s in range(staff_count):
        work_terms = []
        for d in range(day_count):
            if fixed_types[s][d] == "fixed_other":
                work_terms.append(1)
            else:
                work_terms.append(
                    is_day[s, d] + is_after[s, d] + is_leader[s, d] + is_pair[s, d]
                )
        for d in range(day_count - 5):
            model.Add(sum(work_terms[d:d + 6]) <= 5)

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
        objective_terms.append(night_spread * 1000)

    # 各スタッフの夜勤間隔均等化（月を3ブロックに分割してブロック間ばらつきを最小化）
    K = 3
    for s in range(night_eligible_count):
        block_ns = []
        for k in range(K):
            start = k * (day_count // K)
            end = (k + 1) * (day_count // K) if k < K - 1 else day_count
            bn = model.NewIntVar(0, max_night_shifts, f"block_n_{s}_{k}")
            model.Add(bn == sum(is_leader[s, d] + is_pair[s, d] for d in range(start, end)))
            block_ns.append(bn)
        max_bn = model.NewIntVar(0, max_night_shifts, f"max_bn_{s}")
        min_bn = model.NewIntVar(0, max_night_shifts, f"min_bn_{s}")
        model.AddMaxEquality(max_bn, block_ns)
        model.AddMinEquality(min_bn, block_ns)
        block_spread = model.NewIntVar(0, max_night_shifts, f"block_spread_{s}")
        model.Add(block_spread == max_bn - min_bn)
        objective_terms.append(block_spread * 50)

    # 公休の分散（ソフト）: 月を3ブロックに分割し、各スタッフの公休数の
    # ブロック間ばらつきを最小化する。重み10は既存の重み
    # （1000/100/50/-30）より小さくし、夜勤配置の判断を崩さない。
    for s in range(staff_count):
        block_offs = []
        for k in range(K):
            start = k * (day_count // K)
            end = (k + 1) * (day_count // K) if k < K - 1 else day_count
            bo = model.NewIntVar(0, day_count, f"block_off_{s}_{k}")
            model.Add(bo == sum(is_off[s, d] for d in range(start, end)))
            block_offs.append(bo)
        max_bo = model.NewIntVar(0, day_count, f"max_bo_{s}")
        min_bo = model.NewIntVar(0, day_count, f"min_bo_{s}")
        model.AddMaxEquality(max_bo, block_offs)
        model.AddMinEquality(min_bo, block_offs)
        off_spread = model.NewIntVar(0, day_count, f"off_spread_{s}")
        model.Add(off_spread == max_bo - min_bo)
        objective_terms.append(off_spread * 10)

    # 最低ラインを超えた休み1日につき重み50のペナルティ。
    # 重み50の根拠: 公休ブロック分散（重み10）や希望休ボーナス（-30）で得をする
    # ための休みの水増しを防ぎつつ、5連勤制限などのハード制約が必要とする追加休は
    # 妨げない（ハード制約は目的関数の重みと無関係に常に優先される）。
    for s in range(staff_count):
        objective_terms.append(extra_off_vars[s] * 50)

    # 7b の公平化（ソフト）: スタッフごとの月間7b回数の max - min を重み5で最小化。
    # 重み5は既存の重み（1000/100/50/10/-30）より小さくし、他の配置判断を崩さない。
    seven_b_counts = []
    for s in range(staff_count):
        cnt = model.NewIntVar(0, day_count, f"seven_b_count_{s}")
        model.Add(cnt == sum(is_7b[s, d] for d in range(day_count)))
        seven_b_counts.append(cnt)
    max_7b = model.NewIntVar(0, day_count, "max_7b")
    min_7b = model.NewIntVar(0, day_count, "min_7b")
    model.AddMaxEquality(max_7b, seven_b_counts)
    model.AddMinEquality(min_7b, seven_b_counts)
    seven_b_spread = model.NewIntVar(0, day_count, "seven_b_spread")
    model.Add(seven_b_spread == max_7b - min_7b)
    objective_terms.append(seven_b_spread * 5)

    # 希望休（希）は夜勤セット3日目の公休を兼ねてよい（確定仕様）。
    # 「希」の2日前が空欄なら、そこに夜勤を置く配置をボーナスで優先する（ソフト条件）。
    # 重み30は既存の重み（ペア候補違反1000・ばらつき100・ブロック分散50）より小さくし、
    # 公平性を崩してまで兼ねることはしない。対象は「希」のみ（公・有などは対象外）。
    for s in range(night_eligible_count):
        for d in range(day_count):
            if normalized[s][d] != "希":
                continue
            if d - 2 >= 0 and fixed_types[s][d - 2] == "blank":
                objective_terms.append(-30 * (is_leader[s, d - 2] + is_pair[s, d - 2]))

    # ☆ はできるだけリーダー候補外から選ぶ。
    leader_pair_penalty = sum(
        is_pair[s, d]
        for s in range(night_leader_count)
        for d in range(day_count)
    )
    objective_terms.append(leader_pair_penalty * 200)

    model.Minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    solver.parameters.num_search_workers = 8
    solver.parameters.log_search_progress = False

    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        warnings.append("条件を満たす勤務表が見つかりませんでした。設定または固定希望を確認してください。")
        total_capacity = night_eligible_count * max_night_shifts
        required_nights = day_count * 2
        if total_capacity < required_nights:
            warnings.append(
                f"夜勤要員不足: 必要 {required_nights} 回、最大 {total_capacity} 回です。"
            )
        # 日勤必要人数が原因になり得るかの単純なヒント
        # （1日あたり: 日勤 day_required_count 人 + 夜勤2人 + 明け2人）
        daily_min_staff = day_required_count + 2 + 2
        if staff_count < daily_min_staff:
            warnings.append(
                f"日勤要員不足の可能性: 1日あたり日勤{day_required_count}人＋夜勤2人＋明け2人"
                f"（計{daily_min_staff}人）が必要ですが、職員数は{staff_count}人です。"
            )
        return pre_completion_normalized, warnings, list(empty_day_leaders)

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
            elif solver.Value(is_day[s, d]):
                # 7b が立っていれば「7b」、それ以外の日勤は「日」。
                result[s][d] = DAY_SHIFT_7B if solver.Value(is_7b[s, d]) else DAY_SHIFT
            else:
                result[s][d] = BLANK

    # 日勤リーダー（staff_id）を日ごとに抽出する。
    day_leaders: List[Optional[str]] = [None] * day_count
    for d in range(day_count):
        for s in range(day_leader_count):
            if solver.Value(is_day_leader[s, d]):
                day_leaders[d] = staff_ids[s]
                break

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

    # 公休日数の検算（目標は最低限。固定休による超過は許容するため未満のみ警告し、
    # 最低ラインを超えた場合は理由が分かる情報警告を出す）
    for s in range(staff_count):
        off_total = sum(
            1 for d in range(day_count) if result[s][d] in OFF_TYPES
        )
        if off_total < off_target:
            warnings.append(
                f"職員{staff_ids[s]}: 休みが {off_total} 日（最低 {off_target} 日）です。"
            )
        elif off_total > min_off_by_staff[s]:
            warnings.append(
                f"職員{staff_ids[s]}: 休みが{off_total}日です"
                f"（最低{min_off_by_staff[s]}日。連勤制限などのため追加されました）。"
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

    return result, warnings, day_leaders
