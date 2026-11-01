"""Device plugins: register a reader without changing panel/tray polling logic."""
from __future__ import annotations
from dataclasses import dataclass, replace
from typing import Optional, Callable
import hid_win as hw
import battery as bt
import darkrim_proto as drp
import mchose_proto as mcp
import tray_common as tc
from hid_win import HidInterface

@dataclass
class Reading:
    title: str
    subtitle: str
    level: Optional[int] = None
    status: str = ""
    detail: str = ""
    error: str = ""
    extra: str = ""
    no_reply: bool = False
    disabled: bool = False

    @property
    def ok(self) -> bool:
        return self.level is not None


def _find(vid: int, usage_page: int, output_len: int = 0) -> Optional[HidInterface]:
    for d in hw.enumerate_hid():
        if d.vid == vid and d.usage_page == usage_page:
            if not output_len or d.output_len == output_len:
                return d
    return None


def read_atk() -> Reading:
    """ATK / VXE 无线鼠标（内置协议 2）。"""
    r = Reading("ATK 鼠标", "无接收器")
    iface = _find(0x373B, 0xFF05, 64) or _find(0x373B, 0xFF02)
    if iface is None:
        r.error = "没找到接收器（请把 2.4G 接收器插上）"
        return r
    r.subtitle = f"{iface.vid_pid} · {iface.product or '2.4G 接收器'}"
    try:
        res = bt.strategy_vendor_protocol(iface) or bt.strategy_standard_battery_usage(iface)
    except Exception as e:
        r.error = f"读取出错：{e}"
        return r
    if res is None:
        r.error = "这台设备没有可用的读取方式"
        return r
    if res.ok:
        r.level = res.level
        r.status = res.status_text
        r.detail = res.source
    else:
        r.error = res.detail or "读取失败"
        r.no_reply = r.error.startswith("设备没有回复")
        if r.no_reply:
            r.error = "未收到设备回复"
    return r


def read_darkrim() -> Reading:
    """DARKRIM SHADOW 耳机（杰理方案 dongle，逆向协议）。"""
    r = Reading("DARKRIM 耳机", "未连接")
    try:
        info = drp.read_info(timeout=0.35)
    except Exception as e:
        r.error = f"读取出错：{e}"
        return r
    if not info.online:
        r.error = info.detail or "没找到 dongle"
        return r
    r.subtitle = f"3654:6901 · {info.name or 'DARKRIM'}"
    r.level = info.battery
    r.status = ""
    r.detail = "私有 TLV 协议（TLV 0x01 = 电量）"
    bits = []
    if info.dongle_firmware:
        bits.append(f"dongle 固件 {info.dongle_firmware}")
    if info.headset_firmware:
        bits.append(f"耳机固件 {info.headset_firmware}")
    if info.address:
        bits.append(f"地址 {info.address}")
    if info.status_code is not None:
        bits.append(f"状态码 {info.status_code}")
    r.extra = " · ".join(bits)
    if r.level is None and not r.error:
        r.error = "未收到设备回复"
        r.no_reply = True
    return r


def read_mchose_keyboard() -> Reading:
    """MCHOSE G87 V2 keyboard (official M HUB 2.4G protocol)."""
    r = Reading("迈从键盘", "未连接")
    info, error = mcp.read_battery(timeout=1.5)
    if info is None:
        r.no_reply = "没有回复" in error or "未回复" in error
        r.error = "未收到设备回复" if r.no_reply else error
        return r
    r.subtitle = "3837:201B · MCHOSE G87 V2 2.4G"
    r.level = info.level
    r.status = "充电中" if info.charging else ("已充满" if info.full else "")
    r.detail = "M HUB 私有协议（命令 0x4A）"
    return r


@dataclass(frozen=True)
class DevicePlugin:
    key: str
    title: str
    read: Callable[[], Reading]


PLUGINS = (DevicePlugin("mouse", "ATK 鼠标", read_atk),
           DevicePlugin("headset", "DARKRIM 耳机", read_darkrim),
           DevicePlugin("mchose_keyboard", "迈从键盘", read_mchose_keyboard))


def enabled(key: str, config=None) -> bool:
    config = tc.load_config() if config is None else config
    return config.get("devices", {}).get(key, True) is not False


def disabled_reading(plugin: DevicePlugin) -> Reading:
    return Reading(plugin.title, "插件已关闭", error="已关闭，不读取电量",
                   disabled=True)


def read_plugins() -> dict[str, Reading]:
    results = {}
    for plugin in PLUGINS:
        # Re-check before each device: disabling one skips its next hardware call.
        if not enabled(plugin.key):
            results[plugin.key] = disabled_reading(plugin)
            continue
        try:
            result = plugin.read()
        except Exception as exc:
            result = Reading(plugin.title, "", error=f"读取失败：{exc}")
        # A read already in progress may finish, but its result must not reappear.
        results[plugin.key] = result if enabled(plugin.key) else disabled_reading(plugin)
    return results


def mask_disabled(results: dict[str, Reading]) -> dict[str, Reading]:
    config = tc.load_config()
    return {p.key: results[p.key] if enabled(p.key, config) else disabled_reading(p)
            for p in PLUGINS}


def apply_last_success(results: dict[str, Reading],
                       last_success: dict[str, Reading]) -> dict[str, Reading]:
    """Use the last successful value when an enabled device stops replying.

    ``last_success`` belongs to one running panel/tray process.  It is deliberately
    not persisted, so the first read after every launch still reports that no reply
    was received.  Disabling a plugin also forgets its cached value.
    """
    merged = {}
    for plugin in PLUGINS:
        reading = results[plugin.key]
        if reading.disabled:
            last_success.pop(plugin.key, None)
            merged[plugin.key] = reading
        elif reading.ok:
            last_success[plugin.key] = replace(reading)
            merged[plugin.key] = reading
        elif reading.no_reply:
            merged[plugin.key] = replace(last_success[plugin.key]) \
                if plugin.key in last_success else replace(
                    reading, error="未收到设备回复")
        else:
            merged[plugin.key] = reading
    return merged
