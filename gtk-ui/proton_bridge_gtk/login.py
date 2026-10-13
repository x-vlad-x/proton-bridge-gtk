from gi.repository import Adw, Gtk
from . import bridge_pb2 as pb
from .backend import login_request
from .i18n import _
from .widgets import button, group, page, preferences


ERRORS = (
    "Incorrect username or password.", "Bridge requires a paid Proton Mail plan.",
    "Could not connect to Proton. Try again.", "Incorrect authentication code.",
    "Sign-in was cancelled. Please start again.", "Incorrect mailbox password.",
    "Sign-in was cancelled. Please start again.", "Verification failed. Please start again.",
    "Incorrect security key PIN.", "Security key PIN is blocked.", "Security key authentication failed.",
)


class LoginPage:
    def __init__(self, window, username=""):
        self.window = window
        self.username_value = username
        self.stage = "Login"
        self.hv_url = None
        self.use_hv = False
        self.submitted = False
        self.closed = False
        self.content = preferences()
        fields = group("Sign in", "A paid Proton Mail plan is required.")
        self.username = Adw.EntryRow(title=_("Username or email"))
        self.username.set_text(username)
        fields.add(self.username)
        self.password = Adw.PasswordEntryRow(title=_("Password"))
        self.password.connect("entry-activated", lambda *_: self.submit())
        fields.add(self.password)
        self.content.add(fields)
        self.fields = fields
        self.message = Gtk.Label(wrap=True, xalign=0)
        self.message.add_css_class("error")
        error_group = group("")
        error_group.add(self.message)
        self.content.add(error_group)
        actions = group("")
        self.submit_button = button("Continue", self.submit, "suggested-action")
        self.submit_button.set_size_request(-1, 48)
        actions.add(self.submit_button)
        self.key_button = button("Use security key", lambda: self.set_stage("LoginFido"))
        self.key_button.set_visible(False)
        actions.add(self.key_button)
        self.hv_button = button("Open verification", lambda: self.window.open_uri(self.hv_url))
        self.hv_button.set_visible(False)
        actions.add(self.hv_button)
        self.spinner = Gtk.Spinner(margin_top=12)
        actions.add(self.spinner)
        self.content.add(actions)
        self.page = page("Sign in", self.content)
        self.page.connect("hidden", self.on_hidden)

    def on_hidden(self, *_):
        if self.closed:
            return
        self.closed = True
        self.password.set_text("")
        if self.submitted and self.window.connected:
            username = self.username_value
            def abort():
                self.window.backend.call("FidoAssertionAbort", pb.LoginAbortRequest(username=username))
                self.window.backend.call("LoginAbort", pb.LoginAbortRequest(username=username))
            self.window.backend.submit(abort)
        if self.window.login is self:
            self.window.login = None

    def busy(self, active):
        self.submit_button.set_sensitive(not active)
        self.password.set_sensitive(not active)
        self.username.set_sensitive(not active and self.stage == "Login")
        self.key_button.set_sensitive(not active)
        self.spinner.set_spinning(active)

    def submit(self):
        if self.closed or not self.submit_button.get_sensitive():
            return
        username = self.username.get_text().strip()
        password = self.password.get_text()
        if not username or (not password and self.stage != "LoginFido"):
            return
        self.username_value = username
        self.submitted = True
        request = login_request(username, password, useHvDetails=self.use_hv)
        self.password.set_text("")
        self.message.set_text("")
        self.busy(True)
        self.window.backend.submit(lambda: self.window.backend.call(self.stage, request), error=self.failed)

    def failed(self, message):
        if not self.closed:
            self.message.set_text(message)
            self.busy(False)

    def set_stage(self, stage):
        self.stage = stage
        titles = {"Login": ("Sign in", "Password", "A paid Proton Mail plan is required."),
                  "Login2FA": ("Two-factor authentication", "Authentication code", "Enter the code from your authenticator app."),
                  "Login2Passwords": ("Mailbox password", "Mailbox password", "Enter your separate mailbox password."),
                  "LoginFido": ("Security key", "Security key PIN", "Connect your USB security key and continue.")}
        title, prompt, hint = titles[stage]
        self.fields.set_title(_(title))
        self.fields.set_description(_(hint))
        self.password.set_title(_(prompt))
        self.password.set_text("")
        self.message.set_text("")
        self.key_button.set_visible(False)
        self.busy(False)
        self.password.grab_focus()

    def event(self, event):
        if self.closed:
            return
        name = event.WhichOneof("event")
        if name in ("finished", "alreadyLoggedIn"):
            self.submitted = False
            self.window.nav.pop()
            self.window.refresh()
        elif name == "error":
            code = event.error.type
            if code in (0, 1, 2, 4, 6, 7, 10):
                self.use_hv = False
                self.hv_button.set_visible(False)
                self.set_stage("Login")
            self.failed(_(ERRORS[code] if code < len(ERRORS) else ERRORS[0]))
        elif name in ("tfaRequested", "tfaOrFidoRequested"):
            self.set_stage("Login2FA")
            self.key_button.set_visible(name == "tfaOrFidoRequested")
        elif name == "twoPasswordRequested":
            self.set_stage("Login2Passwords")
        elif name in ("fidoRequested", "loginFidoPinRequired"):
            self.set_stage("LoginFido")
        elif name == "loginFidoTouchRequested":
            self.fields.set_description(_("Touch your security key…"))
        elif name == "hvRequested":
            self.hv_url = event.hvRequested.hvUrl
            self.use_hv = True
            self.set_stage("Login")
            self.fields.set_title(_("Human verification"))
            self.fields.set_description(_("Complete verification in your browser, then enter your password again and continue."))
            self.hv_button.set_visible(True)
