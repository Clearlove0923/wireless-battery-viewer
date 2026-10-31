import unittest

from mchose_proto import BatteryInfo, battery_request, parse_battery_reply


class MchoseProtocolTests(unittest.TestCase):
    def test_official_query(self):
        self.assertEqual(battery_request(), bytes.fromhex(
            '13 4a 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 5e'))

    def test_synthetic_reply_layout(self):
        data = bytes([0x13, 0x4a, 1, 0, 2, 75, 0x01]) + bytes(13)
        data = bytearray(data)
        data[-1] = sum(data[:-1]) & 0xFF
        data = bytes(data)
        self.assertEqual(parse_battery_reply(data), BatteryInfo(75, True, False))
        for index, value in [(0, 0), (1, 0x41), (2, 2), (3, 1), (5, 255)]:
            invalid = bytearray(data)
            invalid[index] = value
            self.assertIsNone(parse_battery_reply(invalid))
        for length in range(20):
            self.assertIsNone(parse_battery_reply(data[:length]))
        self.assertIsNone(parse_battery_reply(data + b'\x00'))

    def test_checksum_and_full_status(self):
        data = bytearray([0x13, 0x4a, 1, 0, 2, 36, 0x10] + [0] * 13)
        data[-1] = sum(data[:-1]) & 0xFF
        self.assertEqual(parse_battery_reply(bytes(data)), BatteryInfo(100, False, True))
        data[-1] ^= 1
        self.assertIsNone(parse_battery_reply(bytes(data)))


if __name__ == '__main__':
    unittest.main()
