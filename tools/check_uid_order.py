"""Report whether IMAP UIDs in Bridge's Gluon databases grow with the message date.

Read-only: every database is opened with SQLite's mode=ro. Run it on the phone:
    python3 check_uid_order.py [GLUON_DB_DIR_OR_FILE ...]
The default is ~/.local/share/protonmail/bridge-v3/gluon/backend/db.
"""
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import sys
from urllib.parse import quote


def parse_date(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    text = str(value).strip()
    # Go's driver writes "2006-01-02 15:04:05.999999999-07:00"; Python accepts up to microseconds.
    if "." in text:
        head, _dot, rest = text.partition(".")
        digits = len(rest) - len(rest.lstrip("0123456789"))
        text = f"{head}.{rest[:min(digits, 6)]}{rest[digits:]}"
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def check(path):
    db = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True)
    total_inversions = 0
    try:
        mailboxes = db.execute("SELECT id, name FROM mailboxes_v2 ORDER BY name").fetchall()
        print(f"{path}")
        for mailbox_id, name in mailboxes:
            rows = db.execute(
                f"SELECT mm.uid, m.date FROM mailbox_message_{int(mailbox_id)} mm "
                "JOIN messages_v2 m ON m.id = mm.message_id ORDER BY mm.uid").fetchall()
            dates = [(uid, parse_date(date)) for uid, date in rows]
            inversions = [(a, b) for a, b in zip(dates, dates[1:]) if b[1] < a[1]]
            total_inversions += len(inversions)
            state = "ok" if not inversions else f"{len(inversions)} inversions"
            span = f"UID {dates[0][0]} {dates[0][1]:%Y-%m-%d} .. UID {dates[-1][0]} {dates[-1][1]:%Y-%m-%d}" if dates else "empty"
            print(f"  {name}: {len(dates)} messages, {state}; {span}")
            for (uid_a, date_a), (uid_b, date_b) in inversions[:3]:
                print(f"    UID {uid_a} {date_a:%Y-%m-%d %H:%M} > UID {uid_b} {date_b:%Y-%m-%d %H:%M}")
    finally:
        db.close()
    return total_inversions


def main(args):
    default = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "protonmail/bridge-v3/gluon/backend/db"
    targets = [Path(a) for a in args] or [default]
    files = []
    for target in targets:
        files += sorted(target.glob("*.db")) if target.is_dir() else [target]
    if not files:
        raise SystemExit(f"No Gluon databases found in {', '.join(map(str, targets))}")
    inversions = sum(check(path) for path in files)
    print("UIDs grow with the message date in every mailbox." if not inversions else
          f"{inversions} UID/date inversions found.")
    return 0 if not inversions else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
