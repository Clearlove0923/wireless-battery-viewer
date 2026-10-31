import runpy
import unittest
from unittest.mock import patch, Mock
import tray_app as tray
import tray_common as tc


class TrayAlertTests(unittest.TestCase):
    def test_threshold_and_unknown_devices(self):
        for mouse, headset, expected in [(20, None, False), (19, None, True),
                                         (80, 0, True), (None, None, False),
                                         (20, 20, False), (None, 19, True)]:
            self.assertEqual(tray.needs_low_battery_alert(
                {'mouse': (mouse, ''), 'headset': (headset, '')}), expected)

    def test_blink_stops_on_recovery_and_does_not_poll_hardware(self):
        app = tray.TrayApp()
        app.hwnd = 123
        app.levels = {'mouse': (19, ''), 'headset': (None, '')}
        with patch.object(tray.USER32, 'SetTimer') as start, patch.object(tray.USER32, 'KillTimer') as stop:
            app.sync_blink()
            app.sync_blink()
            start.assert_called_once_with(123, tray.BLINK_TIMER, 600, None)
            app.update_icons = Mock()
            app.refresh_now = Mock()
            app.wnd_proc(123, tray.WM_TIMER, tray.BLINK_TIMER, 0)
            self.assertFalse(app.blink_bright)
            app.update_icons.assert_called_once()
            app.refresh_now.assert_not_called()
            app.levels['mouse'] = (20, '')
            app.sync_blink()
            self.assertFalse(app.blink_active)
            self.assertTrue(app.blink_bright)
            stop.assert_called_once_with(123, tray.BLINK_TIMER)

    def test_default_launch_is_tray(self):
        with patch('sys.argv', ['BatteryViewer.exe']), patch('tray_app.main', return_value=0) as main:
            with self.assertRaises(SystemExit):
                runpy.run_path('launcher.py', run_name='__main__')
            main.assert_called_once()

    def test_debug_demo_uses_enabled_device_and_triggers_blink(self):
        app = tray.TrayApp()
        app.hwnd = 123
        app.update_icons = Mock()
        config = {'devices': {'mouse': True, 'headset': False}}
        with patch.dict('os.environ', {'BATTERY_VIEWER_DEBUG': '1'}), \
             patch.object(tray.tc, 'load_config', return_value=config), \
             patch.object(tray.USER32, 'KillTimer'), \
             patch.object(tray.USER32, 'SetTimer') as timer:
            self.assertTrue(app.set_demo_level(12))
        self.assertEqual(app.levels['mouse'][0], 12)
        self.assertTrue(app.blink_active)
        timer.assert_any_call(123, tray.DEMO_TIMER, tray.DEMO_DURATION_MS, None)

    def test_blink_off_frame_uses_transparent_icon(self):
        app = tray.TrayApp()
        app.hwnd = 123
        app.blink_active = True
        app.blink_bright = False
        config = {'devices': {'mouse': True, 'headset': False}}
        with patch.object(tray.tc, 'load_config', return_value=config), \
             patch.object(tray.win_icon, 'make_hicon', return_value=1) as icon, \
             patch.object(tray.SHELL32, 'Shell_NotifyIconW', return_value=True):
            app._apply_icon(tray.NIM_MODIFY)
        icon.assert_called_once_with('blank', (255, 70, 50))

    def test_ignore_blink_lasts_for_session_only(self):
        app = tray.TrayApp()
        app.hwnd = 123
        app.levels = {'mouse': (12, ''), 'headset': (80, '')}
        app.update_icons = Mock()
        with patch.object(tray.USER32, 'SetTimer'), patch.object(tray.USER32, 'KillTimer'):
            app.sync_blink()
            self.assertTrue(app.blink_active)
            app.ignore_blink_for_session()
            self.assertFalse(app.blink_active)
            self.assertTrue(app.blink_ignored)
            app.sync_blink()
            self.assertFalse(app.blink_active)
        restarted = tray.TrayApp()
        self.assertFalse(restarted.blink_ignored)

    def test_panel_entry_is_explicit(self):
        with patch('sys.frozen', True, create=True):
            self.assertEqual(tc.launch_command('my_devices.py')[-1], '--panel')
        with patch('sys.argv', ['BatteryViewer.exe', '--panel']), patch('my_devices.main') as main:
            with self.assertRaises(SystemExit):
                runpy.run_path('launcher.py', run_name='__main__')
            main.assert_called_once()


if __name__ == '__main__':
    unittest.main()
