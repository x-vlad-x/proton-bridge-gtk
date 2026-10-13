from pathlib import Path
from gi.repository import Adw, Gtk, GLib
from google.protobuf import wrappers_pb2
from . import bridge_pb2 as pb
from .i18n import LANGUAGES, _, get_language
from .widgets import button, group, page, preferences, row


class SettingsPage:
    def __init__(self, window):
        self.window = window
        self.loading = False
        self.last_state = None
        self.pending_apply = False
        self.server_error = False
        self.content = preferences()
        general = group("General")
        self.language = Adw.ComboRow(title=_("Language"), subtitle=_("Application language"),
                                     model=Gtk.StringList.new([_(label) for _code, label in LANGUAGES]))
        self.language.set_selected([code for code, _label in LANGUAGES].index(get_language()))
        self.language.connect("notify::selected", self.change_language)
        general.add(self.language)
        self.switches = {}
        for title, description, get, set_method, inverse in (
            ("Start at login", "Keep Bridge available for your mail app.", "IsAutostartOn", "SetIsAutostartOn", False),
            ("Show All Mail", "Include the All Mail folder in IMAP.", "IsAllMailVisible", "SetIsAllMailVisible", False),
            ("Alternative routing", "Use DNS over HTTPS to reach Proton when blocked.", "IsDoHEnabled", "SetIsDoHEnabled", False),
            ("Share usage statistics", "Controlled by the official Bridge core.", "IsTelemetryDisabled", "SetIsTelemetryDisabled", True),
        ):
            item = Adw.SwitchRow(title=_(title), subtitle=_(description))
            item.set_subtitle_lines(0)
            item.connect("notify::active", self.toggle, set_method, inverse)
            general.add(item)
            self.switches[get] = (item, inverse)
        self.content.add(general)
        servers = group("Local mail servers", "These settings apply to every account. Update your mail app after changing them.")
        self.imap = Adw.SpinRow(title=_("IMAP port"), adjustment=Gtk.Adjustment(lower=1024, upper=65535, step_increment=1, page_increment=100), digits=0)
        self.smtp = Adw.SpinRow(title=_("SMTP port"), adjustment=Gtk.Adjustment(lower=1024, upper=65535, step_increment=1, page_increment=100), digits=0)
        servers.add(self.imap)
        servers.add(self.smtp)
        self.imap_tls = Adw.ComboRow(title=_("IMAP security"), model=Gtk.StringList.new(["STARTTLS", "SSL/TLS"]))
        self.smtp_tls = Adw.ComboRow(title=_("SMTP security"), model=Gtk.StringList.new(["STARTTLS", "SSL/TLS"]))
        servers.add(self.imap_tls)
        servers.add(self.smtp_tls)
        self.apply = button("Apply server settings", self.apply_servers, "suggested-action")
        self.apply.set_margin_top(12)
        self.apply.set_size_request(-1, 44)
        servers.add(self.apply)
        self.content.add(servers)
        diagnostics = group("Diagnostics", "Updates are installed with update-proton-bridge-gtk.sh.")
        self.version = row("Core version")
        self.keyring = row("Keyring")
        diagnostics.add(self.version)
        diagnostics.add(self.keyring)
        logs = row("Open logs")
        logs.add_suffix(button("Open logs", self.open_logs, icon="folder-open-symbolic"))
        diagnostics.add(logs)
        export = row("Export TLS certificate", "Exports cert.pem and private key.pem into the selected folder.")
        export.add_suffix(button("Export TLS certificate", self.export_certificate, icon="document-save-symbolic"))
        diagnostics.add(export)
        self.content.add(diagnostics)
        self.page = page("Settings", self.content)

    def change_language(self, item, _prop):
        language = LANGUAGES[item.get_selected()][0]
        if language != get_language():
            self.window.get_application().change_language(language)

    def update(self, data):
        state = (data["servers"].SerializeToString(), data["version"], data["CurrentKeychain"],
                 *(data[key] for key in self.switches))
        if state == self.last_state:
            return
        self.last_state = state
        self.loading = True
        for key, (item, inverse) in self.switches.items():
            item.set_active(data[key] != inverse)
        servers = data["servers"]
        self.imap.set_value(servers.imapPort)
        self.smtp.set_value(servers.smtpPort)
        self.imap_tls.set_selected(int(servers.useSSLForImap))
        self.smtp_tls.set_selected(int(servers.useSSLForSmtp))
        self.version.set_subtitle(data["version"])
        self.keyring.set_subtitle(data["CurrentKeychain"] or "—")
        self.loading = False

    def toggle(self, item, _prop, method, inverse):
        if self.loading or not self.window.connected:
            return
        desired = item.get_active()
        item.set_sensitive(False)
        def finish(_result=None):
            item.set_sensitive(True)
            self.window.refresh()
        def failed(message):
            self.loading = True
            item.set_active(not desired)
            self.loading = False
            item.set_sensitive(True)
            self.window.toast(message)
        self.window.backend.submit(lambda: self.window.backend.call(method, wrappers_pb2.BoolValue(value=desired != inverse)), finish, failed)

    def apply_servers(self):
        imap, smtp = int(self.imap.get_value()), int(self.smtp.get_value())
        if imap == smtp or not all(1024 <= port <= 65535 for port in (imap, smtp)):
            self.window.toast(_("Ports must be different and between 1024 and 65535."))
            return
        request = pb.ImapSmtpSettings(imapPort=imap, smtpPort=smtp,
                                      useSSLForImap=bool(self.imap_tls.get_selected()),
                                      useSSLForSmtp=bool(self.smtp_tls.get_selected()))
        self.apply.set_sensitive(False)
        self.pending_apply = True
        self.server_error = False
        self.window.toast(_("Updating server settings…"))
        def failed(message):
            self.pending_apply = False
            self.apply.set_sensitive(True)
            self.window.toast(message)
        self.window.rpc("SetMailServerSettings", request, error=failed)

    def open_logs(self):
        self.window.rpc("LogsPath", callback=lambda result: self.window.open_uri(Path(result.value).as_uri()))

    def export_certificate(self):
        dialog = Gtk.FileDialog(title=_("Choose an empty, private folder for the certificate and key."))
        def selected(d, result):
            try:
                folder = d.select_folder_finish(result).get_path()
            except Exception:
                return
            if folder is None:
                return
            target = Path(folder)
            if any((target / name).exists() for name in ("cert.pem", "key.pem")):
                self.window.toast(_("This folder already contains cert.pem or key.pem. Choose an empty folder."))
                return
            self.window.rpc("ExportTLSCertificates", wrappers_pb2.StringValue(value=folder))
            self.window.toast(_("Exporting certificate…"))
            attempts = 0
            def check():
                nonlocal attempts
                attempts += 1
                if all((target / name).is_file() for name in ("cert.pem", "key.pem")):
                    self.window.toast(_("Certificate exported"))
                    return GLib.SOURCE_REMOVE
                return GLib.SOURCE_CONTINUE if attempts < 15 else GLib.SOURCE_REMOVE
            GLib.timeout_add_seconds(1, check)
        dialog.select_folder(self.window, None, selected)
