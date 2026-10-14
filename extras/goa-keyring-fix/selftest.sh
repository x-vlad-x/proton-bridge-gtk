#!/usr/bin/env bash
# Run selftest.py on a private session bus that activates a mock goa-daemon.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/services" "$WORK/bin" "$WORK/state"
printf '[D-BUS Service]\nName=org.gnome.OnlineAccounts\nExec=%s %s/selftest.py goa\n' "$(command -v python3)" "$HERE" \
  > "$WORK/services/org.gnome.OnlineAccounts.service"
printf '#!/bin/sh\nexec %s %s/selftest.py geary-cli "$@"\n' "$(command -v python3)" "$HERE" > "$WORK/bin/geary"
printf '#!/bin/sh\necho true\n' > "$WORK/bin/gsettings"
chmod +x "$WORK/bin/geary" "$WORK/bin/gsettings"
cat > "$WORK/bus.conf" <<EOF
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>session</type>
  <listen>unix:tmpdir=$WORK</listen>
  <servicedir>$WORK/services</servicedir>
  <policy context="default"><allow send_destination="*" eavesdrop="true"/><allow eavesdrop="true"/><allow own="*"/></policy>
</busconfig>
EOF
SELFTEST_DIR="$WORK" XDG_STATE_HOME="$WORK/state" dbus-run-session --config-file="$WORK/bus.conf" -- python3 "$HERE/selftest.py"
