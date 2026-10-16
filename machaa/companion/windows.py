"""Windows-only desktop actions.

Importing this module on Linux does nothing visible. Launching Notepad,
Calculator, or File Explorer raises a clear refusal on any system that
is not Windows, so a test cannot mistake a refusal for success.
"""

from __future__ import annotations

import sys
from pathlib import Path

from machaa.companion.policy import title_is_our_notepad
from machaa.core.errors import CompanionRefused

_NOT_WINDOWS = (
    "Opening Notepad, Calculator, or File Explorer runs on your Windows PC. "
    "Machaa did not pretend that it opened."
)


def launch_app(kind: str, documents: Path) -> dict:
    """Start one fixed Windows program. The name is not a command string."""

    if sys.platform != "win32":
        raise CompanionRefused(_NOT_WINDOWS)
    import os
    import subprocess

    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    system = Path(system_root) / "System32"
    programs = {
        "notepad": system / "notepad.exe",
        "calculator": system / "calc.exe",
        "explorer": system / "explorer.exe",
    }
    exe = programs[kind]
    if kind == "explorer":
        documents.mkdir(parents=True, exist_ok=True)
        command = [str(exe), str(documents)]
    else:
        command = [str(exe)]
    process = subprocess.Popen(command, shell=False)
    return {"pid": int(process.pid), "exe": exe.name}


def focus_dashboard() -> None:
    """Open the local dashboard. The address is fixed."""

    if sys.platform != "win32":
        raise CompanionRefused(_NOT_WINDOWS)
    import os

    os.startfile("http://127.0.0.1:8787")  # noqa: S606 - fixed local URL, Windows only


def type_into_notepad(text: str, pid: int) -> None:
    """Type only after the window pid and title match the Notepad we opened."""

    if sys.platform != "win32":
        raise CompanionRefused(_NOT_WINDOWS)
    found = _notepad_window(pid)
    title = str(found.get("title") or "")
    hwnd = found.get("hwnd")
    if hwnd is None or not title_is_our_notepad(title, pid, pid):
        raise CompanionRefused(
            "Machaa refused to type because the front window is not the Notepad it opened."
        )
    try:
        _type_with_sendinput(int(hwnd), text)
    except CompanionRefused:
        raise
    except Exception:
        _type_with_pyautogui(int(hwnd), text)


def _notepad_window(pid: int) -> dict:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: dict = {}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _each(hwnd, _lparam):
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if int(process_id.value) != pid or not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        found["hwnd"] = hwnd
        found["title"] = buffer.value
        return True

    user32.EnumWindows(_each, 0)
    return found


def _type_with_sendinput(hwnd: int, text: str) -> None:
    """Windows UI input, used only on the verified Notepad window."""

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.SetForegroundWindow(hwnd)

    ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("ki", KEYBDINPUT)]

    inputs = []
    for char in text:
        inputs.append(INPUT(1, KEYBDINPUT(0, ord(char), 0x0004, 0, 0)))
        inputs.append(INPUT(1, KEYBDINPUT(0, ord(char), 0x0004 | 0x0002, 0, 0)))
    if not inputs:
        raise CompanionRefused("Machaa blocked this typing because the text is invalid.")
    array = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise OSError("SendInput did not accept the text")


def _type_with_pyautogui(hwnd: int, text: str) -> None:
    """Last resort, still only after the Notepad window was verified."""

    try:
        import pyautogui
    except ImportError as exc:
        raise CompanionRefused(
            "Machaa could not type into Notepad. Nothing was typed."
        ) from exc
    import ctypes

    ctypes.windll.user32.SetForegroundWindow(hwnd)
    pyautogui.FAILSAFE = True
    pyautogui.write(text, interval=0.01)
