"""Current-user Windows Credential Manager; no plaintext or memory fallback."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import os
import re

class CredentialStoreUnavailable(RuntimeError):
    pass

class WindowsCredentialStore:
    def __init__(self, namespace: str):
        if not re.fullmatch(r"[a-f0-9]{64}", namespace):
            raise ValueError("Invalid credential namespace")
        self.prefix = "AgentFactory/" + namespace + "/"

    def _target(self, reference):
        if not isinstance(reference, str) or not re.fullmatch(r"[a-f0-9]{32}", reference):
            raise ValueError("Invalid credential reference")
        return self.prefix + reference

    @staticmethod
    def _api():
        if os.name != "nt":
            raise CredentialStoreUnavailable("OS credential store is unavailable on this platform")
        class Credential(ctypes.Structure):
            _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]
        api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        pointer = ctypes.POINTER(Credential)
        api.CredWriteW.argtypes = [pointer, wintypes.DWORD]; api.CredWriteW.restype = wintypes.BOOL
        api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(pointer)]
        api.CredReadW.restype = wintypes.BOOL
        api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        api.CredDeleteW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]; api.CredFree.restype = None
        return api, Credential

    def put(self, reference: str, value: str):
        target = self._target(reference)
        try:
            data = value.encode("utf-8")
        except (AttributeError, UnicodeError):
            raise ValueError("Invalid credential value") from None
        if not 12 <= len(data) <= 2048 or "\x00" in value:
            raise ValueError("Invalid credential value")
        api, kind = self._api()
        blob = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        entry = kind(Type=1, TargetName=target, CredentialBlobSize=len(data),
                     CredentialBlob=blob, Persist=2, UserName="AgentFactory")
        try:
            if not api.CredWriteW(ctypes.byref(entry), 0):
                raise CredentialStoreUnavailable("OS credential write failed")
        finally:
            ctypes.memset(blob, 0, len(data))

    def get(self, reference: str) -> str:
        target = self._target(reference); api, kind = self._api()
        entry = ctypes.POINTER(kind)()
        if not api.CredReadW(target, 1, 0, ctypes.byref(entry)):
            raise CredentialStoreUnavailable("OS credential is unavailable")
        try:
            size = entry.contents.CredentialBlobSize
            if not 12 <= size <= 2048:
                raise CredentialStoreUnavailable("OS credential is unavailable")
            return ctypes.string_at(entry.contents.CredentialBlob, size).decode("utf-8")
        except UnicodeError:
            raise CredentialStoreUnavailable("OS credential is unavailable") from None
        finally:
            ctypes.memset(entry.contents.CredentialBlob, 0, entry.contents.CredentialBlobSize)
            api.CredFree(entry)

    def delete(self, reference: str):
        target = self._target(reference); api, _ = self._api()
        if not api.CredDeleteW(target, 1, 0) and ctypes.get_last_error() != 1168:
            raise CredentialStoreUnavailable("OS credential removal failed")
