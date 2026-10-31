"""Read-only MCHOSE G87 V2 wireless battery diagnostic.

No settings, firmware, pairing, or wake commands are sent. This is deliberately
The protocol was validated on a 3837:201B receiver on 2026-10-28.
"""
from __future__ import annotations

import argparse
import time
from mchose_proto import battery_request, parse_battery_reply


def main() -> int:
    import hid_win as hw

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--query', action='store_true',
                        help='Send the single known battery query; default only lists interfaces')
    parser.add_argument('--transport', choices=['writefile', 'hidd'], default='writefile')
    parser.add_argument('--timeout', type=float, default=3.0)
    args = parser.parse_args()
    if not 0 < args.timeout <= 10:
        parser.error('--timeout must be greater than 0 and at most 10 seconds')
    interfaces = [d for d in hw.enumerate_hid() if (d.vid, d.pid) == (0x3837, 0x201B)]
    for d in interfaces:
        print(f'{d.vid_pid} {d.product!r} page={d.usage_page:04X} usage={d.usage:04X} '
              f'in={d.input_len} out={d.output_len} feature={d.feature_len} error={d.error}')
    if not args.query:
        return 0 if interfaces else 1
    targets = [d for d in interfaces if (d.usage_page, d.usage, d.input_len, d.output_len)
               == (0xFF02, 2, 20, 20)]
    if len(targets) != 1:
        print('Expected exactly one matching vendor interface; no query sent.')
        return 1
    with hw.HidDevice(targets[0].path, write=True) as device:
        # Establish the separate overlapped reader before sending the request.
        device.read_input(20)
        if not device._read_handle:
            print('Cannot open input reader; no query sent.')
            return 1
        packet = battery_request()
        print('TX', packet.hex(' '))
        device.write_output(packet, use_hidd=args.transport == 'hidd')
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            data = device.read_input(max(1, min(200, int((deadline-time.monotonic())*1000))))
            if data:
                print('RX', data.hex(' '))
                decoded = parse_battery_reply(data)
                if decoded is not None:
                    print('Battery reading:', decoded)
                    return 0
    print('No matching reply. Sleep, disconnection, contention, or protocol differences remain possible.')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
