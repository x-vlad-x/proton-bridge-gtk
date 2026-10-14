from pathlib import Path
from gi.repository import Adw, Gio, GLib, Gtk
from google.protobuf import wrappers_pb2
from . import APP_ID, VERSION, bridge_pb2 as pb
from .i18n import _
from .login import LoginPage
from .settings import SettingsPage
from .widgets import button, confirm, group, page, preferences, readable_bytes, row


class BridgeWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Proton Bridge", default_width=420, default_height=760)
        self.backend = app.backend
        self.connected = False
        self.internet = True
        self.data = None
        self.login = None
        self.detail = None
        self.sync = {}
        self.refresh_pending = False
        self.clipboard_secrets = {}
        self.connect("close-request", self.on_close)
        self.toasts = Adw.ToastOverlay()
        self.nav = Adw.NavigationView()
        self.nav.connect("popped", self.on_popped)
        self.toasts.set_child(self.nav)
        self.set_content(self.toasts)
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.header_title = Adw.WindowTitle(title="Proton Bridge", subtitle="GTK")
        header.set_title_widget(self.header_title)
        menu = Gio.Menu()
        for title, action in (("Add account", "add-account"), ("Settings", "settings"),
                              ("Support", "support"), ("About", "about"), ("Quit Bridge", "quit")):
            menu.append(_(title), f"app.{action}")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu))
        toolbar.add_top_bar(header)
        self.main_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        toolbar.set_content(self.main_stack)
        self.main_page = Adw.NavigationPage.new(toolbar, "Proton Bridge")
        self.nav.add(self.main_page)
        self.loading = Adw.StatusPage(title=_("Starting Bridge…"), icon_name="mail-send-receive-symbolic")
        spinner = Gtk.Spinner(spinning=True, height_request=32)
        self.loading.set_child(spinner)
        self.main_stack.add_named(self.loading, "loading")
        self.error_page = Adw.StatusPage(title=_("Bridge could not start"), icon_name="dialog-error-symbolic")
        self.error_page.set_child(button("Retry", app.retry, "suggested-action"))
        self.main_stack.add_named(self.error_page, "error")
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=560, tightening_threshold=400)
        self.home = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24,
                            margin_start=16, margin_end=16, margin_top=18, margin_bottom=24)
        clamp.set_child(self.home)
        scroll.set_child(clamp)
        self.main_stack.add_named(scroll, "home")
        status_group = group("")
        self.status = row("Bridge is running", "Mail keeps syncing when you close this window.")
        self.status_icon = Gtk.Image(icon_name="object-select-symbolic")
        self.status_icon.add_css_class("success")
        self.status.add_prefix(self.status_icon)
        status_group.add(self.status)
        self.home.append(status_group)
        self.accounts = group("Accounts")
        self.account_rows = []
        self.home.append(self.accounts)
        self.welcome = Adw.StatusPage(title=_("Proton Mail in your mail app"),
                                      description=_("Connect your Proton account, then use the IMAP and SMTP settings in your favourite mail app."),
                                      icon_name="mail-send-receive-symbolic")
        self.welcome.add_css_class("compact")
        self.home.append(self.welcome)
        self.add_button = button("Add account", lambda: self.open_login(), "suggested-action", "list-add-symbolic")
        # Keep a visible label as well as a touch-sized icon.
        self.add_button.set_child(Adw.ButtonContent(icon_name="list-add-symbolic", label=_("Add account")))
        self.add_button.set_size_request(-1, 48)
        self.home.append(self.add_button)
        self.requirement = Gtk.Label(label=_("A paid Proton Mail plan is required."), wrap=True)
        self.requirement.add_css_class("dim-label")
        self.home.append(self.requirement)
        self.settings = SettingsPage(self)
        self.main_stack.set_visible_child_name("loading")

    def on_close(self, *_):
        # The application holds a reference; hidden windows keep the RPC stream
        # and the mail servers alive. Explicit Quit releases it.
        if self.login:
            self.nav.pop_to_page(self.main_page)
        if self.detail:
            self.nav.pop_to_page(self.main_page)
        self.set_visible(False)
        return True

    def on_popped(self, _nav, popped):
        if self.login and popped == self.login.page:
            self.login.on_hidden()
        if self.detail and popped == self.detail.page:
            self.detail.hidden()

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast.new(text))

    def rpc(self, method, request=None, callback=None, error=None):
        if not self.connected:
            return
        self.backend.submit(lambda: self.backend.call(method, request), callback, error or self.toast)

    def ready(self, data):
        self.connected = True
        self.apply_snapshot(data)
        self.main_stack.set_visible_child_name("home")

    def failed(self, message):
        self.connected = False
        self.error_page.set_description(message)
        self.main_stack.set_visible_child_name("error")
        if self.login or self.detail:
            self.nav.pop_to_page(self.main_page)

    def refresh(self):
        if not self.connected or self.refresh_pending:
            return
        self.refresh_pending = True
        def done(data):
            self.refresh_pending = False
            self.apply_snapshot(data)
        def error(message):
            self.refresh_pending = False
            self.failed(message)
        self.backend.submit(self.backend.snapshot, done, error)

    def apply_snapshot(self, data):
        self.data = data
        for item in self.account_rows:
            self.accounts.remove(item)
        self.account_rows.clear()
        for user in data["users"]:
            item = row(user.addresses[0] if user.addresses else user.username, self.user_status(user))
            avatar = Adw.Avatar(size=40, text=user.username, show_initials=True)
            item.add_prefix(avatar)
            item.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            item.set_activatable(True)
            item.connect("activated", lambda _r, uid=user.id: self.open_account(uid))
            self.accounts.add(item)
            self.account_rows.append(item)
        self.accounts.set_visible(bool(data["users"]))
        self.welcome.set_visible(not data["users"])
        self.requirement.set_visible(not data["users"])
        self.settings.update(data)
        self.update_status()
        if self.detail:
            self.detail.update(data)

    def user_status(self, user):
        if user.id in self.sync:
            progress = self.sync[user.id]
            return _("Synchronising…") + (f" {progress:.0%}" if progress is not None else "")
        return _({pb.CONNECTED: "Connected", pb.SIGNED_OUT: "Signed out", pb.LOCKED: "Locked"}.get(user.state, "Locked"))

    def update_status(self):
        self.status.set_title(_("Bridge is running" if self.internet else "No internet connection"))
        self.status_icon.set_from_icon_name("object-select-symbolic" if self.internet else "network-offline-symbolic")

    def open_login(self, username=""):
        if not self.connected or self.login:
            return
        self.login = LoginPage(self, username)
        self.nav.push(self.login.page)

    def open_settings(self):
        if self.connected and self.nav.get_visible_page() != self.settings.page:
            if self.login or self.detail:
                self.nav.pop_to_page(self.main_page)
            self.nav.push(self.settings.page)

    def open_account(self, uid):
        if not self.connected or self.detail:
            return
        self.detail = AccountPage(self, uid)
        self.detail.update(self.data)
        self.nav.push(self.detail.page)

    def copy(self, text, secret=False):
        clipboard = self.get_clipboard()
        clipboard.set(text)
        self.toast(_("Copied"))
        if secret:
            # Clear only if it still contains this password, preserving anything
            # the user copied subsequently.
            def expire():
                def read(c, result):
                    try:
                        if c.read_text_finish(result) == text:
                            c.set("")
                    except GLib.Error:
                        pass
                clipboard.read_text_async(None, read)
                return GLib.SOURCE_REMOVE
            GLib.timeout_add_seconds(45, expire)

    def open_uri(self, uri):
        if not uri:
            return
        def done(launcher, result):
            try:
                launcher.launch_finish(result)
            except GLib.Error:
                pass
        Gtk.UriLauncher.new(uri).launch(self, None, done)

    def about(self):
        about = Adw.AboutWindow(transient_for=self, application_name="Proton Bridge (GTK)",
                                 application_icon=APP_ID, developer_name="Proton Bridge GTK contributors",
                                 version=VERSION, license_type=Gtk.License.GPL_3_0,
                                 comments=_("Unofficial GTK4 + libadwaita interface for Proton Mail Bridge."),
                                 website="https://github.com/ProtonMail/proton-bridge")
        about.add_credit_section("Proton Mail Bridge core", ["Proton AG https://proton.me"])
        about.present()

    def quit_bridge(self):
        confirm(self, "Quit Bridge?", "Your mail app cannot send or receive Proton mail while Bridge is stopped.", "Quit", self.get_application().quit)

    def event(self, event):
        kind = event.WhichOneof("event")
        value = getattr(event, kind) if kind else None
        name = value.WhichOneof("event") if value else None
        if kind == "login" and self.login:
            self.login.event(value)
        elif kind == "app":
            if name == "internetStatus":
                self.internet = value.internetStatus.connected
                self.update_status()
            elif name == "showMainWindow":
                self.present()
            elif name in ("allUsersLoaded", "toggleAutostartFinished"):
                if name == "allUsersLoaded":
                    self.get_application().users_loaded()
                self.refresh()
            elif name == "repairStarted":
                self.get_application().repair_started()
        elif kind == "user":
            if name == "syncStartedEvent":
                self.sync[value.syncStartedEvent.userID] = None
            elif name == "syncProgressEvent":
                self.sync[value.syncProgressEvent.userID] = value.syncProgressEvent.progress
            elif name == "syncFinishedEvent":
                self.sync.pop(value.syncFinishedEvent.userID, None)
            elif name == "userBadEvent":
                uid = value.userBadEvent.userID
                confirm(self, "Resynchronise account?", "Bridge reported a synchronisation error. Rebuilding the local cache may take a while.",
                        "Resynchronise", lambda: self.rpc("SendBadEventUserFeedback", pb.UserBadEventFeedbackRequest(userID=uid, doResync=True)))
            self.refresh()
        elif kind == "mailServerSettings":
            if name == "error":
                self.settings.server_error = True
                self.toast(_("Could not change mail server settings. Check whether the ports are already in use."))
            elif name == "changeMailServerSettingsFinished":
                self.settings.apply.set_sensitive(True)
                if self.settings.pending_apply and not self.settings.server_error:
                    self.toast(_("Server settings updated"))
                self.settings.pending_apply = False
                self.refresh()
            elif name == "mailServerSettingsChanged":
                self.refresh()
        elif kind == "keychain":
            if name in ("hasNoKeychain", "rebuildKeychain"):
                self.toast(_("Unlock GNOME Keyring (Secret Service), then restart Bridge."))
        elif kind == "mail":
            if name == "apiCertIssue":
                self.toast(_("Could not connect to Proton. Try again."))
            else:
                self.refresh()
        elif kind == "genericError":
            self.toast(_("Could not export TLS certificate or key."))
        elif kind == "update" and name == "force":
            self.toast(_("Updates are installed with update-proton-bridge-gtk.sh."))


class AccountPage:
    def __init__(self, window, uid):
        self.window = window
        self.uid = uid
        self.user = None
        self.loading = False
        self.content = preferences()
        self.account = group("Account")
        self.identity = row("")
        self.account.add(self.identity)
        self.storage = Gtk.ProgressBar(show_text=True, margin_top=12)
        self.account.add(self.storage)
        self.content.add(self.account)
        self.addresses = group("Addresses")
        self.address_rows = []
        self.content.add(self.addresses)
        self.credentials = group("Mail client settings", "Use this password in your mail app, not your Proton password.")
        self.password = row("Bridge password", "••••••••••••••••")
        self.visible_password = False
        self.reveal = button("Show password", self.toggle_password, icon="view-reveal-symbolic")
        self.password.add_suffix(self.reveal)
        self.password.add_suffix(button("Copy", self.copy_password, icon="edit-copy-symbolic"))
        self.credentials.add(self.password)
        self.address_choice = Adw.ComboRow(title=_("Address"))
        self.address_choice.set_use_markup(False)
        self.address_choice.connect("notify::selected", self.select_address)
        self.credentials.add(self.address_choice)
        self.content.add(self.credentials)
        self.server_groups = []
        self.server_rows = {}
        for protocol in ("IMAP", "SMTP"):
            server = group(protocol)
            for title in ("Host", "Port", "Security", "Username"):
                item = row(title)
                self.server_rows[(protocol, title)] = item
                if title != "Security":
                    item.add_suffix(button("Copy", lambda r=item: window.copy(r.get_subtitle()), icon="edit-copy-symbolic"))
                server.add(item)
            self.content.add(server)
            self.server_groups.append(server)
        certificate = group("Local certificate", "Your mail app may ask you to trust Bridge’s local TLS certificate.")
        self.content.add(certificate)
        self.certificate = certificate
        options = group("")
        self.split = Adw.SwitchRow(title=_("Split addresses"), subtitle=_("Configure each address as a separate mail account."))
        self.split.set_subtitle_lines(0)
        self.split.connect("notify::active", self.toggle_split)
        options.add(self.split)
        self.signin = button("Sign in", self.sign_in, "suggested-action")
        # Sign-in button is outside options so its visibility follows account state.
        self.content.add(options)
        self.actions = group("")
        self.actions.add(self.signin)
        self.logout = button("Sign out", self.sign_out)
        self.actions.add(self.logout)
        self.actions.add(button("Remove account", self.remove, "destructive-action"))
        self.content.add(self.actions)
        self.page = page("Account", self.content)
        self.page.connect("hidden", self.hidden)

    def hidden(self, *_):
        self.visible_password = False
        self.password.set_subtitle("••••••••••••••••")
        if self.user:
            self.user = None
        if self.window.detail is self:
            self.window.detail = None

    def update(self, data):
        user = next((u for u in data["users"] if u.id == self.uid), None)
        if user is None:
            self.window.nav.pop_to_page(self.window.main_page)
            return
        self.user = user
        active = user.state == pb.CONNECTED
        self.identity.set_title(user.username)
        self.identity.set_subtitle(self.window.user_status(user))
        self.storage.set_fraction(min(1, user.usedBytes / user.totalBytes) if user.totalBytes else 0)
        self.storage.set_text(f"{readable_bytes(user.usedBytes)} / {readable_bytes(user.totalBytes)}")
        for item in self.address_rows:
            self.addresses.remove(item)
        self.address_rows.clear()
        for address in user.addresses:
            item = row(address)
            item.add_suffix(button("Copy", lambda a=address: self.window.copy(a), icon="edit-copy-symbolic"))
            self.addresses.add(item)
            self.address_rows.append(item)
        self.loading = True
        self.split.set_active(user.splitMode)
        self.split.set_sensitive(active)
        self.loading = False
        self.credentials.set_visible(active)
        selected = self.address_choice.get_selected()
        self.address_choice.set_model(Gtk.StringList.new(list(user.addresses)))
        self.address_choice.set_selected(min(selected, max(0, len(user.addresses) - 1)))
        self.address_choice.set_visible(active and user.splitMode and len(user.addresses) > 1)
        self.certificate.set_visible(active)
        for server in self.server_groups:
            server.set_visible(active)
        self.logout.set_visible(active)
        self.signin.set_visible(not active)
        if not active:
            self.visible_password = False
        if not self.visible_password:
            self.password.set_subtitle("••••••••••••••••")
        servers = data["servers"]
        for protocol, port, ssl in (("IMAP", servers.imapPort, servers.useSSLForImap), ("SMTP", servers.smtpPort, servers.useSSLForSmtp)):
            self.server_rows[(protocol, "Host")].set_subtitle(data["hostname"])
            self.server_rows[(protocol, "Port")].set_subtitle(str(port))
            self.server_rows[(protocol, "Security")].set_subtitle("SSL/TLS" if ssl else "STARTTLS")
            self.server_rows[(protocol, "Username")].set_subtitle(user.addresses[0] if user.addresses else user.username)
        self.select_address()

    def select_address(self, *_):
        if not self.user or not self.user.splitMode:
            return
        selected = self.address_choice.get_selected()
        if selected < len(self.user.addresses):
            for protocol in ("IMAP", "SMTP"):
                self.server_rows[(protocol, "Username")].set_subtitle(self.user.addresses[selected])

    def sign_in(self):
        username = self.user.username
        self.window.nav.pop()
        self.window.open_login(username)

    def toggle_password(self):
        if not self.user:
            return
        self.visible_password = not self.visible_password
        self.password.set_subtitle(self.user.password.decode("utf-8") if self.visible_password else "••••••••••••••••")
        self.reveal.set_icon_name("view-conceal-symbolic" if self.visible_password else "view-reveal-symbolic")
        self.reveal.set_tooltip_text(_("Hide password" if self.visible_password else "Show password"))

    def copy_password(self):
        if self.user:
            self.window.copy(self.user.password.decode("utf-8"), secret=True)

    def toggle_split(self, item, _prop):
        if self.loading or not self.user:
            return
        desired = item.get_active()
        self.loading = True
        item.set_active(self.user.splitMode)
        self.loading = False
        confirm(self.window, "Split addresses?", "Changing address mode requires reconfiguring your mail app.", "Apply",
                lambda: self.window.rpc("SetUserSplitMode", pb.UserSplitModeRequest(userID=self.uid, active=desired)))

    def sign_out(self):
        confirm(self.window, "Sign out of this account?", "Mail will stop syncing until you sign in again.", "Sign out",
                lambda: self.window.rpc("LogoutUser", wrappers_pb2.StringValue(value=self.uid)))

    def remove(self):
        def remove():
            self.window.rpc("RemoveUser", wrappers_pb2.StringValue(value=self.uid))
            self.window.nav.pop()
        confirm(self.window, "Remove this account from Bridge?", "This removes its local cache and settings. Your mail stays on Proton.", "Remove account", remove)
