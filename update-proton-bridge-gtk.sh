#!/usr/bin/env bash
# Build Proton Mail Bridge's official core and a GTK4/libadwaita frontend for FLX1s.
# Usage: ./update-proton-bridge-gtk.sh [--build-only|--ui-only|--check|--uninstall]
#        [--tag v3.27.1] [--force]
# PHONE defaults to the SSH host "furios". Requires podman, git, ssh and tar.
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$TASK_ROOT/upstream"
# The core is built from a disposable copy of upstream/ with patches/*.patch applied.
CORE_SOURCE="$TASK_ROOT/out/core-src"
IMAGE="localhost/proton-bridge-gtk-cross"
APP_ID="io.github.x_vlad_x.ProtonBridgeGtk"
PHONE="${PHONE:-furios}"
REMOTE=".local/share/proton-bridge-gtk"
TAG="$(cat "$TASK_ROOT/upstream-version")"
BUILD_ONLY=0; UI_ONLY=0; CHECK=0; UNINSTALL=0; FORCE=0
while (($#)); do
  case "$1" in
    --build-only) BUILD_ONLY=1 ;;
    --ui-only) UI_ONLY=1 ;;
    --check) CHECK=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --force) FORCE=1 ;;
    --tag) [[ $# -ge 2 ]] || { echo '--tag requires a value' >&2; exit 2; }; TAG="$2"; shift ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Expected a vMAJOR.MINOR.PATCH release tag' >&2; exit 2; }
if ((BUILD_ONLY + CHECK + UNINSTALL > 1)); then echo 'Choose one of --build-only, --check, --uninstall' >&2; exit 2; fi
rsh() { ssh -o BatchMode=yes -o ConnectTimeout=10 "$PHONE" "$@"; }
PATCHES=()
for patch in "$TASK_ROOT"/patches/*.patch; do [[ -f "$patch" ]] && PATCHES+=("$patch"); done
patches_id() { (cd "$TASK_ROOT"; if ((${#PATCHES[@]})); then sha256sum "${PATCHES[@]#"$TASK_ROOT/"}"; fi); }
# Fail loudly when a patch no longer matches the upstream tree (e.g. after --tag).
check_patches() {
  local patch
  for patch in "${PATCHES[@]}"; do
    if ! git -C "$1" apply --check "$patch" 2>/dev/null; then
      echo "Core patch ${patch#"$TASK_ROOT/"} does not apply to upstream $TAG." >&2
      echo 'Rebase the patch onto this release (see README, "Core patch") before building.' >&2
      git -C "$1" apply --check "$patch" >&2 || true
      return 1
    fi
  done
}
in_container() {
  podman run --rm --userns=keep-id -v "$TASK_ROOT":/src:z \
    -v "$TASK_ROOT/.cache/go":/go:z -e GOPATH=/go -e GOCACHE=/go/build-cache -e XDG_CONFIG_HOME=/go/config -w /src "$IMAGE" "$@"
}
if ((UNINSTALL)); then
  # Data is deliberately retained. Never remove the shared upstream vault or mail.
  rsh 'pkill -TERM -f "[p]ython3 -m proton_bridge_gtk" || true'
  rsh "rm -rf $REMOTE; rm -f .local/share/applications/$APP_ID.desktop .local/share/icons/hicolor/scalable/apps/$APP_ID.svg"
  rsh 'python3 -' <<'PY'
from pathlib import Path
# Remove only an autostart entry belonging to this GTK installation.
for path in (Path.home() / '.config/autostart').glob('*.desktop'):
    if '.local/share/proton-bridge-gtk/proton-bridge-gtk' in path.read_text():
        path.unlink()
PY
  echo 'Uninstalled. Proton accounts, vault and mail cache are retained.'
  exit 0
fi
# Hash paths relative to the checkout, so cloning elsewhere gives the same revision.
ui_rev() { (cd "$TASK_ROOT"; find gtk-ui packaging build-env patches -type f ! -name '*.pyc' ! -path '*/__pycache__/*' -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-10); }
REV="$(ui_rev)"
FULL_VERSION="${TAG#v}+gtk.$REV"
DIST="$TASK_ROOT/out/proton-bridge-gtk-${TAG#v}"
if ((CHECK)); then
  INSTALLED="$(rsh "cat $REMOTE/VERSION 2>/dev/null" || true)"
  echo "Supported upstream: $TAG; local interface: $REV; installed: ${INSTALLED:-none}"
  if [[ -d "$SOURCE/.git" ]]; then
    check_patches "$SOURCE" || exit 1
    echo "Core patches: ${#PATCHES[@]} apply cleanly to upstream/ ($(git -C "$SOURCE" describe --tags --always 2>/dev/null))."
  else
    echo "Core patches: ${#PATCHES[@]}; upstream/ is not checked out, so they were not verified."
  fi
  if [[ "$INSTALLED" == "$FULL_VERSION" ]]; then echo 'Up to date.'; else echo 'An update from this checkout is available.'; fi
  echo 'New upstream tags are tested explicitly; use --tag to build another release.'
  exit 0
fi
mkdir -p "$TASK_ROOT/.cache/go" "$DIST/bin"
if ! podman image exists "$IMAGE"; then
  podman build -t "$IMAGE" -f "$TASK_ROOT/build-env/Containerfile" "$TASK_ROOT/build-env"
fi
if ((!UI_ONLY)); then
  if [[ ! -d "$SOURCE/.git" ]]; then
    git clone --depth 1 --branch "$TAG" https://github.com/ProtonMail/proton-bridge.git "$SOURCE"
  fi
  if [[ -n "$(git -C "$SOURCE" status --porcelain)" ]]; then
    echo 'upstream/ has local changes; commit or save them before building.' >&2; exit 1
  fi
  if [[ "$(git -C "$SOURCE" describe --tags --exact-match 2>/dev/null || true)" != "$TAG" ]]; then
    git -C "$SOURCE" fetch --depth 1 origin tag "$TAG"
    git -C "$SOURCE" checkout --detach "$TAG"
  fi
  CORE_REV="$(git -C "$SOURCE" rev-parse HEAD)"
  check_patches "$SOURCE"
  # FullAppName matches upstream's Makefile; it names the autostart entry
  # (~/.config/autostart/Proton Mail Bridge.desktop), which is empty without it.
  CONSTANTS=github.com/ProtonMail/proton-bridge/v3/internal/constants
  CORE_LDFLAGS="-s -w -X $CONSTANTS.Version=${TAG#v} -X $CONSTANTS.Revision=$CORE_REV -X $CONSTANTS.BuildEnv=dev -X '$CONSTANTS.FullAppName=Proton Mail Bridge'"
  if ((FORCE)) || [[ ! -f "$DIST/bin/bridge" || "$(cat "$DIST/CORE_REVISION" 2>/dev/null || true)" != "$CORE_REV" ]] ||
      [[ "$(cat "$DIST/CORE_PATCHES" 2>/dev/null || true)" != "$(patches_id)" ]] ||
      [[ "$(cat "$DIST/CORE_LDFLAGS" 2>/dev/null || true)" != "$CORE_LDFLAGS" ]]; then
    rm -rf "$CORE_SOURCE"
    git clone -q --no-checkout "$SOURCE" "$CORE_SOURCE"
    git -C "$CORE_SOURCE" checkout -q --detach "$CORE_REV"
    for patch in "${PATCHES[@]}"; do
      echo "Applying core patch ${patch#"$TASK_ROOT/"}…"
      git -C "$CORE_SOURCE" apply "$patch"
    done
    echo "Building official Bridge $TAG for arm64 (no Qt)…"
    in_container env GOOS=linux GOARCH=arm64 CGO_ENABLED=1 CC=aarch64-linux-gnu-gcc \
      PKG_CONFIG_LIBDIR=/usr/lib/aarch64-linux-gnu/pkgconfig:/usr/share/pkgconfig \
      CGO_LDFLAGS='-lfido2 -lcbor -lssl -lcrypto' \
      sh -c 'cd out/core-src && make gofiles && go build -p 6 -trimpath -ldflags "$1" -o "$2/bin/bridge.new" ./cmd/Desktop-Bridge' \
      build "$CORE_LDFLAGS" "/src/out/proton-bridge-gtk-${TAG#v}"
    mv "$DIST/bin/bridge.new" "$DIST/bin/bridge"
    echo "$CORE_REV" > "$DIST/CORE_REVISION"
    patches_id > "$DIST/CORE_PATCHES"
    echo "$CORE_LDFLAGS" > "$DIST/CORE_LDFLAGS"
  fi
else
  [[ -f "$DIST/bin/bridge" && -f "$DIST/CORE_REVISION" ]] || { echo 'Build the core once before using --ui-only.' >&2; exit 1; }
  [[ "$(cat "$DIST/CORE_PATCHES" 2>/dev/null || true)" == "$(patches_id)" ]] ||
    { echo 'The built core does not match patches/; rebuild it without --ui-only.' >&2; exit 1; }
fi
[[ "$(git -C "$SOURCE" describe --tags --exact-match 2>/dev/null)" == "$TAG" ]] || { echo 'Protocol source and core tag do not match.' >&2; exit 1; }
echo 'Generating Python bindings from the matching upstream protocol…'
in_container protoc -I /src/upstream/internal/frontend/grpc -I /usr/include \
  --python_out=/src/gtk-ui/proton_bridge_gtk /src/upstream/internal/frontend/grpc/bridge.proto
FULL_VERSION="${TAG#v}+gtk.$(ui_rev)"
rm -rf "$DIST/gtk-ui"
mkdir -p "$DIST/gtk-ui" "$DIST/packaging"
cp -r "$TASK_ROOT/gtk-ui/proton_bridge_gtk" "$DIST/gtk-ui/"
find "$DIST/gtk-ui" -type d -name __pycache__ -exec rm -rf {} +
cp "$TASK_ROOT/packaging/proton-bridge-gtk" "$DIST/"
cp "$TASK_ROOT/packaging/$APP_ID.desktop" "$TASK_ROOT/packaging/$APP_ID.svg" "$DIST/packaging/"
cp "$TASK_ROOT/LICENSE" "$TASK_ROOT/NOTICE" "$TASK_ROOT/README.md" "$DIST/"
cp "$SOURCE/LICENSE" "$DIST/LICENSE.upstream"
rm -rf "$DIST/patches"
if ((${#PATCHES[@]})); then mkdir -p "$DIST/patches"; cp "${PATCHES[@]}" "$DIST/patches/"; fi
echo "$TAG" > "$DIST/UPSTREAM_TAG"
echo "$FULL_VERSION" > "$DIST/VERSION"
echo "Built: $DIST"
if ((BUILD_ONLY)); then exit 0; fi
echo "Installing on $PHONE…"
rsh 'test "$(uname -m)" = aarch64; python3 -c '\''import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); from gi.repository import Gtk,Adw; assert (Gtk.get_major_version(),Gtk.get_minor_version()) >= (4,12); assert (Adw.get_major_version(),Adw.get_minor_version()) >= (1,5)'\'''
rsh "mkdir -p $REMOTE.new"
tar -C "$DIST" -cf - . | rsh "tar -C $REMOTE.new -xf -"
# Install Python's arm64 modules from the phone's own apt repository privately.
# This avoids requiring sudo or bundling a second GTK/Python runtime.
rsh "bash -s -- $REMOTE.new" <<'SH'
set -euo pipefail
target="$1"
export LC_ALL=C
task_tmp="$(mktemp -d)"
trap 'rm -rf "$task_tmp"' EXIT
mapfile -t grpc_libs < <(apt-cache depends python3-grpcio | sed -n 's/^ *Depends: \(lib[^ <>]*\)$/\1/p' | sed -n '/^libabsl/p; /^libcares/p; /^libc-ares/p')
(cd "$task_tmp" && apt-get download python3-grpcio python3-protobuf libre2-11 "${grpc_libs[@]}" >/dev/null)
mkdir -p "$target/runtime"
for package in "$task_tmp"/*.deb; do dpkg-deb -x "$package" "$target/runtime"; done
PYTHONPATH="$target/runtime/usr/lib/python3/dist-packages" LD_LIBRARY_PATH="$target/runtime/usr/lib/aarch64-linux-gnu" python3 -c 'import grpc, google.protobuf'
SH
# Stop only this frontend; the owned core flushes its vault on SIGTERM.
rsh 'pkill -TERM -f "[p]ython3 -m proton_bridge_gtk" || true'
rsh 'for i in $(seq 1 15); do pgrep -f "[p]ython3 -m proton_bridge_gtk" >/dev/null || exit 0; sleep 1; done; echo "Bridge is still stopping; installation left staged." >&2; exit 1'
rsh "set -e; rm -rf $REMOTE.old; if [ -d $REMOTE ]; then mv $REMOTE $REMOTE.old; fi; mv $REMOTE.new $REMOTE; rm -rf $REMOTE.old
  mkdir -p .local/share/applications .local/share/icons/hicolor/scalable/apps
  sed \"s|@HOME@|\$HOME|g\" $REMOTE/packaging/$APP_ID.desktop > .local/share/applications/$APP_ID.desktop
  cp $REMOTE/packaging/$APP_ID.svg .local/share/icons/hicolor/scalable/apps/
  chmod +x $REMOTE/proton-bridge-gtk
  update-desktop-database .local/share/applications 2>/dev/null || true"
rsh 'python3 -' <<'PY'
from pathlib import Path
# Cores built without FullAppName wrote a nameless ~/.config/autostart/.desktop.
# Rename ours to the path upstream now uses, so disabling autostart removes it.
autostart = Path.home() / '.config/autostart'
old, new = autostart / '.desktop', autostart / 'Proton Mail Bridge.desktop'
if old.is_file() and '.local/share/proton-bridge-gtk/proton-bridge-gtk' in old.read_text():
    if not new.exists():
        new.write_text(old.read_text().replace('\nName=\n', '\nName=Proton Mail Bridge\n'))
    old.unlink()
PY
rsh "$REMOTE/proton-bridge-gtk --help >/dev/null"
echo "Installed $FULL_VERSION. Open Proton Bridge (GTK) in the app list."
