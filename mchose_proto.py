"""MCHOSE G87 V2 2.4G keyboard battery protocol."""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Optional

import hid_win as hw

VID = 0x3837
PID = 0x201B
USAGE_PAGE = 0xFF02
USAGE = 0x0002
REPORT_LEN = 20


@dataclass(frozen=True)
class BatteryInfo:
    level: int
    charging: bool
    full: bool


def battery_request() -> bytes:
    packet = bytes([0x13, 0x4A, 1]) + bytes(16)
    return packet + bytes([sum(packet) & 0xFF])


def parse_battery_reply(data: bytes) -> Optional[BatteryInfo]:
    if len(data) != REPORT_LEN:
        return None
    if data[:4] != bytes([0x13, 0x4A, 1, 0]):
        return None
    if sum(data[:-1]) & 0xFF != data[-1]:
        return None
    level, flags = data[5:7]
    if level > 100:
        return None
    full = bool(flags >> 4)
    return BatteryInfo(100 if full else level, (flags & 0x0F) == 1, full)


def find_interface() -> Optional[hw.HidInterface]:
    matches = [d for d in hw.enumerate_hid()
               if (d.vid, d.pid, d.usage_page, d.usage,
                   d.input_len, d.output_len)
               == (VID, PID, USAGE_PAGE, USAGE, REPORT_LEN, REPORT_LEN)]
    return matches[0] if len(matches) == 1 else None


def read_battery(timeout: float = 1.5) -> tuple[Optional[BatteryInfo], str]:
    iface = find_interface()
    if iface is None:
        return None, "没找到迈从 G87 V2 2.4G 接收器"
    try:
        with hw.HidDevice(iface.path, write=True) as device:
            device.drain()
            device.write_output(battery_request(), use_hidd=False)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                remaining = max(1, min(100, int((deadline - time.monotonic()) * 1000)))
                data = device.read_input(remaining)
                if data:
                    info = parse_battery_reply(data)
                    if info is not None:
                        return info, ""
    except Exception as exc:
        return None, f"读取失败：{exc}"
    return None, "键盘没有回复（请确认处于 2.4G 模式并按键唤醒）"
