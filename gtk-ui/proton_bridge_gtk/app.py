import argparse
import json
import os
from pathlib import Path
import signal
import sys

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk
from . import APP_ID
from .backend import Backend
from .i18n import LANGUAGES, _, set_language
from .window import BridgeWindow


def dispatch(callback, *args):
    def invoke():
        callback(*args)
        return GLib.SOURCE_REMOVE
    GLib.idle_add(invoke)


class BridgeApplication(Adw.Application):
    def __init__(self, args):
        super().__init__(application_id=APP_ID + (".Preview" if args.demo else ""), flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.args = args
        self.preferences_path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "proton-bridge-gtk/preferences.json"
        language = getattr(args, "language", None)
        if language is None:
            try:
                language = json.loads(self.preferences_path.read_text())["language"]
            except (OSError, ValueError, KeyError):
                language = "system"
        if language not in dict(LANGUAGES):
            language = "system"
        set_language(language)
        self.window = None
        self.backend = None
        self.connect("startup", self.startup)
        self.connect("activate", self.activate)
        self.connect("shutdown", self.shutdown)

    def startup(self, *_):
        self.hold()
        for name, callback in (
            ("add-account", lambda: self.window.open_login()),
            ("settings", lambda: self.window.open_settings()),
            ("support", lambda: self.window.open_uri("https://proton.me/support/mail/bridge")),
            ("about", lambda: self.window.about()),
            ("quit", lambda: self.window.quit_bridge()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, cb=callback: cb())
            self.add_action(action)
        self.set_accels_for_action("app.add-account", ["<Control>n"])
        self.set_accels_for_action("app.settings", ["<Control>comma"])
        self.set_accels_for_action("app.quit", ["<Control>q"])
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.stop_signal)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.stop_signal)

    def stop_signal(self):
        self.quit()
        return GLib.SOURCE_REMOVE

    def make_backend(self):
        if self.args.demo:
            from .demo import DemoBackend
            return DemoBackend(dispatch, lambda e: self.window.event(e), empty=self.args.demo == "empty")
        return Backend(os.environ.get("PROTON_BRIDGE_GTK_ROOT", Path(__file__).resolve().parents[2]),
                       dispatch, lambda e: self.window.event(e), lambda m: self.window.failed(m))

    def activate(self, *_args):
        if not self.window:
            self.backend = self.make_backend()
            self.window = BridgeWindow(self)
            if self.args.demo:
                self.window.set_title("Proton Bridge · " + _("Demo"))
                self.window.header_title.set_subtitle(_("Demo · Offline preview"))
            self.backend.start(self.ready, self.window.failed)
            if not self.args.no_window:
                self.window.present()
        else:
            self.window.present()

    def ready(self, data):
        self.window.ready(data)
        command = os.environ.get("PROTON_BRIDGE_GTK_OPEN", "")
        if command == "settings":
            self.window.open_settings()
        elif command == "login":
            self.window.open_login()
        elif command == "account" and data["users"]:
            self.window.open_account(data["users"][0].id)

    def change_language(self, language):
        if language not in dict(LANGUAGES):
            return
        try:
            self.preferences_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temp = self.preferences_path.with_suffix(".tmp")
            temp.write_text(json.dumps({"language": language}, ensure_ascii=True) + "\n")
            temp.replace(self.preferences_path)
        except OSError as exc:
            self.window.toast(str(exc))
            return
        set_language(language)
        old = self.window
        if old.login:
            old.login.on_hidden()
        data = old.data
        connected, internet = old.connected, old.internet
        self.window = BridgeWindow(self)
        self.window.set_default_size(old.get_width(), old.get_height())
        self.window.internet = internet
        if self.args.demo:
            self.window.set_title("Proton Bridge · " + _("Demo"))
            self.window.header_title.set_subtitle(_("Demo · Offline preview"))
        if connected:
            self.window.ready(data)
            self.window.open_settings()
        else:
            self.window.failed(old.error_page.get_description())
        old.destroy()
        self.window.present()

    def retry(self):
        self.window.main_stack.set_visible_child_name("loading")
        old = self.backend
        # Reap a failed start before trying again, off the main loop.
        import threading
        def restart():
            old.close()
            dispatch(self.restart_backend)
        threading.Thread(target=restart, daemon=True).start()

    def restart_backend(self):
        self.backend = self.make_backend()
        self.window.backend = self.backend
        self.backend.start(self.ready, self.window.failed)

    def shutdown(self, *_):
        if self.backend:
            self.backend.close()


def main():
    parser = argparse.ArgumentParser(description="GTK4 + libadwaita interface for Proton Mail Bridge")
    parser.add_argument("--no-window", action="store_true", help="Start in the background (autostart)")
    parser.add_argument("--demo", nargs="?", const="accounts", choices=("accounts", "empty"), help="Offline interface preview; no real accounts")
    parser.add_argument("--language", choices=[code for code, _label in LANGUAGES], help="Override application language for this launch")
    args = parser.parse_args()
    os.umask(0o077)
    app = BridgeApplication(args)
    return app.run([sys.argv[0]])
