"""Single executable entry point for the panel, tray and diagnostic UI."""
import sys


if __name__ == "__main__":
    if "--uninstall-cleanup" in sys.argv:
        import os
        import tray_common as tc
        import win_shell
        target = win_shell.read_shortcut(tc.startup_lnk()).get("target", "")
        if target and os.path.normcase(os.path.abspath(target)) == os.path.normcase(sys.executable):
            tc.set_autostart(False)
        pid = tc.read_pid()
        if pid and os.path.normcase(tc.process_image(pid)) == os.path.normcase(sys.executable):
            tc.post_to_tray(tc.MSG_QUIT)
        sys.exit(0)
    if "--tray" in sys.argv:
        sys.argv.remove("--tray")
        from tray_app import main
    elif "--diagnostics" in sys.argv:
        sys.argv.remove("--diagnostics")
        from app import main
    elif "--panel" in sys.argv or any(arg in sys.argv for arg in ("--once", "--autostart", "--install-links")):
        if "--panel" in sys.argv:
            sys.argv.remove("--panel")
        from my_devices import main
    else:
        from tray_app import main
    sys.exit(main())
