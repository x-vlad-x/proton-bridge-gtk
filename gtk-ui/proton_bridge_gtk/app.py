import argparse
import os
from pathlib import Path
import signal
import sys

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk
from . import APP_ID, preferences
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
        self.preferences_path = preferences.default_path()
        stored = preferences.load(self.preferences_path)
        language = getattr(args, "language", None)
        if language is None:
            language = stored.get("language", "system")
        if language not in dict(LANGUAGES):
            language = "system"
        set_language(language)
        # The offline demo must never change how the real core synchronises.
        self.sync_settings = {} if args.demo else stored
        self.repair_requested = False
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

    def make_backend(self, wait_keyring=False):
        if self.args.demo:
            from .demo import DemoBackend
            return DemoBackend(dispatch, lambda e: self.window.event(e), empty=self.args.demo == "empty")
        return Backend(os.environ.get("PROTON_BRIDGE_GTK_ROOT", Path(__file__).resolve().parents[2]),
                       dispatch, lambda e: self.window.event(e), lambda m: self.window.failed(m),
                       sync_oldest_first=self.sync_oldest_first, wait_keyring=wait_keyring)

    @property
    def sync_oldest_first(self):
        return self.sync_settings.get("sync_oldest_first") is True

    @property
    def sync_repair_pending(self):
        return self.sync_settings.get("sync_repair_pending") is True

    def save_sync(self, **changes):
        if self.args.demo:
            self.sync_settings.update(changes)
        else:
            self.sync_settings = preferences.save(self.preferences_path, **changes)

    def set_sync_oldest_first(self, enabled):
        # Mark the repair first: if anything stops before it runs, the next start repeats it.
        try:
            self.save_sync(sync_oldest_first=enabled, sync_repair_pending=True)
        except OSError as exc:
            self.window.toast(str(exc))
            return
        self.window.connected = False
        self.window.nav.pop_to_page(self.window.main_page)
        # The core reads the order only at startup.
        self.retry()

    def users_loaded(self):
        # Repair needs the loaded users: it rebuilds each Gluon store and restarts sync.
        if not self.sync_repair_pending or self.repair_requested:
            return
        self.repair_requested = True
        def failed(_message):
            self.repair_requested = False
            self.window.toast(_("Could not start resynchronisation. Bridge will try again when it next starts."))
        self.backend.submit(lambda: self.backend.call("TriggerRepair"), None, failed)

    def repair_started(self):
        # Upstream sends this after every account's cache was removed and sync restarted.
        self.repair_requested = False
        if not self.sync_repair_pending:
            return
        try:
            self.save_sync(sync_repair_pending=False)
        except OSError as exc:
            self.window.toast(str(exc))
            return
        self.window.toast(_("Resynchronisation started. Bridge is downloading your mail again."))
        self.window.refresh()

    def activate(self, *_args):
        if not self.window:
            self.backend = self.make_backend(wait_keyring=self.args.no_window)
            self.window = BridgeWindow(self)
            if self.args.demo:
                self.window.set_title("Proton Bridge · " + _("Demo"))
                self.window.header_title.set_subtitle(_("Demo · Offline preview"))
            self.backend.start(self.ready, self.window.failed)
            if not self.args.no_window:
                self.window.present()
        else:
            # The user is here: let the core ask for the keyring if it is still locked.
            self.backend.wait_keyring = False
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
            preferences.save(self.preferences_path, language=language)
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
        self.repair_requested = False
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
