import unittest
from dataclasses import replace
from unittest.mock import patch

import battery as bt


class AtkProtocolTests(unittest.TestCase):
    def setUp(self):
        self.spec = next(s for s in bt.BUILTIN_PROTOCOLS
                         if s.vid == 0x373B and s.usage_page == 0xFF02)
        self.valid = bytes.fromhex('08 04 00 00 00 02 19 00 0e 52 00 00 00 00 00 00 ce')
        self.error = bytes.fromhex('08 04 01 00 00 00 00 00 00 00 00 00 00 00 00 00 48')

    def test_request_has_checksum_at_byte_16(self):
        for spec in bt.BUILTIN_PROTOCOLS:
            if spec.vid in (0x373B, 0x3554) and spec.usage_page == 0xFF02:
                frame = bytes([spec.report_id] + spec.payload)
                self.assertEqual(len(frame), 17)
                self.assertEqual(frame[-1], 0x49)
                self.assertEqual(sum(frame) & 255, 0x55)

    def test_real_reply_and_error(self):
        result = bt._parse_spec_response(self.spec, self.valid, None, 'output')
        self.assertTrue(result.ok)
        self.assertEqual(result.level, 25)
        self.assertEqual(result.status, 'discharging')
        for invalid in (self.error, self.valid[:-1], self.valid[:-1] + b'\x00'):
            self.assertFalse(bt._parse_spec_response(self.spec, invalid, None, 'output').ok)

    def test_error_reply_is_skipped(self):
        class Device:
            def drain(self): pass
            def write_output(self, data): self.sent = data
            def read_input(self, timeout_ms): return next(self.replies)
        dev = Device()
        dev.replies = iter([self.error, self.valid])
        with patch('battery.time.sleep'):
            self.assertEqual(bt._read_report_after_request(dev, self.spec), self.valid)

    def test_unmatched_reply_is_never_returned_on_timeout(self):
        class Device:
            def drain(self): pass
            def write_output(self, data): pass
            def read_input(self, timeout_ms): return b'\x08\x04\x01' + bytes(14)
        with patch('battery.time.sleep'), patch('battery.time.monotonic', side_effect=[0, 0, 1]):
            self.assertEqual(bt._read_report_after_request(Device(), replace(self.spec, retries=1)), b'')


if __name__ == '__main__':
    unittest.main()
