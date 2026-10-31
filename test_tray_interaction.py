import unittest
from unittest.mock import Mock, patch
import tray_app as t
import tray_common as tc


class TrayInteractionTests(unittest.TestCase):
    def test_mouse_gestures(self):
        app = t.TrayApp()
        app.show_menu = Mock()
        app.open_ui = Mock()
        app.refresh_now = Mock()
        for event in (t.WM_LBUTTONUP, t.WM_LBUTTONDBLCLK, t.WM_LBUTTONUP, t.WM_RBUTTONUP):
            app.wnd_proc(1, t.MSG_TRAY_CALLBACK, 1, event)
        app.open_ui.assert_called_once_with()
        app.show_menu.assert_called_once_with()
        app.refresh_now.assert_not_called()

    def test_menu_commands_and_cleanup(self):
        app = t.TrayApp()
        app.hwnd = 1
        for selection in (t.MENU_EXIT, t.MENU_PLUGINS, t.MENU_PANEL, 0):
            app.quit, app.open_ui = Mock(), Mock()
            with patch.object(t.USER32, 'CreatePopupMenu', return_value=123), \
                 patch.object(t.USER32, 'AppendMenuW') as append, \
                 patch.object(t.USER32, 'GetCursorPos', return_value=True), \
                 patch.object(t.USER32, 'SetForegroundWindow'), \
                 patch.object(t.USER32, 'TrackPopupMenu', return_value=selection), \
                 patch.object(t.USER32, 'PostMessageW'), \
                 patch.object(t.USER32, 'DestroyMenu') as destroy:
                app.show_menu()
                self.assertEqual([c.args[3] for c in append.call_args_list], ['主界面', '插件', '退出'])
                destroy.assert_called_once_with(123)
            if selection == t.MENU_EXIT:
                app.quit.assert_called_once()
            elif selection == t.MENU_PLUGINS:
                app.open_ui.assert_called_once_with(show_plugins=True)
            elif selection == t.MENU_PANEL:
                app.open_ui.assert_called_once_with()
            else:
                app.quit.assert_not_called()
                app.open_ui.assert_not_called()

    def test_blinking_menu_offers_session_ignore(self):
        app = t.TrayApp()
        app.hwnd = 1
        app.blink_active = True
        app.ignore_blink_for_session = Mock()
        with patch.object(t.USER32, 'CreatePopupMenu', return_value=123), \
             patch.object(t.USER32, 'AppendMenuW') as append, \
             patch.object(t.USER32, 'GetCursorPos', return_value=True), \
             patch.object(t.USER32, 'SetForegroundWindow'), \
             patch.object(t.USER32, 'TrackPopupMenu', return_value=t.MENU_IGNORE_BLINK), \
             patch.object(t.USER32, 'PostMessageW'), \
             patch.object(t.USER32, 'DestroyMenu'):
            app.show_menu()
        self.assertEqual([c.args[3] for c in append.call_args_list],
                         ['主界面', '插件', '忽略低电量闪烁', '退出'])
        app.ignore_blink_for_session.assert_called_once()

    def test_tooltip_omits_disabled_devices(self):
        app = t.TrayApp()
        app.levels = {'mouse': (25, ''), 'headset': (10, ''),
                      'mchose_keyboard': (54, '')}
        tips = []
        def capture(action, pointer):
            tips.append(pointer._obj.szTip)
            return True
        with patch.object(tc, 'load_config', return_value={'devices': {
                 'mouse': True, 'headset': False, 'mchose_keyboard': False}}), \
             patch.object(t.win_icon, 'make_hicon', return_value=0), \
             patch.object(t.SHELL32, 'Shell_NotifyIconW', side_effect=capture):
            app._apply_icon(t.NIM_MODIFY)
        self.assertIn('25%', tips[0])
        self.assertNotIn('DARKRIM', tips[0])
        self.assertNotIn('10%', tips[0])

    def test_existing_panel_receives_plugin_request(self):
        app = t.TrayApp()
        with patch.object(tc, 'ui_hwnd', return_value=123), \
             patch.object(tc, 'request_plugin_panel') as request, \
             patch.object(t.USER32, 'ShowWindow'), patch.object(t.USER32, 'SetForegroundWindow'):
            app.open_ui(show_plugins=True)
            request.assert_called_once()


if __name__ == '__main__':
    unittest.main()
