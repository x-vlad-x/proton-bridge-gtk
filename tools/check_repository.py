"""Verify that repository text and all historical commit messages use no Cyrillic.

Application translation catalogs use ASCII JSON escapes. Published screenshots
must also be regenerated with tools/screenshots.py and visually reviewed.
"""
import re
import subprocess


def git(*args):
    return subprocess.check_output(["git", *args])


cyrillic = re.compile("[\u0400-\u04ff]")
objects = {}
for line in git("rev-list", "--objects", "--all").decode().splitlines():
    oid, _separator, name = line.partition(" ")
    objects[oid] = name
failures = []
for oid, name in objects.items():
    kind = git("cat-file", "-t", oid).decode().strip()
    if kind not in ("blob", "commit"):
        continue
    data = git("cat-file", kind, oid)
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        continue
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        continue
    if cyrillic.search(text):
        failures.append(f"{kind} {oid} {name}")
if failures:
    raise SystemExit("Cyrillic found in repository history:\n" + "\n".join(failures))
print(f"Repository history check passed ({len(objects)} objects; no literal Cyrillic).")
