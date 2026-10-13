"""Verify live language changes, translated titles and mobile window width."""
import argparse
from pathlib import Path
import tempfile
import sys
from proton_bridge_gtk.app import BridgeApplication
from proton_bridge_gtk.i18n import LANGUAGES, catalog
from gi.repository import GLib, Gtk

app = BridgeApplication(argparse.Namespace(demo="accounts", no_window=False, language="en"))
preferences_tmp = tempfile.TemporaryDirectory()
app.preferences_path = Path(preferences_tmp.name) / "preferences.json"
Gtk.Settings.get_default().set_property("gtk-enable-animations", False)
codes = [code for code, _label in LANGUAGES if code != "system"]
step = -1
backend = None
failed = False


def check():
    global step, backend, failed
    try:
        if step == -1:
            assert app.window.connected
            app.window.set_default_size(360, 720)
            app.window.open_settings()
            backend = app.backend
        else:
            code = codes[step]
            assert app.window.settings.page.get_title() == catalog(code)["Settings"]
            assert app.backend is backend
            assert app.window.get_width() <= 360, f"{code}: forced window width {app.window.get_width()}"
            if step + 1 == len(codes):
                app.quit()
                return GLib.SOURCE_REMOVE
        step += 1
        app.window.settings.language.set_selected([code for code, _label in LANGUAGES].index(codes[step]))
    except Exception:
        import traceback
        traceback.print_exc()
        failed = True
        app.quit()
        return GLib.SOURCE_REMOVE
    return GLib.SOURCE_CONTINUE


GLib.timeout_add(700, check)
app.run([sys.argv[0]])
preferences_tmp.cleanup()
if failed:
    raise SystemExit(1)
print("All seven application languages render at 360px and retain the running backend.")
