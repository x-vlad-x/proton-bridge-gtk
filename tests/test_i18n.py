import ast
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from proton_bridge_gtk import i18n


class TranslationTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("system")

    def test_complete_catalogs_and_ascii_storage(self):
        english = i18n.catalog("en")
        self.assertGreater(len(english), 120)
        for code, _label in i18n.LANGUAGES:
            if code == "system":
                continue
            with self.subTest(language=code):
                content = (i18n.CATALOG_DIR / f"{code}.json").read_bytes()
                self.assertTrue(content.isascii())
                data = json.loads(content)
                self.assertEqual(set(data), set(english))
                self.assertTrue(all(isinstance(value, str) and value for value in data.values()))
                i18n.set_language(code)
                self.assertEqual(i18n._("Settings"), data["Settings"])

    def test_literal_ui_strings_have_catalog_entries(self):
        english = i18n.catalog("en")
        root = i18n.CATALOG_DIR.parent
        functions = {"_": (0,), "button": (0,), "row": (0, 1), "group": (0, 1), "page": (0,), "confirm": (1, 2, 3)}
        for file in root.glob("*.py"):
            if file.name in ("i18n.py", "bridge_pb2.py"):
                continue
            for node in ast.walk(ast.parse(file.read_text())):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    for index in functions.get(node.func.id, ()):
                        if index < len(node.args) and isinstance(node.args[index], ast.Constant):
                            text = node.args[index].value
                            if isinstance(text, str) and any(char.isalpha() for char in text):
                                self.assertIn(text, english, f"{file.name}:{node.lineno}")

    def test_posix_bcp47_and_region_fallbacks(self):
        for locale, expected in (("de_DE.UTF-8", "de"), ("fr-CA", "fr"), ("pt_PT", "pt_BR"),
                                 ("ru_RU.UTF-8@variant", "ru"), ("C.UTF-8", "en"), ("xx_YY", "en")):
            self.assertEqual(i18n.resolve_language(locale), expected)

    def test_locale_precedence_and_language_list(self):
        with patch.dict(os.environ, {"LANG": "de_DE.UTF-8", "LC_ALL": "", "LC_MESSAGES": "fr_FR", "LANGUAGE": ""}):
            self.assertEqual(i18n.system_language(), "fr")
            os.environ["LC_ALL"] = "es_ES.UTF-8"
            self.assertEqual(i18n.system_language(), "es")
            os.environ["LANGUAGE"] = "xx:it:de"
            self.assertEqual(i18n.system_language(), "it")
            os.environ["LC_ALL"] = "C.UTF-8"
            self.assertEqual(i18n.system_language(), "en")

    def test_explicit_language_and_unknown_string_fallback(self):
        with patch.dict(os.environ, {"LC_ALL": "C.UTF-8"}):
            i18n.set_language("fr")
            self.assertEqual(i18n._("Settings"), "Param\u00e8tres")
            self.assertEqual(i18n._("untranslated diagnostic"), "untranslated diagnostic")
        with self.assertRaises(ValueError):
            i18n.set_language("../invalid")


if __name__ == "__main__":
    unittest.main()
