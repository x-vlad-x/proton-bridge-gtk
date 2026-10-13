"""Capture every published screenshot in English using the offline demo.

Run with the same Python/library paths as the installed launcher. The explicit
locale prevents the desktop's language from appearing in screenshots.
"""
import argparse
import os
from pathlib import Path
import sys

os.environ["LC_ALL"] = "C.UTF-8"
os.environ["LANG"] = "C.UTF-8"
os.environ["LANGUAGE"] = "en"

from proton_bridge_gtk.app import BridgeApplication
from proton_bridge_gtk.demo import DemoBackend
from gi.repository import GLib, Gtk

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
app = BridgeApplication(argparse.Namespace(demo="empty", no_window=False, language="en"))
Gtk.Settings.get_default().set_property("gtk-enable-animations", False)
step = 0
attempts = 0
failed = False


def capture(name):
    window = app.window
    paintable = Gtk.WidgetPaintable.new(window)
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, window.get_width(), window.get_height())
    node = snapshot.to_node()
    if node is None:
        raise RuntimeError("Window did not render")
    texture = window.get_renderer().render_texture(node, None)
    if not texture.save_to_png(str(args.output / f"{name}.png")):
        raise OSError("Could not save screenshot")


def check():
    global step, failed, attempts
    attempts += 1
    window = app.window
    if not window or not window.connected:
        if attempts >= 30:
            print("Screenshot startup timed out", file=sys.stderr)
            failed = True
            app.quit()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE
    try:
        if step == 0:
            capture("welcome")
            window.backend.users = DemoBackend(lambda *_args: None, lambda _event: None).users
            window.apply_snapshot(window.backend.snapshot())
        elif step == 1:
            capture("accounts")
            window.open_account("demo")
        elif step == 2:
            capture("account")
            window.nav.pop()
        elif step == 3:
            window.open_settings()
        elif step == 4:
            capture("settings")
            capture("phone-settings")
            window.nav.pop()
        elif step == 5:
            window.open_login()
        elif step == 6:
            capture("login")
            app.quit()
            return GLib.SOURCE_REMOVE
    except Exception as exc:
        print(f"Screenshot capture failed: {exc}", file=sys.stderr)
        failed = True
        app.quit()
        return GLib.SOURCE_REMOVE
    step += 1
    return GLib.SOURCE_CONTINUE


GLib.timeout_add_seconds(1, check)
app.run([sys.argv[0]])
raise SystemExit(1 if failed else 0)
