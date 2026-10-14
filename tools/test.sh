#!/usr/bin/env bash
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TASK_ROOT"
podman run --rm --userns=keep-id -v "$TASK_ROOT":/src:z -w /src -e PYTHONPATH=/src/gtk-ui \
  -e LC_ALL=C.UTF-8 -e LANGUAGE=en localhost/proton-bridge-gtk-cross python3 -m unittest discover -s tests -p 'test_*.py' -v
podman run --rm --userns=keep-id -v "$TASK_ROOT":/src:z -w /src -e PYTHONPATH=/src/gtk-ui -e G_DEBUG=fatal-criticals -e GTK_A11Y=none \
  -e LC_ALL=C.UTF-8 -e LANGUAGE=en localhost/proton-bridge-gtk-cross dbus-run-session -- xvfb-run -a python3 tests/ui_smoke.py
podman run --rm --userns=keep-id -v "$TASK_ROOT":/src:z -w /src -e PYTHONPATH=/src/gtk-ui -e G_DEBUG=fatal-criticals -e GTK_A11Y=none \
  -e LC_ALL=C.UTF-8 -e LANGUAGE=en localhost/proton-bridge-gtk-cross dbus-run-session -- xvfb-run -a python3 tests/ui_languages.py
if [[ -d upstream/.git ]]; then
  ./tools/test_core_patch.sh
else
  echo 'upstream/ is not checked out; skipped the core patch tests.'
fi
