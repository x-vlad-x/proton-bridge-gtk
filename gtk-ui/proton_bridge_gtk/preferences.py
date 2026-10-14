"""Frontend preferences in ~/.config/proton-bridge-gtk; never the upstream vault."""
import json
import os
from pathlib import Path


def default_path():
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "proton-bridge-gtk/preferences.json"


def load(path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(path, **changes):
    """Merge changes into the stored preferences and replace the file atomically."""
    path = Path(path)
    data = {**load(path), **changes}
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=True) + "\n")
    temp.replace(path)
    return data
