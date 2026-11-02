# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""Encrypted store for third-party API keys. Windows-only: keys are sealed
with DPAPI (current-user scope), so the DB copy is useless on another
account or machine."""

import ctypes
from ctypes import wintypes
from typing import Optional

from persistence.database import Database

RAVEN = "ravencolonial"
EDSM = "edsm"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.LocalFree.argtypes = [ctypes.c_void_p]
_kernel32.LocalFree.restype = ctypes.c_void_p


def _crypt(fn, data: bytes) -> Optional[bytes]:
    buf = ctypes.create_string_buffer(data, len(data))
    src = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = _Blob()
    if not fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        return None
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        _kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def protect(data: bytes) -> bytes:
    return _crypt(_crypt32.CryptProtectData, data)


def unprotect(blob: bytes) -> Optional[bytes]:
    return _crypt(_crypt32.CryptUnprotectData, blob)


def save_key(db: Database, service: str, name: str, key: str) -> None:
    db.execute(
        "INSERT OR REPLACE INTO push_credentials (service, name, secret) VALUES (?, ?, ?)",
        (service, name, protect(key.encode("utf-8"))),
    )


def load_key(db: Database, service: str) -> Optional[tuple[str, str]]:
    row = db.execute(
        "SELECT name, secret FROM push_credentials WHERE service = ?", (service,)
    ).fetchone()
    if not row:
        return None
    key = unprotect(bytes(row[1]))
    return None if key is None else (row[0], key.decode("utf-8"))


def clear_key(db: Database, service: str) -> None:
    db.execute("DELETE FROM push_credentials WHERE service = ?", (service,))
