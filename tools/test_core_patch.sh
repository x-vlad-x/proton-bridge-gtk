#!/usr/bin/env bash
# Apply patches/*.patch to a fresh copy of upstream/ and run the patched package's Go tests.
# Tests are cross-compiled for arm64 (the core's cgo dependencies are arm64-only) and run with qemu.
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$TASK_ROOT/upstream"
TEST_SOURCE="$TASK_ROOT/out/core-test-src"
[[ -d "$SOURCE/.git" ]] || { echo 'upstream/ is missing; run update-proton-bridge-gtk.sh --build-only first.' >&2; exit 1; }
rm -rf "$TEST_SOURCE"
git clone -q --no-checkout "$SOURCE" "$TEST_SOURCE"
git -C "$TEST_SOURCE" checkout -q --detach "$(git -C "$SOURCE" rev-parse HEAD)"
for patch in "$TASK_ROOT"/patches/*.patch; do
  git -C "$TEST_SOURCE" apply "$patch"
done
mkdir -p "$TASK_ROOT/.cache/go"
podman run --rm --userns=keep-id -v "$TASK_ROOT":/src:z -v "$TASK_ROOT/.cache/go":/go:z \
  -e GOPATH=/go -e GOCACHE=/go/build-cache -e XDG_CONFIG_HOME=/go/config -w /src/out/core-test-src \
  -e GOOS=linux -e GOARCH=arm64 -e CGO_ENABLED=1 -e CC=aarch64-linux-gnu-gcc \
  -e PKG_CONFIG_LIBDIR=/usr/lib/aarch64-linux-gnu/pkgconfig:/usr/share/pkgconfig \
  -e CGO_LDFLAGS='-lfido2 -lcbor -lssl -lcrypto' localhost/proton-bridge-gtk-cross sh -ec '
    unformatted="$(gofmt -l internal/services/syncservice)"
    [ -z "$unformatted" ] || { echo "gofmt: $unformatted" >&2; exit 1; }
    go vet ./internal/services/syncservice/
    go test -c -o /src/out/core-test-src/syncservice.test ./internal/services/syncservice/
    qemu-aarch64 -L /usr/aarch64-linux-gnu ./syncservice.test -test.count=1 -test.v >syncservice-test.log 2>&1 ||
      { grep -E "^(--- FAIL|FAIL|panic)" -A20 syncservice-test.log >&2 || tail -n 80 syncservice-test.log >&2; exit 1; }
    go test -c -o imapservice.test ./internal/services/imapservice/
    qemu-aarch64 -L /usr/aarch64-linux-gnu ./imapservice.test -test.run TestDateOrdered -test.v
    echo "Patched syncservice tests passed: $(grep -c "^--- PASS" syncservice-test.log) top-level tests, $(grep -c "^--- PASS: TestOldestFirst" syncservice-test.log) for oldest-first sync."'
