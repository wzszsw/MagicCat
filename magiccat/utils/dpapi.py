"""Windows DPAPI 加解密（ctypes 直调 CryptProtectData，无第三方依赖）。

- Windows：当前 Windows 用户级加密（凭据无法拷贝到其他机器/用户解密）。
- 非 Windows / 调用失败：降级为 base64（仅混淆，日志提示），保证跨平台可运行。
"""

from __future__ import annotations

import base64
import ctypes
import logging
from ctypes import wintypes

logger = logging.getLogger(__name__)

_PLAIN_PREFIX = "plain:"


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _crypt(encrypt: bool, data: bytes) -> bytes:
    if data == b"":
        return b""
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        raise OSError("DPAPI 仅支持 Windows")
    buf_in = ctypes.create_string_buffer(data, max(len(data), 1))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf_in, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    fn = windll.crypt32.CryptProtectData if encrypt else windll.crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    if not ok:
        raise OSError(f"DPAPI 调用失败: {ctypes.WinError()}")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        windll.kernel32.LocalFree(ctypes.cast(blob_out.pbData, wintypes.HLOCAL))


def encrypt_text(text: str) -> str:
    """加密为 base64 字符串；空串保持空串。"""
    if not text:
        return ""
    try:
        return base64.b64encode(_crypt(True, text.encode("utf-8"))).decode("ascii")
    except OSError:
        logger.warning("DPAPI 不可用，口令以 base64 降级存储（仅混淆）")
        return _PLAIN_PREFIX + base64.b64encode(text.encode("utf-8")).decode("ascii")


def decrypt_text(token: str) -> str:
    """解密 encrypt_text 的产物。"""
    if not token:
        return ""
    if token.startswith(_PLAIN_PREFIX):
        return base64.b64decode(token[len(_PLAIN_PREFIX) :]).decode("utf-8")
    return _crypt(False, base64.b64decode(token)).decode("utf-8")
