import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk
from .i18n import _


def button(title, callback, css=None, icon=None):
    item = Gtk.Button(icon_name=icon) if icon else Gtk.Button(label=_(title))
    item.set_tooltip_text(_(title))
    if css:
        item.add_css_class(css)
    item.connect("clicked", lambda *_args: callback())
    return item


def row(title, subtitle=""):
    item = Adw.ActionRow(title=_(title), subtitle=_(subtitle))
    item.set_use_markup(False)
    item.set_title_lines(0)
    item.set_subtitle_lines(0)
    return item


def group(title, description=None):
    item = Adw.PreferencesGroup(title=_(title))
    if description:
        item.set_description(_(description))
    return item


def page(title, child, header_end=None):
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    if header_end:
        header.pack_end(header_end)
    toolbar.add_top_bar(header)
    toolbar.set_content(child)
    return Adw.NavigationPage.new(toolbar, _(title))


def preferences():
    return Adw.PreferencesPage()


def confirm(window, title, body, action, callback):
    dialog = Adw.MessageDialog.new(window, _(title), _(body))
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("confirm", _(action))
    dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")
    dialog.connect("response", lambda _d, response: callback() if response == "confirm" else None)
    dialog.present()
