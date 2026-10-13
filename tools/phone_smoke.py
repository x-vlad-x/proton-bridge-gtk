"""Manual on-device startup/navigation/background check, without signing in.

Run with the installed launcher's PYTHONPATH and PROTON_BRIDGE_GTK_ROOT.
Screenshots stay in /tmp and contain only the empty-account interface.
"""
import argparse
from pathlib import Path
import sys
from google.protobuf import wrappers_pb2
from proton_bridge_gtk.app import BridgeApplication
from gi.repository import GLib, Gtk

app = BridgeApplication(argparse.Namespace(demo=None, no_window=False, language="en"))
Gtk.Settings.get_default().set_property("gtk-enable-animations", False)
attempts = 0
stage = 0
failed = False
folder = Path("/tmp/proton-bridge-gtk-check")
folder.mkdir(exist_ok=True)


def capture(name):
    window = app.window
    paintable = Gtk.WidgetPaintable.new(window)
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, window.get_width(), window.get_height())
    node = snapshot.to_node()
    window.get_renderer().render_texture(node, None).save_to_png(str(folder / f"{name}.png"))


def check():
    global stage, attempts, failed
    attempts += 1
    window = app.window
    try:
        if window.main_stack.get_visible_child_name() == "error":
            raise RuntimeError(window.error_page.get_description())
        if not window.connected:
            if attempts > 60:
                raise TimeoutError("Startup check timed out")
            return GLib.SOURCE_CONTINUE
        if stage == 0:
            print(f'Connected to core {window.data["version"]}; accounts={len(window.data["users"])}; size={window.get_width()}x{window.get_height()}', flush=True)
            if not window.data["users"]:
                capture("welcome")
            window.open_settings()
        elif stage == 1:
            assert window.settings.version.get_subtitle() == "3.27.1"
            initial = window.backend.call("IsAutostartOn").value
            if not initial:
                try:
                    window.backend.call("SetIsAutostartOn", wrappers_pb2.BoolValue(value=True))
                    entries = list((Path.home()/".config/autostart").glob("*.desktop"))
                    assert any("proton-bridge-gtk/proton-bridge-gtk" in p.read_text() and "--no-window" in p.read_text() for p in entries)
                finally:
                    window.backend.call("SetIsAutostartOn", wrappers_pb2.BoolValue(value=False))
            print("Autostart launcher check passed; original preference retained.", flush=True)
            capture("settings")
            window.nav.pop()
        elif stage == 2:
            window.open_login()
        elif stage == 3:
            assert window.login.stage == "Login"
            capture("login")
            window.nav.pop()
        elif stage == 4:
            window.close()
            assert not window.get_visible()
            assert window.backend.process.poll() is None
            assert window.backend.call("Version").value == "3.27.1"
            print("On-device navigation, real authenticated RPC and background check passed.", flush=True)
            app.quit()
            return GLib.SOURCE_REMOVE
        stage += 1
    except Exception as exc:
        print(f"FAIL: {exc}", flush=True)
        failed = True
        app.quit()
        return GLib.SOURCE_REMOVE
    return GLib.SOURCE_CONTINUE


GLib.timeout_add_seconds(1, check)
app.run([sys.argv[0]])
raise SystemExit(1 if failed else 0)
