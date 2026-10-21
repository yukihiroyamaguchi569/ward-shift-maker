"""画面（static/app.js）の E2E テスト。

実サーバー（uvicorn）を起動し、ヘッドレス Chromium で操作する。
入力の xlsx はテスト内で合成する（実データは使わない）。
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from io import BytesIO

from openpyxl import Workbook
from playwright.sync_api import sync_playwright

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DAY_COUNT = 30  # 2026年11月
MONTH = "2026-11"
SERVER_START_TIMEOUT_SECONDS = 30
DIALOG_WAIT_SECONDS = 30
UI_TIMEOUT_MS = 60000  # 生成は制限時間 10 秒＋余裕

PRECHECK_MESSAGE = "このままでは勤務表を作成できません。"
PASSWORD_WARNING = "Excel にパスワードがかかっていると読み込めません。"
PASSWORD_BYTES = (
    bytes.fromhex("D0CF11E0A1B11AE1")
    + b"\x00" * 16
    + "EncryptionInfo".encode("utf-16-le")
)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_xlsx(staff_count, fixed_cells=None):
    """1行目に日付 1..30、A列に職員番号の勤務表を作る。fixed_cells は {(職員index, 日index): 値}"""
    wb = Workbook()
    ws = wb.active
    ws.cell(1, 1, "職員番号")
    for d in range(DAY_COUNT):
        ws.cell(1, 2 + d, d + 1)
    for s in range(staff_count):
        ws.cell(2 + s, 1, str(s + 1))
    for (s, d), value in (fixed_cells or {}).items():
        ws.cell(2 + s, 2 + d, value)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def overbooked_day_29():
    # 17人中、29日に 委 が1人、公 が11人 → 配置可能が足りない（tests/test_precheck.py と同じ入力）
    cells = {(0, 28): "委"}
    for s in range(1, 12):
        cells[(s, 28)] = "公"
    return make_xlsx(17, cells)


def day_leader_blocked():
    # 10日: 日勤リーダー候補（上から3人）が 公・委・休 で、誰も日勤に入れない（tests/test_diagnosis.py と同じ入力）
    return make_xlsx(19, {(0, 9): "公", (1, 9): "委", (2, 9): "休"})


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        port = free_port()
        cls.base_url = f"http://127.0.0.1:{port}"
        env = {**os.environ, "SOLVER_TIME_LIMIT_SECONDS": "10"}
        cls.server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--port", str(port)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        cls.playwright = None
        cls.browser = None
        try:
            cls.wait_for_server()
            cls.playwright = sync_playwright().start()
            cls.browser = cls.playwright.chromium.launch()
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def wait_for_server(cls):
        deadline = time.monotonic() + SERVER_START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if cls.server.poll() is not None:
                raise RuntimeError("uvicorn が起動直後に終了しました")
            try:
                urllib.request.urlopen(cls.base_url + "/", timeout=2).close()
                return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("uvicorn が時間内に応答しませんでした")

    @classmethod
    def tearDownClass(cls):
        if cls.browser:
            cls.browser.close()
        if cls.playwright:
            cls.playwright.stop()
        cls.server.terminate()
        try:
            cls.server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait()

    def setUp(self):
        # テストごとに新しいコンテキスト（localStorage を持ち越さない）
        self.context = self.browser.new_context(accept_downloads=True)
        self.addCleanup(self.context.close)
        # 外部 CDN（Tailwind・フォント）には出ない。画面の動作に必要なのは自サーバーの資源だけ
        self.context.route(
            "**/*",
            lambda route: route.continue_()
            if route.request.url.startswith(self.base_url)
            else route.abort(),
        )
        self.context.set_default_timeout(UI_TIMEOUT_MS)
        self.page = self.context.new_page()
        self.dialogs = []
        self.prompt_answer = ""
        self.page.on("dialog", self.on_dialog)
        self.page.goto(self.base_url + "/", wait_until="domcontentloaded")
        self.page.fill("#targetMonth", MONTH)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def on_dialog(self, dialog):
        self.dialogs.append(dialog.message)
        if dialog.type == "prompt":
            dialog.accept(self.prompt_answer)
        else:
            dialog.accept()

    def upload(self, contents, filename="勤務表.xlsx"):
        self.page.set_input_files(
            "#fileInput",
            files=[{"name": filename, "mimeType": "application/octet-stream", "buffer": contents}],
        )

    def warnings_text(self):
        return self.page.locator("#warningsList").inner_text()

    def wait_for_dialog(self):
        deadline = time.monotonic() + DIALOG_WAIT_SECONDS
        while not self.dialogs and time.monotonic() < deadline:
            self.page.wait_for_timeout(100)
        self.assertEqual(len(self.dialogs), 1, self.dialogs)

    def test_upload_generate_and_download(self):
        self.upload(make_xlsx(19))
        self.page.locator("#staffCount", has_text="19名 × 30日").wait_for()
        # 職員 19 行＋日勤計・夜勤計の 2 行
        self.assertEqual(self.page.locator("#scheduleTable tbody tr").count(), 19 + 2)
        self.assertNotIn("公休", self.page.locator("#scheduleTable tbody").inner_text())

        self.page.click("#generateBtn")
        self.page.locator("#generateBtn", has_text="再作成").wait_for()
        self.assertIn("公休", self.page.locator("#scheduleTable tbody").inner_text())
        self.assertTrue(self.page.locator("#downloadBtn").is_enabled())

        with self.page.expect_download() as info:
            self.page.click("#downloadBtn")
        path = os.path.join(self.tmp.name, "out.xlsx")
        info.value.save_as(path)
        with open(path, "rb") as f:
            self.assertEqual(f.read(2), b"PK")  # xlsx は zip

    def test_precheck_blocks_overbooked_day(self):
        self.upload(overbooked_day_29())
        self.page.locator("#warningsList li", has_text=PRECHECK_MESSAGE).wait_for()
        self.assertIn("29日", self.warnings_text())

    def test_diagnosis_shows_cause_when_unsolvable(self):
        self.page.fill("#dayLeaderCount", "3")
        self.upload(day_leader_blocked())
        self.page.click("#generateBtn")
        self.page.locator(
            "#warningsList li", has_text="10日: 日勤リーダーを置けません。"
        ).wait_for()
        self.assertIn("条件を満たす勤務表が見つかりませんでした。", self.warnings_text())
        self.assertTrue(self.page.locator("#generateBtn").is_enabled())

    def test_password_protected_file_shows_message(self):
        self.upload(PASSWORD_BYTES, "パスワード付き.xlsx")
        # 読み込み失敗は alert で知らせる
        self.wait_for_dialog()
        self.assertIn(PASSWORD_WARNING, self.dialogs[0])
        self.assertTrue(self.page.locator("#generateBtn").is_disabled())

    def assert_generate_failure_recovers(self, handler):
        self.upload(make_xlsx(19))
        self.page.locator("#staffCount", has_text="19名 × 30日").wait_for()
        self.page.route("**/api/generate", handler)
        self.page.click("#generateBtn")
        self.wait_for_dialog()
        # 固まらず、もう一度押せる
        self.page.locator("#loading.panel-hidden").wait_for(state="attached")
        self.assertTrue(self.page.locator("#generateBtn").is_enabled())
        self.assertEqual(self.page.locator("#generateBtn").inner_text(), "シフト作成")
        self.assertTrue(self.page.locator("#downloadBtn").is_disabled())

    def test_generate_http_500_recovers(self):
        self.assert_generate_failure_recovers(
            lambda route: route.fulfill(
                status=500,
                content_type="application/json",
                body='{"detail": "サーバーエラーです"}',
            )
        )
        self.assertIn("サーバーエラーです", self.dialogs[0])

    def test_generate_network_failure_recovers(self):
        self.assert_generate_failure_recovers(lambda route: route.abort())

    def test_sunday_day_required_preset_roundtrip(self):
        self.prompt_answer = "日曜4人"
        self.page.fill("#sundayDayRequired", "4")
        self.page.click("#presetSaveBtn")
        self.assertEqual(self.page.locator("#presetSelect").input_value(), "日曜4人")

        self.page.select_option("#presetSelect", "デフォルト")
        self.assertEqual(self.page.locator("#sundayDayRequired").input_value(), "5")

        self.page.select_option("#presetSelect", "日曜4人")
        self.assertEqual(self.page.locator("#sundayDayRequired").input_value(), "4")
        self.assertEqual(self.dialogs, ["プリセット名を入力してください:"])


if __name__ == "__main__":
    unittest.main()
