"""Exercise the actual native widget tree, navigation and login event flow."""
import argparse
import os
from pathlib import Path
import sys
import json
import tempfile
from proton_bridge_gtk.app import BridgeApplication
from proton_bridge_gtk import bridge_pb2 as pb
from gi.repository import GLib, Gtk

app = BridgeApplication(argparse.Namespace(demo="accounts", no_window=False, language="en"))
preferences_tmp = tempfile.TemporaryDirectory()
app.preferences_path = Path(preferences_tmp.name) / "preferences.json"
original_backend = None
Gtk.Settings.get_default().set_property("gtk-enable-animations", False)
failures = []
screen_dir = Path(os.environ.get("SCREENSHOT_DIR", "/src/out/screenshots"))
screen_dir.mkdir(parents=True, exist_ok=True)
step = 0


def capture(name):
    window = app.window
    paintable = Gtk.WidgetPaintable.new(window)
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, window.get_width(), window.get_height())
    node = snapshot.to_node()
    if node is None:
        raise AssertionError("Window did not render")
    texture = window.get_renderer().render_texture(node, None)
    texture.save_to_png(str(screen_dir / f"{name}.png"))


def check():
    global step, original_backend
    window = app.window
    try:
        if step == 0:
            assert window.connected and len(window.data["users"]) == 1
            window.set_default_size(360, 720)
        elif step == 1:
            if not os.environ.get("PROTON_BRIDGE_GTK_PHONE_TEST"):
                assert window.get_width() <= 360, f"Phone layout forced width {window.get_width()}"
            else:
                assert window.get_width() <= 600, f"Unexpected phone layout width {window.get_width()}"
            capture("accounts")
            window.open_account("demo")
        elif step == 2:
            assert window.detail and window.detail.user.id == "demo"
            assert "demo-password" not in window.detail.password.get_subtitle()
            capture("account")
            window.detail.toggle_password()
            assert window.detail.password.get_subtitle().startswith("demo-password")
            window.nav.pop()
        elif step == 3:
            assert window.detail is None
            window.open_settings()
        elif step == 4:
            capture("settings")
            window.settings.smtp.set_value(window.settings.imap.get_value())
            window.settings.apply_servers()
            assert window.backend.servers.smtpPort == 1025, "Duplicate ports must not be submitted"
            window.settings.smtp.set_value(2025)
            window.settings.apply_servers()
        elif step == 5:
            assert window.backend.servers.smtpPort == 2025
            window.nav.pop()
        elif step == 6:
            window.open_login()
        elif step == 7:
            capture("login")
            window.login.username.set_text("test@proton.me")
            window.login.password.set_text("never-store-this")
            window.login.submit()
            assert window.login.password.get_text() == ""
        elif step == 8:
            assert window.login.submit_button.get_sensitive()
            window.event(pb.StreamEvent(login=pb.LoginEvent(tfaRequested=pb.LoginTfaRequestedEvent(username="test"))))
            assert window.login.stage == "Login2FA"
        elif step == 9:
            capture("two-factor")
            window.event(pb.StreamEvent(login=pb.LoginEvent(twoPasswordRequested=pb.LoginTwoPasswordsRequestedEvent(username="test"))))
            assert window.login.stage == "Login2Passwords"
            window.event(pb.StreamEvent(login=pb.LoginEvent(loginFidoPinRequired=pb.LoginFidoPinRequired(username="test"))))
            assert window.login.stage == "LoginFido"
            window.event(pb.StreamEvent(login=pb.LoginEvent(hvRequested=pb.LoginHvRequestedEvent(hvUrl="https://proton.me"))))
            assert window.login.use_hv and window.login.hv_button.get_visible()
            window.nav.pop()
        elif step == 10:
            assert window.login is None
            window.close()
            assert not window.get_visible()
            assert window.connected, "Closing the window must retain the backend"
            window.present()
            window.failed("Intentional test disconnect")
        elif step == 11:
            assert window.main_stack.get_visible_child_name() == "error"
            window.ready(window.backend.snapshot())
            window.open_settings()
            original_backend = window.backend
            window.settings.language.set_selected(4)  # French
        elif step == 12:
            assert window.settings.page.get_title() == "Param\u00e8tres"
            assert window.backend is original_backend, "Switching language must retain the running core"
            assert json.loads(app.preferences_path.read_text())["language"] == "fr"
            window.settings.language.set_selected(1)  # English
        elif step == 13:
            assert window.settings.page.get_title() == "Settings"
            assert json.loads(app.preferences_path.read_text())["language"] == "en"
            app.quit()
            return GLib.SOURCE_REMOVE
    except Exception as exc:
        import traceback
        traceback.print_exc()
        failures.append(str(exc))
        app.quit()
        return GLib.SOURCE_REMOVE
    step += 1
    return GLib.SOURCE_CONTINUE


GLib.timeout_add(500, check)
app.run([sys.argv[0]])
if failures:
    raise SystemExit(1)
print(f"Native UI smoke checks passed ({app.window.get_width()}px, accounts, settings, login, 2FA, mailbox password, FIDO, HV, background, disconnect).")
preferences_tmp.cleanup()
