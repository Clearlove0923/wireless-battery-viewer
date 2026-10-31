import unittest
from unittest.mock import Mock, patch
import device_plugins as p
import tray_common as tc
import tray_app


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.mouse = Mock(return_value=p.Reading('Mouse', '', level=10))
        self.headset = Mock(return_value=p.Reading('Headset', '', level=80))
        self.registry = (p.DevicePlugin('mouse', 'Mouse', self.mouse),
                         p.DevicePlugin('headset', 'Headset', self.headset))
        self.config = {'interval': 60, 'autostart': False,
                       'devices': {'mouse': False, 'headset': True,
                                   'mchose_keyboard': False}}

    def test_disabled_reader_is_not_called_and_reenable_reads(self):
        with patch.object(p, 'PLUGINS', self.registry), patch.object(tc, 'load_config', return_value=self.config):
            results = p.read_plugins()
            self.mouse.assert_not_called()
            self.headset.assert_called_once()
            self.assertIsNone(results['mouse'].level)
            self.config['devices']['mouse'] = True
            self.assertEqual(p.read_plugins()['mouse'].level, 10)
            self.mouse.assert_called_once()

    def test_all_disabled_does_not_call_any_reader(self):
        self.config['devices']['headset'] = False
        with patch.object(p, 'PLUGINS', self.registry), patch.object(tc, 'load_config', return_value=self.config):
            results = p.read_plugins()
        self.mouse.assert_not_called()
        self.headset.assert_not_called()
        self.assertTrue(all(r.level is None for r in results.values()))

    def test_disable_during_read_discards_result(self):
        self.config['devices']['mouse'] = True
        def read():
            self.config['devices']['mouse'] = False
            return p.Reading('Mouse', '', level=10)
        self.mouse.side_effect = read
        with patch.object(p, 'PLUGINS', self.registry), patch.object(tc, 'load_config', return_value=self.config):
            self.assertIsNone(p.read_plugins()['mouse'].level)

    def test_tray_discards_queued_disabled_low_reading(self):
        with patch.object(tc, 'load_config', return_value=self.config):
            app = tray_app.TrayApp()
            app.pending_levels = {'mouse': p.Reading('Mouse', '', level=10),
                                  'headset': p.Reading('Headset', '', level=80),
                                  'mchose_keyboard': p.Reading('Keyboard', '', level=15)}
            app.update_icons = Mock()
            app.on_refresh_done()
            self.assertFalse(app.blink_active)
            self.assertIsNone(app.levels['mouse'][0])

    def test_one_plugin_error_does_not_block_next(self):
        self.config['devices']['mouse'] = True
        self.mouse.side_effect = RuntimeError('test error')
        with patch.object(p, 'PLUGINS', self.registry), patch.object(tc, 'load_config', return_value=self.config):
            self.assertEqual(p.read_plugins()['headset'].level, 80)

    def test_mchose_plugin_maps_protocol_result(self):
        info = p.mcp.BatteryInfo(level=54, charging=False, full=False)
        with patch.object(p.mcp, 'read_battery', return_value=(info, '')):
            reading = p.read_mchose_keyboard()
        self.assertEqual(reading.level, 54)
        self.assertIn('0x4A', reading.detail)

    def test_mchose_plugin_preserves_reader_error(self):
        with patch.object(p.mcp, 'read_battery', return_value=(None, '键盘未回复')):
            reading = p.read_mchose_keyboard()
        self.assertIsNone(reading.level)
        self.assertEqual(reading.error, '键盘未回复')


if __name__ == '__main__':
    unittest.main()
