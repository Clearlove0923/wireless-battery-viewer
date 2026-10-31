# -*- coding: utf-8 -*-
"""tray_app.py —— 托盘电量监视器（纯 ctypes，无第三方依赖）

界面约定
--------
* 通知区域一个闪电图标：任意已知设备电量低于 20% 时红色明暗闪烁。
* 右键图标 → 菜单：退出、插件、主界面。
* 左键双击 → 打开主界面。
* 悬停显示 tooltip：设备名 + 电量 + 更新时间。

其它
----
* 开机自启用「启动」文件夹里的快捷方式（`电量托盘.lnk`，任务管理器可见）+ pythonw.exe。
* 低 CPU：SetTimer 驱动，空闲不轮询；读取在后台线程；默认 60 秒一轮。
* **不写日志文件**：只有 `--debug` 时才往控制台打印。
* 全 ctypes 调 shell32/user32，不依赖 pystray / Pillow。

启动：
    pythonw tray_app.py        # 静默驻留（开机自启用的就是这个）
    python  tray_app.py --debug   # 前台运行并打印过程信息（排查问题用）
    python  tray_app.py --status
    python  tray_app.py --quit
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import threading
import time
import traceback
from ctypes import wintypes
from typing import Optional

import hid_win as hw
import battery as bt
import darkrim_proto as drp
import device_plugins as plugins
import win_icon
import tray_common as tc

BASE_DIR = tc.BASE_DIR
APP_NAME = tc.APP_NAME
MUTEX_NAME = tc.MUTEX_NAME
WND_CLASS = tc.WND_CLASS

USER32 = tc.USER32
KERNEL32 = tc.KERNEL32
SHELL32 = ctypes.WinDLL("shell32", use_last_error=True)

WM_DESTROY = 0x0002
WM_TIMER = 0x0113
WM_NULL = 0x0000
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_APP = 0x8000
MSG_TRAY_CALLBACK = WM_APP + 1
MSG_REFRESH_DONE = WM_APP + 2

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x01, 0x02, 0x04

SW_RESTORE = 9
MENU_EXIT, MENU_PLUGINS, MENU_PANEL, MENU_IGNORE_BLINK = 101, 102, 103, 104

USER32.CreatePopupMenu.restype = ctypes.c_void_p
USER32.CreatePopupMenu.argtypes = []
USER32.AppendMenuW.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
USER32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
USER32.TrackPopupMenu.restype = wintypes.UINT
USER32.TrackPopupMenu.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
USER32.DestroyMenu.argtypes = [ctypes.c_void_p]

# --------------------------------------------------------------------------
# Win32 结构体与原型
# --------------------------------------------------------------------------
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint,
                             ctypes.c_size_t, ctypes.c_ssize_t)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.c_void_p),
        ("hIcon", ctypes.c_void_p),
        ("hCursor", ctypes.c_void_p),
        ("hbrBackground", ctypes.c_void_p),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", ctypes.c_void_p),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", ctypes.c_void_p),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", ctypes.c_void_p),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", ctypes.c_wchar * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", hw.GUID),
        ("hBalloonIcon", ctypes.c_void_p),
    ]


class MSG(ctypes.Structure):
    _fields_ = [("hWnd", ctypes.c_void_p), ("message", wintypes.UINT),
                ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                ("time", wintypes.DWORD), ("pt_x", wintypes.LONG),
                ("pt_y", wintypes.LONG)]


USER32.RegisterClassExW.restype = wintypes.WORD
USER32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
USER32.CreateWindowExW.restype = ctypes.c_void_p
USER32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
USER32.DefWindowProcW.restype = ctypes.c_ssize_t
USER32.DefWindowProcW.argtypes = [ctypes.c_void_p, wintypes.UINT,
                                  ctypes.c_size_t, ctypes.c_ssize_t]
USER32.DestroyWindow.restype = wintypes.BOOL
USER32.DestroyWindow.argtypes = [ctypes.c_void_p]
USER32.SetTimer.restype = ctypes.c_size_t
USER32.SetTimer.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wintypes.UINT,
                            ctypes.c_void_p]
USER32.KillTimer.restype = wintypes.BOOL
USER32.KillTimer.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
USER32.GetMessageW.restype = ctypes.c_int
USER32.GetMessageW.argtypes = [ctypes.POINTER(MSG), ctypes.c_void_p,
                               wintypes.UINT, wintypes.UINT]
USER32.PostQuitMessage.restype = None
USER32.PostQuitMessage.argtypes = [ctypes.c_int]
USER32.TranslateMessage.restype = wintypes.BOOL
USER32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
USER32.DispatchMessageW.restype = ctypes.c_ssize_t
USER32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]

SHELL32.Shell_NotifyIconW.restype = wintypes.BOOL
SHELL32.Shell_NotifyIconW.argtypes = [wintypes.DWORD,
                                      ctypes.POINTER(NOTIFYICONDATAW)]

KERNEL32.GetModuleHandleW.restype = ctypes.c_void_p
KERNEL32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
KERNEL32.CreateMutexW.restype = ctypes.c_void_p
KERNEL32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                  wintypes.LPCWSTR]

DEVICES = [(p.key, p.title) for p in plugins.PLUGINS]
REFRESH_TIMER = 1
BLINK_TIMER = 2
DEMO_TIMER = 3
BLINK_INTERVAL_MS = 600
DEMO_DURATION_MS = 60000


def needs_low_battery_alert(levels) -> bool:
    return any(level is not None and 0 <= level < 20 for level, _ in levels.values())



# --------------------------------------------------------------------------
# 设备读取（轻量版）
# --------------------------------------------------------------------------
def _find_iface(vid: int, usage_page: int, output_len: int = 0):
    for d in hw.enumerate_hid():
        if d.vid == vid and d.usage_page == usage_page:
            if not output_len or d.output_len == output_len:
                return d
    return None


def read_mouse() -> tuple[Optional[int], str]:
    iface = _find_iface(0x373B, 0xFF05, 64) or _find_iface(0x373B, 0xFF02)
    if iface is None:
        return None, "没找到接收器"
    try:
        res = bt.strategy_vendor_protocol(iface)
    except Exception as e:
        return None, f"读取失败：{e}"
    if res is None:
        return None, "没有可用的读取方式"
    if res.ok:
        return res.level, ""
    return None, res.detail or "无回复（动一下鼠标）"


def read_headset() -> tuple[Optional[int], str]:
    return drp.read_battery_only(timeout=0.4)


# --------------------------------------------------------------------------
# 托盘程序
# --------------------------------------------------------------------------
class TrayApp:
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.cfg = tc.load_config()
        self.hwnd: Optional[int] = None
        self.wndproc_ref = None
        self.busy = False
        self.levels = {k: (None, "正在读取…") for k, _ in DEVICES}
        self.icons_added = False
        self.blink_active = False
        self.blink_bright = True
        self.blink_ignored = False
        self.updated_at = ""
        self.pending_levels = None
        self.refresh_pending = False
        self.demo_key = None
        self.demo_level = None
        self.taskbar_created_msg = USER32.RegisterWindowMessageW("TaskbarCreated")
        self.msg_quit = USER32.RegisterWindowMessageW(tc.MSG_QUIT)
        self.msg_reload = USER32.RegisterWindowMessageW(tc.MSG_RELOAD)
        self.msg_demo_low = USER32.RegisterWindowMessageW(tc.MSG_DEMO_LOW)
        self.msg_ignore_blink = USER32.RegisterWindowMessageW(tc.MSG_IGNORE_BLINK)
        self.log("启动，配置 = " + json.dumps(self.cfg, ensure_ascii=False))

    # ---- 输出（默认不落盘）---------------------------------------------
    def log(self, msg: str) -> None:
        """只在 --debug 时输出到控制台。

        默认**不写任何日志文件**（不占磁盘也不留痕）；需要排查问题时用
        `python tray_app.py --debug` 前台跑一次就能看到全部输出。
        """
        if self.debug:
            print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)

    # ---- 图标 ----------------------------------------------------------
    @staticmethod
    def _color(level: Optional[int]) -> tuple[int, int, int]:
        if level is None:
            return (150, 155, 160)
        if level >= 60:
            return (93, 220, 138)
        if level >= 30:
            return (245, 196, 81)
        return (255, 107, 107)

    def _nid(self, uID: int):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = uID
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = MSG_TRAY_CALLBACK
        return nid

    def _apply_icon(self, action: int) -> bool:
        nid = self._nid(1)
        if self.blink_active:
            icon_name = "lightning" if self.blink_bright else "blank"
            color = (255, 70, 50)
        else:
            icon_name = "lightning"
            color = (255, 205, 65)
        nid.hIcon = win_icon.make_hicon(icon_name, color)
        lines = []
        config = tc.load_config()
        low_battery = any(plugins.enabled(k, config) and v[0] is not None and v[0] < 20
                          for k, v in self.levels.items())
        for key, title in DEVICES:
            if not plugins.enabled(key, config):
                continue
            level, error = self.levels[key]
            lines.append(f"{title}：{level}%" if level is not None else f"{title}：{error or '未知'}")
        if not lines:
            lines.append("暂无开启的设备插件")
        if self.blink_active and low_battery:
            lines.append("低电量提醒：低于 20%")
        elif self.blink_ignored and low_battery:
            lines.append("低电量闪烁：本次运行已忽略")
        if self.updated_at:
            lines.append(f"更新于 {self.updated_at}")
        nid.szTip = "\n".join(lines)[:127]
        return bool(SHELL32.Shell_NotifyIconW(action, ctypes.byref(nid)))

    def add_icons(self) -> None:
        self.icons_added = self._apply_icon(NIM_ADD)

    def update_icons(self) -> None:
        if not self.icons_added:
            self.add_icons()
        elif not self._apply_icon(NIM_MODIFY):
            self.add_icons()

    def remove_icons(self) -> None:
        nid = self._nid(1)
        nid.uFlags = 0
        SHELL32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        self.icons_added = False

    def sync_blink(self) -> None:
        alert = needs_low_battery_alert(self.levels) and not self.blink_ignored
        if alert == self.blink_active:
            return
        self.blink_active = alert
        self.blink_bright = True
        if alert:
            USER32.SetTimer(self.hwnd, BLINK_TIMER, BLINK_INTERVAL_MS, None)
        else:
            USER32.KillTimer(self.hwnd, BLINK_TIMER)

    def ignore_blink_for_session(self) -> None:
        self.blink_ignored = True
        self.sync_blink()
        self.blink_bright = True
        self.update_icons()
        self.log("本次运行已忽略低电量闪烁")

    def apply_demo_level(self) -> None:
        if self.demo_key is not None and self.demo_level is not None:
            self.levels[self.demo_key] = (self.demo_level, "调试模拟值")

    def set_demo_level(self, level: int) -> bool:
        if os.environ.get("BATTERY_VIEWER_DEBUG") != "1":
            return False
        config = tc.load_config()
        self.demo_key = next((key for key, _ in DEVICES if plugins.enabled(key, config)), None)
        if self.demo_key is None:
            return False
        self.demo_level = max(0, min(100, int(level)))
        self.apply_demo_level()
        self.updated_at = time.strftime("%H:%M:%S") + "（模拟）"
        USER32.KillTimer(self.hwnd, DEMO_TIMER)
        USER32.SetTimer(self.hwnd, DEMO_TIMER, DEMO_DURATION_MS, None)
        self.sync_blink()
        self.update_icons()
        self.log(f"低电量演示：{self.demo_key}={self.demo_level}%")
        return True

    def clear_demo_level(self) -> None:
        self.demo_key = None
        self.demo_level = None
        USER32.KillTimer(self.hwnd, DEMO_TIMER)
        self.refresh_now()

    # ---- 定时器 / 刷新 --------------------------------------------------
    def apply_timer(self) -> None:
        if not self.hwnd:
            return
        USER32.KillTimer(self.hwnd, 1)
        USER32.SetTimer(self.hwnd, 1, int(self.cfg["interval"]) * 1000, None)

    def apply_config(self) -> None:
        """同步界面里改过的设置。

        注意：开机自启这里**只读不改**——托盘绝不替用户动系统设置。
        （早先的版本会自动"纠正"，结果一次读到不一致就把用户的启动项删了。）
        """
        new = tc.load_config()
        changed = new["interval"] != self.cfg["interval"]
        plugins_changed = new["devices"] != self.cfg["devices"]
        self.cfg = new
        if plugins_changed:
            for key, _ in DEVICES:
                if not plugins.enabled(key, new):
                    self.levels[key] = (None, "插件已关闭")
            self.sync_blink()
            self.update_icons()
            if self.busy:
                self.refresh_pending = True
            else:
                self.refresh_now()
        if changed:
            self.log(f"刷新间隔 -> {new['interval']} 秒")
            self.apply_timer()

        actual = tc.is_autostart_enabled()
        if bool(self.cfg.get("autostart")) != actual:
            # 只把真实状态写回配置，让界面上的勾选和任务管理器保持一致
            self.cfg["autostart"] = actual
            tc.save_config(self.cfg)
            self.log(f"开机自启实际为 {actual}，已同步到配置（未改动系统设置）")

    def refresh_now(self) -> None:
        if self.busy or not self.hwnd:
            return
        self.busy = True
        threading.Thread(target=self._worker, args=(self.hwnd,), daemon=True).start()

    def _worker(self, hwnd: int) -> None:
        try:
            self.pending_levels = plugins.read_plugins()
        except Exception:
            self.log("读取异常:\n" + traceback.format_exc())
        USER32.PostMessageW(hwnd, MSG_REFRESH_DONE, 0, 0)

    def on_refresh_done(self) -> None:
        self.busy = False
        if self.pending_levels is not None:
            self.levels = {key: (r.level, r.error) for key, r in
                           plugins.mask_disabled(self.pending_levels).items()}
            self.pending_levels = None
            self.updated_at = time.strftime("%H:%M:%S")
        self.apply_demo_level()
        self.sync_blink()
        self.log(f"刷新完成：{self.levels}")
        self.update_icons()
        if self.refresh_pending:
            self.refresh_pending = False
            self.refresh_now()

    # ---- 打开简洁界面 ---------------------------------------------------
    def open_ui(self, show_plugins=False) -> None:
        hwnd = tc.ui_hwnd()
        if hwnd:
            if show_plugins:
                tc.request_plugin_panel()
            USER32.ShowWindow(hwnd, SW_RESTORE)
            USER32.SetForegroundWindow(hwnd)
            self.log("简洁界面已在前台")
            return
        import subprocess
        try:
            command = tc.launch_command("my_devices.py")
            if show_plugins:
                command.append("--plugins")
            subprocess.Popen(command,
                             cwd=BASE_DIR, creationflags=0x00000008)
            self.log("已打开简洁界面")
        except Exception as e:
            self.log(f"打开界面失败：{e}")

    def show_menu(self) -> None:
        menu = USER32.CreatePopupMenu()
        if not menu:
            return
        selected = 0
        try:
            items = [(MENU_PANEL, "主界面"), (MENU_PLUGINS, "插件")]
            if self.blink_active:
                items.append((MENU_IGNORE_BLINK, "忽略低电量闪烁"))
            items.append((MENU_EXIT, "退出"))
            for item, title in items:
                USER32.AppendMenuW(menu, 0, item, title)
            point = wintypes.POINT()
            if not USER32.GetCursorPos(ctypes.byref(point)):
                return
            USER32.SetForegroundWindow(self.hwnd)
            selected = USER32.TrackPopupMenu(menu, 0x0100 | 0x0002, point.x, point.y,
                                            0, self.hwnd, None)
            USER32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        finally:
            USER32.DestroyMenu(menu)
        if selected == MENU_EXIT:
            self.quit()
        elif selected == MENU_PLUGINS:
            self.open_ui(show_plugins=True)
        elif selected == MENU_PANEL:
            self.open_ui()
        elif selected == MENU_IGNORE_BLINK:
            self.ignore_blink_for_session()

    def quit(self) -> None:
        self.log("退出")
        USER32.KillTimer(self.hwnd, REFRESH_TIMER)
        USER32.KillTimer(self.hwnd, BLINK_TIMER)
        USER32.KillTimer(self.hwnd, DEMO_TIMER)
        self.remove_icons()
        try:
            win_icon.destroy_all()
            win_icon.cleanup_files()
        except Exception:
            self.log("清理图标时出错（忽略）：\n" + traceback.format_exc())
        if self.hwnd:
            # DestroyWindow 会触发 WM_DESTROY -> PostQuitMessage，消息循环随之结束
            USER32.DestroyWindow(self.hwnd)

    # ---- 窗口过程 -------------------------------------------------------
    def wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == MSG_TRAY_CALLBACK:
            event = int(lparam) & 0xFFFF
            if event == WM_RBUTTONUP:
                self.show_menu()
            elif event == WM_LBUTTONDBLCLK:
                self.open_ui()
            return 0
        if msg == MSG_REFRESH_DONE:
            self.on_refresh_done()
            return 0
        if msg == WM_TIMER:
            if wparam == BLINK_TIMER:
                if self.blink_active:
                    self.blink_bright = not self.blink_bright
                    self.update_icons()
                return 0
            if wparam == DEMO_TIMER:
                self.clear_demo_level()
                return 0
            if wparam != REFRESH_TIMER:
                return 0
            self.apply_config()                    # 顺手同步一下界面里改的设置
            self.refresh_now()
            return 0
        if msg == self.msg_quit:
            self.quit()
            return 0
        if msg == self.msg_reload:
            self.apply_config()
            return 0
        if msg == self.msg_demo_low:
            self.set_demo_level(int(wparam))
            return 0
        if msg == self.msg_ignore_blink:
            self.ignore_blink_for_session()
            return 0
        if msg == self.taskbar_created_msg:
            self.log("任务栏重建，重新添加图标")
            self.add_icons()
            return 0
        if msg == WM_DESTROY:
            # 重要：销毁窗口后必须让消息循环退出，否则进程会残留成"僵尸"
            # ——它已经没有窗口/图标了，却还占着单实例锁，导致托盘再也起不来。
            USER32.PostQuitMessage(0)
            return 0
        return USER32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # ---- 启动 ----------------------------------------------------------
    def run(self) -> int:
        hinst = KERNEL32.GetModuleHandleW(None)
        self.wndproc_ref = WNDPROC(self.wnd_proc)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self.wndproc_ref
        wc.hInstance = hinst
        wc.lpszClassName = WND_CLASS
        if not USER32.RegisterClassExW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err not in (0, 1410):
                self.log(f"RegisterClassExW 失败 err={err}")
                return 1

        hwnd = USER32.CreateWindowExW(0, WND_CLASS, APP_NAME, 0, 0, 0, 0, 0,
                                      None, None, hinst, None)
        if not hwnd:
            self.log(f"CreateWindowExW 失败 err={ctypes.get_last_error()}")
            return 1
        self.hwnd = hwnd

        self.add_icons()
        self.apply_config()
        self.apply_timer()
        self.refresh_now()

        msg = MSG()
        while USER32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            USER32.TranslateMessage(ctypes.byref(msg))
            USER32.DispatchMessageW(ctypes.byref(msg))
        self.log("消息循环结束")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="托盘电量监视器")
    parser.add_argument("--debug", action="store_true", help="前台运行并输出日志")
    parser.add_argument("--status", action="store_true", help="打印当前状态")
    parser.add_argument("--quit", action="store_true", help="让正在运行的实例退出")
    parser.add_argument("--demo-low-battery", type=int, metavar="PERCENT",
                        help="调试版：向当前托盘注入模拟低电量，保持 60 秒")
    args = parser.parse_args()

    if args.status:
        print("配置：", json.dumps(tc.load_config(), ensure_ascii=False))
        print("开机自启：", tc.is_autostart_enabled())
        print("启动命令：", tc.autostart_command())
        print("托盘是否在运行：", tc.is_tray_running())
        return 0
    if args.quit:
        ok = tc.post_to_tray(tc.MSG_QUIT)
        print("已通知托盘退出" if ok else "托盘没在运行")
        return 0
    if args.demo_low_battery is not None:
        if os.environ.get("BATTERY_VIEWER_DEBUG") != "1":
            print("低电量注入仅供调试版使用")
            return 2
        level = max(0, min(100, args.demo_low_battery))
        ok = tc.post_to_tray(tc.MSG_DEMO_LOW, level)
        print(f"已注入模拟电量 {level}%" if ok else "调试托盘未运行")
        return 0 if ok else 1

    # 单实例
    KERNEL32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == 183:
        if tc.is_tray_running():
            # 真有一个正常实例在跑：让它重读配置
            tc.post_to_tray(tc.MSG_RELOAD)
            print("已经在运行了（托盘里的闪电图标就是它；双击图标打开界面）")
            return 0
        # 有人占着锁但已经没有窗口 —— 上一版留下的僵尸进程，清掉后继续启动
        tc.cleanup_zombie()

    tc.write_pid()

    try:
        USER32.SetProcessDPIAware()            # 图标不糊
    except Exception:
        pass

    app = TrayApp(debug=args.debug or os.environ.get("BATTERY_VIEWER_DEBUG") == "1")
    try:
        return app.run()
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        tc.remove_pid()


if __name__ == "__main__":
    sys.exit(main())
