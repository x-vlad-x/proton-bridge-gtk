# Verification record

Verified on 2026-10-13 with upstream `v3.27.1`, commit
`43b9237786204a0215abfd4dcc51ee7bb92f52d4`.

## Automated checks

`tools/test.sh` passes against the Debian 13 build container:

- Correctly pinned TLS certificate and successful private-file token challenge.
- Rejection of an incorrect server token and of an untrusted TLS certificate.
- Unicode password encoding in upstream's base64 bytes field.
- Sanitisation of RPC errors so remote details are not written to logs/UI.
- Real GTK widget navigation at 360px width, hidden/revealed account password,
  duplicate-port rejection and successful settings event handling.
- Login transitions for TOTP, mailbox password, FIDO PIN and human verification.
- Closing the window preserves the backend; transport failure shows a retry page.
- Every supported language has a complete ASCII-encoded translation catalog.
- Locale precedence, regional fallback, unsupported-locale fallback and an
  explicit application language are verified.
- All seven languages render at 360px. Changing the language in Settings saves
  the preference and preserves the existing core connection.

`update-proton-bridge-gtk.sh --build-only` completes, its output is a stripped
arm64 ELF, and the source checkout remains clean. Shell scripts pass `bash -n`.

## FLX1s

Installed using the same SSH update script that is included in the repository.
The device runs FuriOS 14, Python 3.13, libadwaita 1.9 and glibc 2.42.
Its application window is 413 × 871 logical pixels.

`tools/phone_smoke.py` passes with the actual bundled Go core and the phone's
unlocked Secret Service keyring. It verifies core version, real authenticated
RPC, settings/login navigation, the `Proton Mail Bridge.desktop` autostart
entry with the GTK launcher and `--no-window`,
and a responsive live core after closing the window. The autostart preference
is restored to its original value after this check.

The UI smoke flow also passes on the actual phone in explicit offline demo mode.
All screenshots in `docs/screenshots/` are in English and use the offline demo,
captured on that device with `tools/screenshots.py`. Screenshot
capture uses `GSK_RENDERER=cairo` to avoid a GDK dmabuf texture-builder warning
in the phone's GPU snapshot path; the normal launcher uses GTK's default renderer.

## Remaining manual account checks

No real account credentials were provided. Actual paid-account sign-in,
IMAP sync, SMTP send, hardware FIDO interaction and Proton human-verification
completion still need end-to-end verification. The login state machine is
covered by injected protocol events, not by a live Proton login.

GitHub Actions is configured; it has not run on GitHub because this repository
has not been published.
