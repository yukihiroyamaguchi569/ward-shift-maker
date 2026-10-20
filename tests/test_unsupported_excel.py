import asyncio
import io
import unittest

from fastapi import HTTPException
from starlette.datastructures import UploadFile

from excel_handler import UnsupportedExcelError, read_excel, write_excel
from main import upload_excel

OLE_HEADER = bytes.fromhex("D0CF11E0A1B11AE1")
PASSWORD_BYTES = OLE_HEADER + b"\x00" * 16 + "EncryptionInfo".encode("utf-16-le")
XLS_BYTES = OLE_HEADER + b"\x00" * 64
BROKEN_BYTES = b"this is neither zip nor ole"

PASSWORD_MESSAGE = (
    "Excel にパスワードがかかっていると読み込めません。"
    "パスワードを外して保存し直してから読み込んでください。"
)
XLS_MESSAGE = (
    "古い形式（.xls）のファイルは読み込めません。"
    "Excel で xlsx 形式で保存し直してください。"
)
FAILED_PREFIX = "ファイルの読み込みに失敗しました: "


def upload(contents, filename="test.xlsx"):
    """upload_excel を直接呼び、(status_code, detail または戻り値) を返す"""
    file = UploadFile(file=io.BytesIO(contents), filename=filename)
    try:
        return 200, asyncio.run(upload_excel(file))
    except HTTPException as e:
        return e.status_code, e.detail


class ReadExcelTests(unittest.TestCase):
    def test_password_protected_raises_password_message(self):
        with self.assertRaises(UnsupportedExcelError) as ctx:
            read_excel(PASSWORD_BYTES)
        self.assertEqual(str(ctx.exception), PASSWORD_MESSAGE)

    def test_ole_without_encryption_info_raises_xls_message(self):
        with self.assertRaises(UnsupportedExcelError) as ctx:
            read_excel(XLS_BYTES)
        self.assertEqual(str(ctx.exception), XLS_MESSAGE)

    def test_valid_xlsx_is_still_readable(self):
        data = write_excel(["1", "2"], [1, 2, 3], [["日", "", "公休"], ["", "夜", ""]])
        result = read_excel(data)
        self.assertEqual(result["staff_ids"], ["1", "2"])
        self.assertEqual(result["dates"], [1, 2, 3])


class UploadTests(unittest.TestCase):
    def test_password_protected_returns_message_without_prefix(self):
        status, detail = upload(PASSWORD_BYTES)
        self.assertEqual(status, 400)
        self.assertEqual(detail, PASSWORD_MESSAGE)

    def test_xls_returns_message_without_prefix(self):
        status, detail = upload(XLS_BYTES, "old.xls")
        self.assertEqual(status, 400)
        self.assertEqual(detail, XLS_MESSAGE)

    def test_broken_bytes_keep_failure_prefix(self):
        status, detail = upload(BROKEN_BYTES)
        self.assertEqual(status, 400)
        self.assertTrue(detail.startswith(FAILED_PREFIX))

    def test_valid_xlsx_is_accepted(self):
        data = write_excel(["1"], [1, 2], [["日", ""]])
        status, body = upload(data)
        self.assertEqual(status, 200)
        self.assertEqual(body["staff_ids"], ["1"])


if __name__ == "__main__":
    unittest.main()
