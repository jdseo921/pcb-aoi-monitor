"""Secrets the station keeps outside the workspace (REQ-TRN-017; S38; ADR 0010, decision 3): a dataset store's key now,
REQ-SET-010's license key and Stage 4's MES token later. On Windows each is a generic credential in Windows Credential
Manager, saved for this computer only (CRED_PERSIST_LOCAL_MACHINE, so it never roams with a profile) and protected by
DPAPI under the Windows account the app runs as; on any other system, which runs only CI and development, a store in
memory stands behind the same three calls and forgets everything when the process ends. No secret is ever written to
the workspace, settings.json or a log."""

from __future__ import annotations

import ctypes
import sys
import threading
from typing import Protocol

STORE_PREFIX = "AOI/dataset-store/"  # then the store's UUID


class Credentials(Protocol):
    def write(self, name: str, secret: bytes) -> None: ...
    def read(self, name: str) -> bytes | None: ...
    def delete(self, name: str) -> bool: ...


class MemoryCredentials:
    """Secrets in this process's memory: for tests, CI and development on a system without Credential Manager."""

    def __init__(self) -> None:
        self._secrets: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def write(self, name: str, secret: bytes) -> None:
        with self._lock:
            self._secrets[name] = bytes(secret)

    def read(self, name: str) -> bytes | None:
        with self._lock:
            return self._secrets.get(name)

    def delete(self, name: str) -> bool:
        """True when there was a secret of that name to delete."""
        with self._lock:
            return self._secrets.pop(name, None) is not None


if sys.platform == "win32":  # the types and the DLL exist only there
    from ctypes import wintypes

    class _Credential(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    class WindowsCredentials:
        """Generic credentials in Windows Credential Manager, through advapi32 (CredWriteW, CredReadW, CredDeleteW,
        CredFree). OSError, with Windows' code, for a call that fails other than with a name not found."""

        def __init__(self) -> None:
            api = ctypes.WinDLL("advapi32", use_last_error=True)
            self._write, self._read, self._delete = api.CredWriteW, api.CredReadW, api.CredDeleteW
            self._free = api.CredFree
            self._write.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
            self._read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
            self._delete.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
            self._free.argtypes = [ctypes.c_void_p]
            for call in (self._write, self._read, self._delete):
                call.restype = wintypes.BOOL
            self._free.restype = None

        def write(self, name: str, secret: bytes) -> None:
            blob = (ctypes.c_ubyte * len(secret)).from_buffer_copy(secret)
            cred = _Credential(Type=CRED_TYPE_GENERIC, TargetName=name, Persist=CRED_PERSIST_LOCAL_MACHINE)
            cred.CredentialBlobSize = len(secret)
            cred.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
            if not self._write(ctypes.byref(cred), 0):
                raise ctypes.WinError(ctypes.get_last_error())

        def read(self, name: str) -> bytes | None:
            found = ctypes.c_void_p()
            if not self._read(name, CRED_TYPE_GENERIC, 0, ctypes.byref(found)):
                if (code := ctypes.get_last_error()) == ERROR_NOT_FOUND:
                    return None
                raise ctypes.WinError(code)
            try:
                cred = ctypes.cast(found, ctypes.POINTER(_Credential)).contents
                return ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
            finally:
                self._free(found)

        def delete(self, name: str) -> bool:
            """True when there was a credential of that name to delete."""
            if self._delete(name, CRED_TYPE_GENERIC, 0):
                return True
            if (code := ctypes.get_last_error()) == ERROR_NOT_FOUND:
                return False
            raise ctypes.WinError(code)


MEMORY = MemoryCredentials()  # one per process, so two AppContexts of one workspace in a test see the same keys


def default() -> Credentials:
    """Windows Credential Manager on Windows, else MEMORY."""
    if sys.platform == "win32":
        return WindowsCredentials()
    return MEMORY
