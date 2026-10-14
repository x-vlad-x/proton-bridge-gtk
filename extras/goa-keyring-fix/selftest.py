#!/usr/bin/python3
"""Exercise goa-keyring-fix against mock GOA, Secret Service and Geary services.

Run inside a private session bus whose service directory activates this file
as org.gnome.OnlineAccounts (see selftest.sh). Roles are chosen by argv[1].
"""
import os
import subprocess
import sys
import time

from gi.repository import Gio, GLib

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ["SELFTEST_DIR"]
ACCOUNT = "/org/gnome/OnlineAccounts/Accounts/account_1"
XML = """<node>
<interface name="org.freedesktop.DBus.ObjectManager">
  <method name="GetManagedObjects"><arg type="a{oa{sa{sv}}}" direction="out"/></method>
</interface>
<interface name="org.gnome.OnlineAccounts.Account">
  <method name="EnsureCredentials"><arg type="i" direction="out"/></method>
</interface>
<interface name="org.freedesktop.DBus.Properties">
  <method name="Get"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method>
</interface>
</node>"""
NODE = Gio.DBusNodeInfo.new_for_xml(XML)


def serve(name, objects):
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    for path, iface, handler in objects:
        def method_call(conn, sender, path, iface, method, params, invocation, handler=handler):
            handler(method, params, invocation)
        bus.register_object(path, NODE.lookup_interface(iface), method_call, None, None)
    Gio.bus_own_name_on_connection(bus, name, Gio.BusNameOwnerFlags.NONE, None, None)
    GLib.MainLoop().run()


def goa():
    # The first instance hangs like goa-daemon waiting for a dismissed prompt.
    hang_marker = os.path.join(WORK, "hang-once")
    hang = os.path.exists(hang_marker)
    if hang:
        os.remove(hang_marker)
    open(os.path.join(WORK, "goa-started"), "a").write(f"{os.getpid()} hang={hang}\n")

    def manager(method, params, invocation):
        account = {"org.gnome.OnlineAccounts.Account": {"Identity": GLib.Variant("s", "user@gmail.com"),
                                                        "MailDisabled": GLib.Variant("b", False)},
                   "org.gnome.OnlineAccounts.Mail": {}}
        invocation.return_value(GLib.Variant("(a{oa{sa{sv}}})", ({ACCOUNT: account},)))

    def ensure(method, params, invocation):
        if not hang:
            invocation.return_value(GLib.Variant("(i)", (3600,)))
        else:
            ensure.pending.append(invocation)  # Never answered.
    ensure.pending = []
    serve("org.gnome.OnlineAccounts", [
        ("/org/gnome/OnlineAccounts", "org.freedesktop.DBus.ObjectManager", manager),
        (ACCOUNT, "org.gnome.OnlineAccounts.Account", ensure)])


def secrets():
    unlock_at = time.monotonic() + float(os.environ.get("UNLOCK_AFTER", "2"))

    def get(method, params, invocation):
        locked = time.monotonic() < unlock_at
        invocation.return_value(GLib.Variant("(v)", (GLib.Variant("b", locked),)))
    serve("org.freedesktop.secrets", [
        ("/org/freedesktop/secrets/collection/login", "org.freedesktop.DBus.Properties", get)])


def geary():
    open(os.path.join(WORK, "geary-started"), "a").write(f"{os.getpid()} {time.time()}\n")
    serve("org.gnome.Geary", [])


def fake_geary_cli():
    if "--quit" in sys.argv:
        pid = int(open(os.path.join(WORK, "geary-started")).read().splitlines()[-1].split()[0])
        os.kill(pid, 15)
    else:
        subprocess.Popen([sys.executable, __file__, "geary"], start_new_session=True)


def run_case(hang, geary_running):
    for marker in ("goa-started", "geary-started"):
        try:
            os.remove(os.path.join(WORK, marker))
        except FileNotFoundError:
            pass
    if hang:
        open(os.path.join(WORK, "hang-once"), "w").close()
    autostart = os.path.join(WORK, "config", "autostart", "geary-autostart.desktop")
    os.makedirs(os.path.dirname(autostart), exist_ok=True)
    with open(autostart, "w") as f:
        f.write("[Desktop Entry]\nName=Geary\nExec=geary --gapplication-service\n")
    unlocked_at = time.time() + 2
    roles = ("secrets", "geary") if geary_running else ("secrets",)
    procs = [subprocess.Popen([sys.executable, __file__, role], env=dict(os.environ, UNLOCK_AFTER="2"))
             for role in roles]
    # Activate goa through the bus, as at login.
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    bus.call_sync("org.gnome.OnlineAccounts", "/org/gnome/OnlineAccounts", "org.freedesktop.DBus.ObjectManager",
                  "GetManagedObjects", None, None, Gio.DBusCallFlags.NONE, 5000, None)
    time.sleep(0.5)
    env = dict(os.environ, GOA_FIX_SETTLE="0.5", GOA_FIX_CHECK_TIMEOUT_MS="2000", GOA_FIX_UNLOCK_WAIT="30",
               XDG_CONFIG_HOME=os.path.join(WORK, "config"),
               PATH=os.path.join(WORK, "bin") + os.pathsep + os.environ["PATH"])
    result = subprocess.run([sys.executable, os.path.join(HERE, "goa-keyring-fix")], env=env, timeout=90)
    time.sleep(1)
    goa_starts = open(os.path.join(WORK, "goa-started")).read().splitlines()
    geary_starts = open(os.path.join(WORK, "geary-started")).read().splitlines()
    log = open(os.path.join(WORK, "state", "goa-keyring-fix.log")).read()
    entry = open(autostart).read()
    for p in procs:
        p.terminate()
    subprocess.run(["pkill", "-f", __file__ + " (goa|geary)"], check=False)
    assert result.returncode == 0, log
    assert entry.startswith("[Desktop Entry]\nHidden=true\nName=Geary\n"), entry
    if hang or not geary_running:
        assert float(geary_starts[-1].split()[1]) >= unlocked_at, "Geary must start after the keyring is unlocked"
    if hang:
        assert len(goa_starts) == 2 and goa_starts[1].endswith("hang=False"), goa_starts
        assert "EnsureCredentials hangs" in log and "credentials respond" in log, log
    else:
        assert len(goa_starts) == 1, goa_starts
        assert "GOA credentials respond" in log, log
    if geary_running:
        assert len(geary_starts) == (2 if hang else 1), geary_starts
    else:
        assert len(geary_starts) == 1 and "started Geary" in log, (geary_starts, log)
    print(f"{'hung' if hang else 'healthy'} goa-daemon, Geary {'running' if geary_running else 'not running'}: ok")
    os.remove(os.path.join(WORK, "state", "goa-keyring-fix.log"))


if __name__ == "__main__":
    role = sys.argv[1] if len(sys.argv) > 1 else "test"
    if role == "test":
        for hang in (False, True):
            for geary_running in (True, False):
                run_case(hang, geary_running)
    elif role == "geary-cli":
        fake_geary_cli()
    else:
        {"goa": goa, "secrets": secrets, "geary": geary}[role]()
