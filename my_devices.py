# -*- coding: utf-8 -*-
"""我的设备电量 —— 显示已注册设备插件的简洁面板

用法：
    python my_devices.py            打开界面（默认自动刷新）
    python my_devices.py --once     命令行读一次就退出

界面按插件注册表显示设备电量，可自动刷新并单独启停插件。
"""

from __future__ import annotations

import argparse
import queue
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Optional

import hid_win as hw
import battery as bt
import darkrim_proto as drp
import tray_common as tc
import win_link
from hid_win import HidInterface


# ==========================================================================
# 读取层
# ==========================================================================
from device_plugins import Reading, read_atk, read_darkrim
import device_plugins as plugins


def read_all() -> list[Reading]:
    return list(plugins.read_plugins().values())


# ==========================================================================
# 命令行模式
# ==========================================================================
def cli_once() -> None:
    for r in read_all():
        if r.ok:
            print(f"{r.title}: {r.level}%   {r.detail}")
            if r.extra:
                print(f"    {r.extra}")
        else:
            print(f"{r.title}: 读取失败 —— {r.error}")


# ==========================================================================
# 界面
# ==========================================================================
BG = "#1b1c1f"
PANEL = "#232529"
PANEL2 = "#2b2e33"
FG = "#e8e8ea"
MUTED = "#9aa0a6"
FONT = ("Microsoft YaHei UI", 10)

LEVEL_STYLE = [
    (60, "#5ddc8a", "电量充足"),
    (30, "#f5c451", "电量中等"),
    (0,  "#ff6b6b", "电量偏低"),
]


def level_color(level: Optional[int]) -> str:
    if level is None:
        return MUTED
    for threshold, color, _ in LEVEL_STYLE:
        if level >= threshold:
            return color
    return LEVEL_STYLE[-1][1]


class DeviceCard:
    """一块设备卡片。"""

    def __init__(self, parent, title: str):
        import tkinter as tk
        from tkinter import ttk

        self.frame = ttk.Frame(parent, style="Card.TFrame", padding=16)
        self.lab_title = ttk.Label(self.frame, text=title, style="CardTitle.TLabel")
        self.lab_title.pack(anchor="w")
        self.lab_sub = ttk.Label(self.frame, text="正在读取…", style="CardSub.TLabel")
        self.lab_sub.pack(anchor="w", pady=(2, 0))

        self.lab_level = ttk.Label(self.frame, text="--", style="CardBig.TLabel")
        self.lab_level.pack(anchor="w", pady=(10, 0))
        self.lab_status = ttk.Label(self.frame, text="", style="CardSub.TLabel")
        self.lab_status.pack(anchor="w")

        self.bar = ttk.Progressbar(self.frame, mode="determinate", maximum=100,
                                   style="Card.Horizontal.TProgressbar")
        self.bar.pack(fill="x", pady=(10, 8))

        self.lab_detail = ttk.Label(self.frame, text="", style="CardSub.TLabel",
                                    wraplength=250, justify="left")
        self.lab_detail.pack(anchor="w")
        self.lab_extra = ttk.Label(self.frame, text="", style="CardSub.TLabel",
                                   wraplength=250, justify="left")
        self.lab_extra.pack(anchor="w", pady=(4, 0))

    def update(self, r: Reading) -> None:
        self.lab_sub.configure(text=r.subtitle)
        if r.ok:
            self.lab_level.configure(text=f"{r.level}%",
                                     foreground=level_color(r.level))
            st = r.status if r.status not in ("未知", "状态未知") else ""
            self.lab_status.configure(text=st)
            self.bar["value"] = r.level or 0
            self.lab_detail.configure(text=r.detail)
            self.lab_extra.configure(text=r.extra)
        else:
            self.lab_level.configure(text="--", foreground=MUTED)
            self.lab_status.configure(text="")
            self.bar["value"] = 0
            self.lab_detail.configure(text=r.error)
            self.lab_extra.configure(text="")


def build_ui(show_plugin_list=False):
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(tc.UI_TITLE)
    root.configure(bg=BG)
    root.geometry("1060x680")
    root.minsize(960, 620)

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=FG, font=FONT)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=PANEL)
    style.configure("Panel.TFrame", background=PANEL)
    style.configure("TLabel", background=BG, foreground=FG, font=FONT)
    style.configure("H1.TLabel", background=BG, foreground=FG,
                    font=("Microsoft YaHei UI", 15, "bold"))
    style.configure("Muted.TLabel", background=BG, foreground=MUTED,
                    font=("Microsoft YaHei UI", 9))
    style.configure("CardTitle.TLabel", background=PANEL, foreground=FG,
                    font=("Microsoft YaHei UI", 12, "bold"))
    style.configure("CardSub.TLabel", background=PANEL, foreground=MUTED,
                    font=("Microsoft YaHei UI", 9))
    style.configure("CardBig.TLabel", background=PANEL, foreground="#5ddc8a",
                    font=("Microsoft YaHei UI", 40, "bold"))
    style.configure("Card.Horizontal.TProgressbar", background="#4f8cff",
                    troughcolor=PANEL2, borderwidth=0, thickness=8)
    style.configure("TButton", background=PANEL2, foreground=FG, borderwidth=0,
                    focusthickness=0, padding=(14, 7), font=FONT)
    style.map("TButton", background=[("active", "#3a3f47"), ("disabled", "#2a2c30")],
              foreground=[("disabled", "#6b7076")])
    style.configure("Accent.TButton", background="#4f8cff", foreground="#ffffff")
    style.map("Accent.TButton", background=[("active", "#6ea1ff")])
    style.configure("TCheckbutton", background=BG, foreground=FG, font=FONT)
    style.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2,
                    foreground=FG)

    state = {"busy": False, "auto": True, "interval": 60, "after_id": None,
             "starting": False, "started_at": 0.0}
    last_success: dict[str, Reading] = {}
    # Tkinter 不是线程安全的：后台线程只往队列里放结果，主线程统一取出来处理
    results: "queue.Queue[tuple]" = queue.Queue()

    cfg = tc.load_config()
    state["interval"] = int(cfg["interval"])

    # Persistent sidebar; plugin controls never occupy the device workspace.
    shell = ttk.Frame(root)
    shell.pack(fill="both", expand=True)
    sidebar = ttk.Frame(shell, style="Panel.TFrame", padding=(18, 24), width=220)
    sidebar.pack(side="left", fill="y")
    sidebar.pack_propagate(False)
    ttk.Label(sidebar, text="⚡ 电量中心", style="CardTitle.TLabel").pack(anchor="w")
    ttk.Label(sidebar, text="设备与插件", style="CardSub.TLabel").pack(anchor="w", pady=(6, 28))
    plugin_button = ttk.Button(sidebar, text="插件管理  ▸", style="Accent.TButton")
    plugin_button.pack(fill="x")
    plugin_list = ttk.Frame(sidebar, style="Panel.TFrame")
    style.configure("Plugin.TCheckbutton", background=PANEL, foreground=FG, padding=(2, 8))
    style.map("Plugin.TCheckbutton", background=[("active", PANEL2)])
    plugin_count = ttk.Label(sidebar, text="", style="CardSub.TLabel")
    plugin_count.pack(side="bottom", anchor="w", pady=(12, 0))
    ttk.Label(sidebar, text="关闭插件后停止读取电量", style="CardSub.TLabel",
              wraplength=175).pack(side="bottom", anchor="w")
    main_area = ttk.Frame(shell)
    main_area.pack(side="left", fill="both", expand=True)

    def show_plugins():
        if plugin_list.winfo_manager():
            plugin_list.pack_forget()
            plugin_button.configure(text="插件管理  ▸")
        else:
            plugin_list.pack(fill="x", pady=(12, 0), after=plugin_button)
            plugin_button.configure(text="插件管理  ▾")
    plugin_button.configure(command=show_plugins)
    panel_event = tc.plugin_event()
    def release_panel_event(event):
        if event.widget is root and panel_event:
            tc.KERNEL32.CloseHandle(panel_event)
    root.bind("<Destroy>", release_panel_event, add="+")
    if show_plugin_list:
        show_plugins()

    # ---- 顶部 ----
    head = ttk.Frame(main_area, padding=(18, 16, 18, 8))
    head.pack(fill="x")
    ttk.Label(head, text="我的设备", style="H1.TLabel").pack(side="left")

    v_auto = tk.BooleanVar(value=True)
    v_interval = tk.StringVar(
        value=dict((s, l) for s, l in tc.INTERVAL_CHOICES).get(state["interval"], "1 分钟"))

    def on_auto():
        state["auto"] = v_auto.get()
        _reschedule()

    btn = ttk.Button(head, text="立即刷新", style="Accent.TButton")
    btn.pack(side="right")
    ttk.Checkbutton(head, text="自动刷新", variable=v_auto,
                    command=on_auto).pack(side="right", padx=(0, 12))

    # ---- 卡片 ----
    body = ttk.Frame(main_area, padding=(18, 12, 18, 12))
    body.pack(fill="both", expand=True)
    body.columnconfigure(0, weight=1, uniform="card")
    body.columnconfigure(1, weight=1, uniform="card")
    body.rowconfigure(0, weight=1)

    cards = {}
    plugin_vars = {}
    for column, plugin in enumerate(plugins.PLUGINS):
        body.columnconfigure(column, weight=1, uniform="card")
        card = DeviceCard(body, plugin.title)
        cards[plugin.key] = card
        variable = tk.BooleanVar(value=plugins.enabled(plugin.key, cfg))
        plugin_vars[plugin.key] = variable
        def toggle(key=plugin.key, var=variable):
            latest = tc.load_config()
            latest["devices"][key] = var.get()
            tc.save_config(latest)
            cfg.update(latest)
            tc.post_to_tray(tc.MSG_RELOAD)
            plugin = next(p for p in plugins.PLUGINS if p.key == key)
            cards[key].update(Reading(plugin.title, "正在连接…", error="正在读取电量…")
                              if var.get() else plugins.disabled_reading(plugin))
            layout_cards()
            if state["busy"]:
                state["refresh_pending"] = True
            else:
                refresh()
        ttk.Checkbutton(plugin_list, text=plugin.title, variable=variable,
                        style="Plugin.TCheckbutton", command=toggle).pack(fill="x")

    empty_state = ttk.Frame(body)
    ttk.Label(empty_state, text="还没有开启设备插件", style="H1.TLabel").pack(pady=(0, 12))
    ttk.Label(empty_state, text="点击左侧「插件管理」，开启你需要的设备。",
              style="Muted.TLabel").pack()
    def layout_cards():
        active = [p for p in plugins.PLUGINS if plugin_vars[p.key].get()]
        for card in cards.values():
            card.frame.grid_remove()
        for column in range(max(2, len(cards))):
            body.columnconfigure(column, weight=0, minsize=0)
        empty_state.place_forget()
        if not active:
            empty_state.place(relx=.5, rely=.42, anchor="center")
        else:
            for index, plugin in enumerate(active):
                column = index % 2
                body.columnconfigure(column, weight=1, uniform="card")
                body.rowconfigure(index // 2, weight=1)
                cards[plugin.key].frame.grid(row=index // 2, column=column,
                                             sticky="nsew", padx=5, pady=5)
        plugin_count.configure(text=f"已开启 {len(active)} / {len(plugins.PLUGINS)} 个插件")
    layout_cards()

    foot = ttk.Label(main_area, text="正在读取…", style="Muted.TLabel", padding=(18, 4))
    foot.pack(fill="x", side="bottom")

    # ---- 设置区 ----
    setbar = ttk.Frame(main_area, style="Panel.TFrame", padding=(14, 10))
    setbar.pack(fill="x", padx=18, pady=(2, 8))

    def refresh_tray_state():
        if state.get("starting"):
            return                              # 正在启动，别覆盖提示文字
        if state.get("notice") and time.time() < state.get("notice_until", 0):
            lab_tray.configure(text=state["notice"])   # 临时提示优先显示
            btn_tray.configure(state="normal",
                               text="退出托盘程序" if tc.is_tray_running()
                               else "启动托盘程序")
            return
        state["notice"] = ""
        running = tc.is_tray_running()
        btn_tray.configure(state="normal",
                           text="退出托盘程序" if running else "启动托盘程序")
        lab_tray.configure(text="托盘运行中 · 双击打开面板"
                                if running else "托盘未运行")

    def notify(text: str, seconds: float = 8.0) -> None:
        """在状态标签上显示一条临时提示。"""
        state["notice"] = text
        state["notice_until"] = time.time() + seconds
        refresh_tray_state()

    def on_interval(_event=None):
        sec = dict((label, sec) for sec, label in tc.INTERVAL_CHOICES)[v_interval.get()]
        cfg["interval"] = sec
        tc.save_config(cfg)
        state["interval"] = sec
        tc.post_to_tray(tc.MSG_RELOAD)      # 让托盘立刻换间隔
        _reschedule()
        refresh()

    def on_boot():
        want = bool(v_boot.get())
        ok = tc.set_autostart(want)
        cfg["autostart"] = want
        tc.save_config(cfg)
        tc.post_to_tray(tc.MSG_RELOAD)
        if want and not ok:
            notify("开机自启设置失败：无法创建启动文件夹快捷方式")
        elif want:
            notify("已加入开机自启（任务管理器 →「启动」标签里能看到 电量托盘）", 12)
        else:
            notify("已取消开机自启")

    def tray_done(ok: bool):
        state["starting"] = False
        refresh_tray_state()
        if not ok:
            notify("启动失败：可双击桌面「电量托盘」再试", 12)

    def on_links():
        btn_link.configure(state="disabled", text="正在创建…")

        def work():
            try:
                r = tc.install_desktop_links()
            except Exception as e:
                traceback.print_exc()
                r = {"folder": "", "links": {}, "errors": [str(e)]}
            results.put(("links", r))

        threading.Thread(target=work, daemon=True).start()

    def links_done(r: dict):
        import tkinter.messagebox as mb
        btn_link.configure(state="normal", text="重建桌面链接")
        bits = []
        kind = r.get("folder") or ""
        if kind:
            bits.append(f"文件夹→{win_link.KIND_LABEL.get(kind, kind)}")
        for name, k in (r.get("links") or {}).items():
            bits.append(f"{name}→{win_link.KIND_LABEL.get(k, k)}")
        if bits:
            notify("桌面链接已更新：" + "；".join(bits), 12)
        else:
            notify("桌面链接创建失败", 12)
        if r.get("errors"):
            mb.showwarning("桌面链接", "\n".join(r["errors"]))

    def on_tray_toggle():
        if tc.is_tray_running():
            tc.post_to_tray(tc.MSG_QUIT)
            for delay in (600, 1500, 3000):
                root.after(delay, refresh_tray_state)
            return

        # 启动要等托盘窗口真正出现（pythonw 是静默进程），放后台线程做，别卡界面
        state["starting"] = True
        state["started_at"] = time.time()
        btn_tray.configure(state="disabled", text="正在启动…")
        lab_tray.configure(text="正在启动托盘程序…")

        def work():
            try:
                ok = tc.start_tray_app()
            except Exception:
                traceback.print_exc()
                ok = False
            results.put(("tray", ok))          # 交给主线程处理

        threading.Thread(target=work, daemon=True).start()

    def on_ignore_blink():
        if tc.post_to_tray(tc.MSG_IGNORE_BLINK):
            btn_ignore_blink.configure(text="本次运行已关闭闪烁", state="disabled")
            notify("低电量闪烁已关闭；下次启动软件后自动恢复", 12)
        else:
            notify("托盘程序未运行，无法关闭闪烁")

    # 设置区：第一行放设置项，第二行放托盘相关按钮与状态
    row_a = ttk.Frame(setbar, style="Panel.TFrame")
    row_a.pack(fill="x")
    row_b = ttk.Frame(setbar, style="Panel.TFrame")
    row_b.pack(fill="x", pady=(9, 0))

    ttk.Label(row_a, text="设置", style="CardTitle.TLabel").pack(side="left")
    ttk.Label(row_a, text="刷新间隔", style="CardSub.TLabel").pack(side="left", padx=(16, 6))
    combo = ttk.Combobox(row_a, textvariable=v_interval, width=8, state="readonly",
                         values=[label for _, label in tc.INTERVAL_CHOICES])
    combo.pack(side="left")
    combo.bind("<<ComboboxSelected>>", on_interval)

    v_boot = tk.BooleanVar(value=tc.is_autostart_enabled())
    ttk.Checkbutton(row_a, text="开机自启", variable=v_boot,
                    command=on_boot).pack(side="left", padx=(18, 0))

    btn_tray = ttk.Button(row_b, text="退出托盘程序", command=on_tray_toggle)
    btn_tray.pack(side="right")
    btn_link = ttk.Button(row_b, text="重建桌面链接", command=on_links)
    btn_link.pack(side="right", padx=(0, 8))
    btn_ignore_blink = ttk.Button(row_b, text="本次运行关闭闪烁", command=on_ignore_blink)
    btn_ignore_blink.pack(side="right", padx=(0, 8))
    lab_tray = ttk.Label(row_b, text="", style="CardSub.TLabel")
    lab_tray.pack(side="right", padx=(0, 12))
    refresh_tray_state()

    # ---- 刷新逻辑 ----
    def apply(readings: list[Reading]):
        masked = plugins.mask_disabled(dict(zip((p.key for p in plugins.PLUGINS), readings)))
        masked = plugins.apply_last_success(masked, last_success)
        readings = list(masked.values())
        for key, reading in masked.items():
            cards[key].update(reading)
        enabled_count = sum(plugins.enabled(p.key) for p in plugins.PLUGINS)
        ok = sum(1 for r in readings if r.ok)
        foot.configure(text=f"更新于 {time.strftime('%H:%M:%S')}   "
                            f"成功读取 {ok}/{enabled_count} 个已启用设备"
                            + ("" if state["auto"] else "   （自动刷新已关闭）"))
        state["busy"] = False
        btn.configure(state="normal")
        if state.pop("refresh_pending", False):
            root.after(0, refresh)

    def worker():
        try:
            readings = read_all()
        except Exception:
            traceback.print_exc()
            readings = [Reading(plugin.title, "", error="读取异常")
                        for plugin in plugins.PLUGINS]
        results.put(("readings", readings))

    def refresh():
        if state["busy"]:
            return
        state["busy"] = True
        btn.configure(state="disabled")
        foot.configure(text="正在刷新已开启的设备…")
        threading.Thread(target=worker, daemon=True).start()

    def _reschedule():
        if state["after_id"]:
            root.after_cancel(state["after_id"])
            state["after_id"] = None
        if state["auto"]:
            state["after_id"] = root.after(state["interval"] * 1000, _tick)

    def _tick():
        refresh()
        _reschedule()

    btn.configure(command=refresh)

    root.after(300, refresh)
    _reschedule()

    # 主线程统一处理后台线程的结果 + 跟随托盘状态
    def pump():
        if panel_event and tc.KERNEL32.WaitForSingleObject(panel_event, 0) == 0:
            if not plugin_list.winfo_manager():
                show_plugins()
        try:
            while True:
                kind, payload = results.get_nowait()
                if kind == "readings":
                    apply(payload)
                elif kind == "tray":
                    tray_done(payload)
                elif kind == "links":
                    links_done(payload)
        except queue.Empty:
            pass
        except Exception:
            traceback.print_exc()
            state["busy"] = False
            state["starting"] = False
            btn.configure(state="normal")

        # 兜底：启动流程万一卡住，20 秒后放开按钮，别让它永久禁用
        if state["starting"] and time.time() - state["started_at"] > 20:
            state["starting"] = False
            refresh_tray_state()

        refresh_tray_state()        # FindWindowW 很便宜，顺带同步托盘状态
        root.after(1000, pump)

    root.after(1000, pump)
    # 托盘右键打开时保证窗口到前台
    def raise_me():
        try:
            root.lift()
            root.focus_force()
        except Exception:
            pass
    root.after(250, raise_me)
    return root


def main() -> None:
    parser = argparse.ArgumentParser(description="我的设备电量")
    parser.add_argument("--plugins", action="store_true", help="打开插件管理列表")
    parser.add_argument("--once", action="store_true", help="命令行读一次就退出")
    parser.add_argument("--install-links", action="store_true",
                        help="在桌面重建软连接（项目文件夹 + 启动脚本）")
    parser.add_argument("--autostart", choices=["on", "off", "status"],
                        help="开机自启：on 打开 / off 关闭 / status 查看")
    args = parser.parse_args()

    if args.install_links:
        r = tc.install_desktop_links()
        print("桌面链接：")
        print(f"  项目文件夹 {tc.DESKTOP_LINK_NAME} -> "
              f"{win_link.KIND_LABEL.get(r['folder'], r['folder'] or '创建失败')}")
        for name, kind in r["links"].items():
            print(f"  {name} -> {win_link.KIND_LABEL.get(kind, kind)}")
        for msg in r["errors"]:
            print("  注意：", msg)
        return

    if args.autostart:
        if args.autostart == "status":
            st = tc.autostart_status()
            print("开机自启：", "已启用" if st["enabled"] else "未启用")
            print("  方式：", st["method"])
            print("  快捷方式：", st["shortcut"],
                  "(存在)" if st["shortcut_exists"] else "(不存在)")
            print("  任务管理器状态：", st["taskmanager_state"])
            print("  目标：", st["target"])
            print("  旧注册表项：", "还在" if st["legacy_registry"] else "已清理")
        else:
            ok = tc.set_autostart(args.autostart == "on")
            print("已" + ("加入" if args.autostart == "on" else "取消") + "开机自启",
                  "" if ok else "（失败）")
        return

    if args.once:
        cli_once()
        return
    try:
        root = build_ui(show_plugin_list=args.plugins)
    except Exception:
        print("无法启动图形界面，改用命令行模式：")
        traceback.print_exc()
        cli_once()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
