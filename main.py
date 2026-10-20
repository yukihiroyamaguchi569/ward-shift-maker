"""
病棟勤務表 自動作成システム - FastAPI サーバー
"""

import calendar
import os
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from excel_handler import UnsupportedExcelError, read_excel, write_excel
from solver import SettingsValidationError, generate_shift, precheck_schedule

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="病棟勤務表 自動作成システム")

# 静的ファイルの配信
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


# =========================================================
# リクエストモデル
# =========================================================


class GenerateRequest(BaseModel):
    staff_ids: List[str]
    dates: List[Any]
    schedule: List[List[str]]
    settings: Dict[str, Any]


class DownloadRequest(BaseModel):
    staff_ids: List[str]
    dates: List[Any]
    schedule: List[List[str]]
    original_schedule: Optional[List[List[str]]] = None
    day_leaders: Optional[List[Optional[str]]] = None


# =========================================================
# ルート
# =========================================================


@app.get("/")
async def root():
    """トップページ"""
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))


@app.post("/api/upload")
async def upload_excel(file: UploadFile = File(...)):
    """
    エクセルファイルをアップロードして解析

    Returns:
        { staff_ids, dates, schedule }
    """
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=400,
            detail="xlsx形式のファイルをアップロードしてください",
        )

    try:
        contents = await file.read()
        data = read_excel(contents)
    except UnsupportedExcelError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"ファイルの読み込みに失敗しました: {str(e)}",
        )

    if not data["staff_ids"]:
        raise HTTPException(
            status_code=400,
            detail="職員データが見つかりません。フォーマットを確認してください。",
        )

    return data


def _require_settings(settings: Dict[str, Any]) -> None:
    """必須の設定キーが揃っているか確認する。"""
    required_keys = [
        "year",
        "month",
        "day_leader_count",
        "night_leader_count",
        "night_eligible_count",
        "max_night_shifts",
    ]
    for key in required_keys:
        if key not in settings:
            raise HTTPException(
                status_code=400,
                detail=f"設定が不足しています: {key}",
            )


def _parse_year_month(settings: Dict[str, Any]) -> Tuple[int, int]:
    try:
        year = int(settings["year"])
        month = int(settings["month"])
    except (TypeError, ValueError):
        raise SettingsValidationError("year と month は整数で指定してください。")
    if year < 1:
        raise SettingsValidationError("year は1以上にしてください。")
    if not 1 <= month <= 12:
        raise SettingsValidationError("month は1以上12以下にしてください。")
    return year, month


@app.post("/api/generate")
async def generate(request: GenerateRequest):
    """
    シフトを自動生成

    Returns:
        { schedule, warnings, day_leaders }
    """
    _require_settings(request.settings)

    try:
        year, month = _parse_year_month(request.settings)
        schedule, warnings, day_leaders = generate_shift(
            staff_ids=request.staff_ids,
            year=year,
            month=month,
            schedule=request.schedule,
            settings=request.settings,
        )
    except SettingsValidationError as e:
        raise HTTPException(status_code=400, detail=f"設定エラー: {e}")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"シフト生成中にエラーが発生しました: {str(e)}",
        )

    return {"schedule": schedule, "warnings": warnings, "day_leaders": day_leaders}


@app.post("/api/check")
async def check(request: GenerateRequest):
    """
    シフト作成前の事前チェック（ソルバーは実行しない）

    Returns:
        { conflicts, notices }
    """
    _require_settings(request.settings)

    try:
        year, month = _parse_year_month(request.settings)
        result = precheck_schedule(
            staff_ids=request.staff_ids,
            year=year,
            month=month,
            schedule=request.schedule,
            settings=request.settings,
        )
    except SettingsValidationError as e:
        raise HTTPException(status_code=400, detail=f"設定エラー: {e}")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"事前チェック中にエラーが発生しました: {str(e)}",
        )

    return {"conflicts": result.conflict_warnings, "notices": result.warnings}


@app.post("/api/download")
async def download_excel(request: DownloadRequest):
    """
    勤務表をエクセルファイルとしてダウンロード
    """
    try:
        excel_bytes = write_excel(
            staff_ids=request.staff_ids,
            dates=request.dates,
            schedule=request.schedule,
            original_schedule=request.original_schedule,
            day_leaders=request.day_leaders,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"エクセル生成中にエラーが発生しました: {str(e)}",
        )

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="shift_schedule.xlsx"'
        },
    )


# =========================================================
# 起動
# =========================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
