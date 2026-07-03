import ctypes
import ctypes.wintypes
import json
import os
import re
import sqlite3
import sys
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk


APP_DIR = Path(__file__).resolve().parent
USAGE_JSON = APP_DIR / "usage.json"
TRAY_ICON_PATH = APP_DIR / "assets" / "codex_usage_overlay_icon.ico"
TRAY_ICON_PATHS = {
    "all": TRAY_ICON_PATH,
    "red": APP_DIR / "assets" / "codex_usage_overlay_icon_red.ico",
    "yellow": APP_DIR / "assets" / "codex_usage_overlay_icon_yellow.ico",
    "green": APP_DIR / "assets" / "codex_usage_overlay_icon_green.ico",
}
CODEX_DIR = Path.home() / ".codex"
STATE_DB = CODEX_DIR / "state_5.sqlite"
LOGS_DB = CODEX_DIR / "logs_2.sqlite"
SESSIONS_DIR = CODEX_DIR / "sessions"

BAR_HEIGHT = 34
BAR_MAX_WIDTH = 600
BAR_SIDE_MARGIN = 12
BAR_TOP_OFFSET = 2
WINDOW_CONTROL_SAFE_WIDTH = 170
POLL_MS = 2500
POSITION_MS = 400


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SW_SHOWMINNOACTIVE = 7

WM_DESTROY = 0x0002
WM_NULL = 0x0000
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 20
PM_REMOVE = 0x0001

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040
MF_STRING = 0x0000
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
TRAY_EXIT_COMMAND = 1001


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    ctypes.wintypes.HWND,
    ctypes.wintypes.UINT,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.wintypes.HINSTANCE),
        ("hIcon", ctypes.wintypes.HICON),
        ("hCursor", ctypes.wintypes.HANDLE),
        ("hbrBackground", ctypes.wintypes.HBRUSH),
        ("lpszMenuName", ctypes.wintypes.LPCWSTR),
        ("lpszClassName", ctypes.wintypes.LPCWSTR),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("hWnd", ctypes.wintypes.HWND),
        ("uID", ctypes.wintypes.UINT),
        ("uFlags", ctypes.wintypes.UINT),
        ("uCallbackMessage", ctypes.wintypes.UINT),
        ("hIcon", ctypes.wintypes.HICON),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", ctypes.wintypes.DWORD),
        ("dwStateMask", ctypes.wintypes.DWORD),
        ("szInfo", ctypes.c_wchar * 256),
        ("uTimeoutOrVersion", ctypes.wintypes.UINT),
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", ctypes.wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", ctypes.wintypes.HICON),
    ]


@dataclass
class CodexWindow:
    hwnd: int
    pid: int
    left: int
    top: int
    right: int
    bottom: int
    minimized: bool

    @property
    def width(self) -> int:
        return max(240, self.right - self.left)


@dataclass
class UsageSnapshot:
    remaining_text: str
    remaining_percent: float | None
    detail: str
    updated_text: str
    source: str


def _query_process_path(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = ctypes.wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        ok = kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        return buf.value if ok else ""
    finally:
        kernel32.CloseHandle(handle)


def _window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _window_pid(hwnd: int) -> int:
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _process_exe(pid: int) -> str:
    path = _query_process_path(pid)
    return Path(path).name.lower() if path else ""


def is_codex_foreground() -> bool:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    return _process_exe(_window_pid(hwnd)) in {"codex.exe"}


def find_codex_window() -> CodexWindow | None:
    matches: list[CodexWindow] = []

    def enum_proc(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True

        pid = _window_pid(hwnd)
        title = _window_text(hwnd)
        exe = _process_exe(pid)
        minimized = bool(user32.IsIconic(hwnd))

        if title.lower() == "codex" or exe == "codex.exe":
            rect = RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                width = rect.right - rect.left
                height = rect.bottom - rect.top
                if minimized or (width >= 500 and height >= 300):
                    matches.append(
                        CodexWindow(
                            hwnd,
                            pid,
                            rect.left,
                            rect.top,
                            rect.right,
                            rect.bottom,
                            minimized,
                        )
                    )
        return True

    enum_windows_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(enum_windows_proc(enum_proc), 0)

    if not matches:
        return None
    return max(matches, key=lambda item: item.width)


def open_readonly_sqlite(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)
    con.execute("pragma query_only = on")
    return con


def fmt_ts(value: int | float | None) -> str:
    if not value:
        return "未知"
    value = float(value)
    if value > 10_000_000_000:
        value = value / 1000
    return time.strftime("%H:%M:%S", time.localtime(value))


def fmt_reset(value: int | float | None) -> str:
    if not value:
        return "未知"
    value = float(value)
    if value > 10_000_000_000:
        value = value / 1000
    return time.strftime("%m-%d %H:%M", time.localtime(value))


def window_name(minutes: int | None) -> str:
    if not minutes:
        return "窗口"
    if minutes < 60:
        return f"{minutes}分钟"
    if minutes < 24 * 60:
        hours = minutes // 60
        return f"{hours}小时"
    days = minutes // (24 * 60)
    return f"{days}天"


def parse_iso_to_local_time(value: str | None) -> str:
    if not value:
        return "未知"
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%H:%M:%S")
    except Exception:
        return value


def parse_iso_timestamp(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        from datetime import datetime

        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def compact_tokens(value: int | None) -> str:
    if value is None:
        return "未知"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def iter_recent_session_files(limit: int = 12) -> list[Path]:
    if not SESSIONS_DIR.exists():
        return []
    try:
        files = list(SESSIONS_DIR.rglob("*.jsonl"))
    except Exception:
        return []
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)[:limit]


def read_latest_session_rate_limits() -> dict | None:
    latest: dict | None = None
    latest_ts = 0.0

    for path in iter_recent_session_files():
        try:
            file_mtime = path.stat().st_mtime
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    payload = event.get("payload") or {}
                    if payload.get("type") != "token_count":
                        continue
                    rate_limits = payload.get("rate_limits")
                    if not isinstance(rate_limits, dict):
                        continue
                    event_ts = parse_iso_timestamp(event.get("timestamp"))
                    if event_ts < latest_ts:
                        continue
                    latest_ts = event_ts
                    latest = {
                        "timestamp": event.get("timestamp"),
                        "rate_limits": rate_limits,
                        "file_mtime": file_mtime,
                    }
        except Exception:
            continue
    return latest


def session_rate_snapshot() -> UsageSnapshot | None:
    found = read_latest_session_rate_limits()
    if not found:
        return None

    rate_limits = found["rate_limits"]
    primary = rate_limits.get("primary") or {}
    secondary = rate_limits.get("secondary") or {}

    def remaining(part: dict) -> float | None:
        used = part.get("used_percent")
        if not isinstance(used, (int, float)):
            return None
        return max(0.0, min(100.0, 100.0 - float(used)))

    primary_remaining = remaining(primary)
    secondary_remaining = remaining(secondary)
    values = [item for item in [primary_remaining, secondary_remaining] if item is not None]
    if not values:
        return None

    limiting = min(values)
    short_text = f"{primary_remaining:.0f}%" if primary_remaining is not None else "--"
    week_text = f"{secondary_remaining:.0f}%" if secondary_remaining is not None else "--"
    remaining_text = f"短{short_text} 周{week_text}"

    primary_window = window_name(primary.get("window_minutes"))
    secondary_window = window_name(secondary.get("window_minutes"))
    primary_reset = fmt_reset(primary.get("resets_at"))
    secondary_reset = fmt_reset(secondary.get("resets_at"))
    plan = rate_limits.get("plan_type") or "未知套餐"
    detail = (
        f"{primary_window}剩余 {short_text} 重置 {primary_reset} | "
        f"{secondary_window}剩余 {week_text} 重置 {secondary_reset} | {plan}"
    )

    return UsageSnapshot(
        remaining_text=remaining_text,
        remaining_percent=limiting,
        detail=detail,
        updated_text=parse_iso_to_local_time(found.get("timestamp")),
        source="Codex 会话",
    )


def read_usage_json() -> dict:
    if not USAGE_JSON.exists():
        return {}
    try:
        data = json.loads(USAGE_JSON.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"error": "usage.json 解析失败"}


def read_latest_thread() -> tuple[str, int | None, int | None]:
    if not STATE_DB.exists():
        return "未找到 Codex 状态库", None, None
    try:
        with open_readonly_sqlite(STATE_DB) as con:
            row = con.execute(
                """
                select title, tokens_used, updated_at
                from threads
                order by coalesce(updated_at_ms, updated_at * 1000) desc
                limit 1
                """
            ).fetchone()
    except Exception as exc:
        return f"状态读取失败: {exc}", None, None

    if not row:
        return "暂无线程", None, None
    title = (row[0] or "未命名线程").strip()
    return title[:24], int(row[1] or 0), int(row[2] or 0)


def read_latest_rate_event() -> int | None:
    if not LOGS_DB.exists():
        return None
    try:
        with open_readonly_sqlite(LOGS_DB) as con:
            row = con.execute(
                """
                select ts
                from logs
                where target = 'codex_app_server::outgoing_message'
                  and feedback_log_body like '%account/rateLimits/updated%'
                order by id desc
                limit 1
                """
            ).fetchone()
    except Exception:
        return None
    return int(row[0]) if row else None


def read_log_remaining_percent() -> tuple[float | None, str | None]:
    if not LOGS_DB.exists():
        return None, None

    patterns = [
        re.compile(r"remaining[_ -]?percent[\"'=:\s]+([0-9]+(?:\.[0-9]+)?)", re.I),
        re.compile(r"rate[_ -]?limit.{0,120}?remaining.{0,40}?([0-9]+(?:\.[0-9]+)?)\s*%", re.I),
    ]

    try:
        with open_readonly_sqlite(LOGS_DB) as con:
            rows = con.execute(
                """
                select ts, feedback_log_body
                from logs
                where feedback_log_body like '%remaining%'
                   or feedback_log_body like '%rateLimit%'
                   or feedback_log_body like '%rate limit%'
                order by id desc
                limit 200
                """
            ).fetchall()
    except Exception:
        return None, None

    for ts, body in rows:
        body = body or ""
        if "codex_usage_overlay.py" in body or "read_log_remaining_percent" in body:
            continue
        for pattern in patterns:
            match = pattern.search(body)
            if match:
                value = float(match.group(1))
                if 0 <= value <= 100:
                    return value, fmt_ts(ts)
    return None, None


def build_snapshot() -> UsageSnapshot:
    data = read_usage_json()
    _, _, thread_updated = read_latest_thread()


    percent = data.get("remaining_percent")
    source = "本地状态"
    updated = fmt_ts(thread_updated)

    if isinstance(percent, (int, float)):
        percent = max(0.0, min(100.0, float(percent)))
        remaining_text = f"{percent:.0f}%"
        source = "usage.json"
        updated = str(data.get("updated_at") or updated)
    else:
        session_snapshot = session_rate_snapshot()
        if session_snapshot is not None:
            percent = session_snapshot.remaining_percent
            remaining_text = session_snapshot.remaining_text
            source = session_snapshot.source
            updated = session_snapshot.updated_text
            detail = session_snapshot.detail
        else:
            log_percent, log_updated = read_log_remaining_percent()
            if log_percent is not None:
                percent = log_percent
                remaining_text = f"{percent:.0f}%"
                source = "Codex 日志"
                updated = log_updated or updated
            else:
                percent = None
                remaining_text = str(data.get("remaining_text") or "未获取")

    reset_at = data.get("reset_at")
    if "detail" not in locals():
        detail = f"剩余 {remaining_text}"
    if reset_at:
        detail = f"{detail} | 重置: {reset_at}"
    if data.get("error"):
        detail = f"{detail} | {data["error"]}"


    return UsageSnapshot(remaining_text, percent, detail, updated, source)


class SystemTrayIcon:
    def __init__(self, root: tk.Tk, on_exit) -> None:
        self.root = root
        self.on_exit = on_exit
        self.active = False
        self.icon_added = False
        self.hwnd = None
        self.hicon = None
        self.current_status = "all"
        self.nid = None
        self.class_name = f"CodexUsageOverlayTray_{os.getpid()}"
        self._wnd_proc = WNDPROC(self._handle_message)

        kernel32.GetModuleHandleW.restype = ctypes.wintypes.HMODULE
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        user32.CreateWindowExW.argtypes = [
            ctypes.wintypes.DWORD,
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.wintypes.HWND,
            ctypes.wintypes.HMENU,
            ctypes.wintypes.HINSTANCE,
            ctypes.wintypes.LPVOID,
        ]
        user32.CreateWindowExW.restype = ctypes.wintypes.HWND
        user32.DefWindowProcW.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.wintypes.UINT,
            ctypes.wintypes.WPARAM,
            ctypes.wintypes.LPARAM,
        ]
        user32.DefWindowProcW.restype = LRESULT
        user32.LoadImageW.argtypes = [
            ctypes.wintypes.HINSTANCE,
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.wintypes.UINT,
        ]
        user32.LoadImageW.restype = ctypes.wintypes.HANDLE
        user32.CreatePopupMenu.restype = ctypes.wintypes.HMENU
        user32.TrackPopupMenu.restype = ctypes.wintypes.UINT

        self.hinstance = kernel32.GetModuleHandleW(None)
        window_class = WNDCLASSW()
        window_class.lpfnWndProc = self._wnd_proc
        window_class.hInstance = self.hinstance
        window_class.lpszClassName = self.class_name

        if not user32.RegisterClassW(ctypes.byref(window_class)):
            raise ctypes.WinError()

        self.hwnd = user32.CreateWindowExW(
            0,
            self.class_name,
            "Codex Usage Overlay Tray",
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            self.hinstance,
            None,
        )
        if not self.hwnd:
            user32.UnregisterClassW(self.class_name, self.hinstance)
            raise ctypes.WinError()

        self.hicon = user32.LoadImageW(
            None,
            str(TRAY_ICON_PATH),
            IMAGE_ICON,
            32,
            32,
            LR_LOADFROMFILE | LR_DEFAULTSIZE,
        )
        if not self.hicon:
            self.close()
            raise ctypes.WinError()

        self.nid = NOTIFYICONDATAW()
        self.nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        self.nid.hWnd = self.hwnd
        self.nid.uID = 1
        self.nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        self.nid.uCallbackMessage = WM_TRAYICON
        self.nid.hIcon = self.hicon
        self.nid.szTip = "Codex 用量指示条"

        if not ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self.nid)):
            self.close()
            raise ctypes.WinError()

        self.icon_added = True
        self.active = True
        self.pump_messages()

    def _handle_message(self, hwnd, message, wparam, lparam):
        if message == WM_TRAYICON:
            event = int(lparam) & 0xFFFF
            if event in {WM_RBUTTONUP, WM_CONTEXTMENU}:
                self.show_menu()
            return 0
        if message == WM_DESTROY:
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def show_menu(self) -> None:
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        try:
            user32.AppendMenuW(menu, MF_STRING, TRAY_EXIT_COMMAND, "退出程序")
            cursor = POINT()
            user32.GetCursorPos(ctypes.byref(cursor))
            user32.SetForegroundWindow(self.hwnd)
            command = user32.TrackPopupMenu(
                menu,
                TPM_RIGHTBUTTON | TPM_RETURNCMD,
                cursor.x,
                cursor.y,
                0,
                self.hwnd,
                None,
            )
            user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
            if command == TRAY_EXIT_COMMAND:
                self.root.after(0, self.on_exit)
        finally:
            user32.DestroyMenu(menu)

    def update_remaining(self, remaining_percent: float | None) -> None:
        if remaining_percent is None:
            status = "all"
            tooltip = "Codex 用量指示条"
        elif remaining_percent < 30:
            status = "red"
            tooltip = f"Codex 用量指示条 - 剩余 {remaining_percent:.0f}%"
        elif remaining_percent < 60:
            status = "yellow"
            tooltip = f"Codex 用量指示条 - 剩余 {remaining_percent:.0f}%"
        else:
            status = "green"
            tooltip = f"Codex 用量指示条 - 剩余 {remaining_percent:.0f}%"

        if self.nid is None:
            return
        if status == self.current_status:
            self.nid.szTip = tooltip
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self.nid))
            return

        new_icon = user32.LoadImageW(
            None,
            str(TRAY_ICON_PATHS[status]),
            IMAGE_ICON,
            32,
            32,
            LR_LOADFROMFILE | LR_DEFAULTSIZE,
        )
        if not new_icon:
            return

        old_icon = self.hicon
        self.nid.hIcon = new_icon
        self.nid.szTip = tooltip
        if ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self.nid)):
            self.hicon = new_icon
            self.current_status = status
            if old_icon:
                user32.DestroyIcon(old_icon)
        else:
            user32.DestroyIcon(new_icon)

    def pump_messages(self) -> None:
        if not self.active or not self.hwnd:
            return
        message = ctypes.wintypes.MSG()
        while user32.PeekMessageW(
            ctypes.byref(message), self.hwnd, 0, 0, PM_REMOVE
        ):
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        self.root.after(50, self.pump_messages)

    def close(self) -> None:
        self.active = False
        if self.icon_added and self.nid is not None:
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.nid))
            self.icon_added = False
        if self.hicon:
            user32.DestroyIcon(self.hicon)
            self.hicon = None
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None
        if getattr(self, "hinstance", None):
            user32.UnregisterClassW(self.class_name, self.hinstance)


class OverlayApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Codex 用量悬浮条")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
        self.root.configure(bg="#111827")

        self.window_found = False
        self.overlay_visible = True
        self.closing = False
        self.tray = None
        self._build_ui()
        self.tray = SystemTrayIcon(self.root, self.shutdown)
        self.refresh_usage()
        self.follow_codex()

    def _build_ui(self) -> None:
        self.frame = tk.Frame(self.root, bg="#111827", height=BAR_HEIGHT)
        self.frame.pack(fill="both", expand=True)

        self.detail_label = tk.Label(
            self.frame,
            text="等待 Codex 窗口",
            bg="#111827",
            fg="#CBD5E1",
            font=("Microsoft YaHei UI", 10),
            anchor="w",
        )
        self.detail_label.pack(side="left", fill="x", expand=True, padx=(14, 8))

        self.parts_frame = tk.Frame(self.frame, bg="#111827")
        self.parts_frame.pack_forget()
        self.part_labels: list[tk.Label] = []

        close_button = tk.Button(
            self.frame,
            text="×",
            command=self.shutdown,
            bg="#1F2937",
            fg="#F9FAFB",
            activebackground="#374151",
            activeforeground="#FFFFFF",
            bd=0,
            width=3,
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        close_button.pack(side="right", padx=(2, 8), pady=7)

    def refresh_usage(self) -> None:
        snapshot = build_snapshot()
        if self.tray is not None:
            self.tray.update_remaining(snapshot.remaining_percent)
        text = snapshot.detail if self.window_found else f"等待 Codex 打开 | {snapshot.detail}"
        self.render_detail(text)
        self.root.after(POLL_MS, self.refresh_usage)

    def render_detail(self, text: str) -> None:
        # Two-percentage format (session data)
        match = re.match(r"^(.*?剩余 )([0-9]+%)(.*?\|\s*)(.*?剩余 )([0-9]+%)(.*?\|\s*)(.*)$", text)
        if not match:
            # Single-percentage format (usage.json / logs)
            match = re.match(r"^(.*?剩余 )([0-9]+%)(\s*\|\s*)(.*)$", text)
        single = match and match.lastindex == 4
        if not match:
            self.parts_frame.pack_forget()
            self.detail_label.pack(side="left", fill="x", expand=True, padx=(14, 8))
            self.detail_label.configure(text=text)
            return

        self.detail_label.pack_forget()
        if not self.parts_frame.winfo_ismapped():
            self.parts_frame.pack(side="left", fill="x", expand=True, padx=(14, 8))

        if single:
            color = self.percent_color(match.group(2))
            parts = [
                (match.group(1), ("Microsoft YaHei UI", 10), "#CBD5E1", 0),
                (match.group(2), ("Consolas", 15, "bold"), color, 0),
                (match.group(3).replace("|", ""), ("Microsoft YaHei UI", 10), "#CBD5E1", 0),
                (match.group(4), ("Microsoft YaHei UI", 10), "#CBD5E1", 16),
            ]
        else:
            first_color = self.percent_color(match.group(2))
            second_color = self.percent_color(match.group(5))
            parts = [
                (match.group(1), ("Microsoft YaHei UI", 10), "#CBD5E1", 0),
                (match.group(2), ("Consolas", 15, "bold"), first_color, 0),
                (match.group(3).replace("|", ""), ("Microsoft YaHei UI", 10), "#CBD5E1", 0),
                (match.group(4), ("Microsoft YaHei UI", 10), "#CBD5E1", 20),
                (match.group(5), ("Consolas", 15, "bold"), second_color, 0),
                (match.group(6).replace("|", ""), ("Microsoft YaHei UI", 10), "#CBD5E1", 0),
                (match.group(7), ("Microsoft YaHei UI", 10), "#CBD5E1", 16),
            ]

        while len(self.part_labels) < len(parts):
            label = tk.Label(self.parts_frame, bg="#111827", anchor="w")
            label.pack(side="left")
            self.part_labels.append(label)

        for label, (part_text, font, color, padx_left) in zip(self.part_labels, parts):
            label.configure(text=part_text, font=font, fg=color)
            label.pack(side="left", padx=(padx_left, 0))

        for label in self.part_labels[len(parts) :]:
            label.pack_forget()
    def percent_color(self, value_text: str) -> str:
        try:
            value = float(value_text.rstrip("%"))
        except ValueError:
            return "#CBD5E1"
        if value < 30:
            return "#F87171"
        if value < 60:
            return "#FBBF24"
        return "#34D399"

    def follow_codex(self) -> None:
        target = find_codex_window()
        if target is None:
            self.window_found = False
            self.hide_overlay()
        elif target.minimized or not is_codex_foreground():
            self.window_found = False
            self.hide_overlay()
        else:
            self.window_found = True
            self.show_overlay()
            width = min(BAR_MAX_WIDTH, max(360, target.width - BAR_SIDE_MARGIN * 2))
            safe_right = target.right - WINDOW_CONTROL_SAFE_WIDTH
            centered_x = target.left + (target.width - width) // 2
            x = min(centered_x, safe_right - width)
            x = max(target.left + BAR_SIDE_MARGIN, x)
            y = target.top + BAR_TOP_OFFSET
            self.root.geometry(f"{width}x{BAR_HEIGHT}+{x}+{y}")
        if self.overlay_visible:
            self.root.lift()
        self.root.after(POSITION_MS, self.follow_codex)

    def show_overlay(self) -> None:
        if self.overlay_visible:
            return
        self.root.deiconify()
        self.overlay_visible = True

    def hide_overlay(self) -> None:
        if not self.overlay_visible:
            return
        self.root.withdraw()
        self.overlay_visible = False

    def shutdown(self) -> None:
        if self.closing:
            return
        self.closing = True
        if self.tray is not None:
            self.tray.close()
            self.tray = None
        self.root.destroy()

    def run(self) -> None:
        try:
            self.root.mainloop()
        finally:
            if self.tray is not None:
                self.tray.close()
                self.tray = None


def main() -> int:
    if os.name != "nt":
        print("这个悬浮条目前只支持 Windows。")
        return 1
    app = OverlayApp()
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
