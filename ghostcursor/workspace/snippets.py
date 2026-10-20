"""Named text snippets / quicklinks (D186), like Raycast snippets or Notebag
quicklinks: save a blob of text once, recall it by name onto the clipboard.

A single JSON file under the workspace root. Names are keys in a dict, never
file paths, so there's no traversal surface; a name is just trimmed and bounded.
Local only -- a snippet is never sent anywhere; recall puts it on the clipboard
for you to paste yourself (Orbyn never types it: rule 1).
"""

from __future__ import annotations

import json
from pathlib import Path

MAX_NAME = 60
MAX_TEXT = 10000


def _store(root: Path) -> Path:
    return Path(root) / "snippets.json"


def _load(root: Path) -> dict[str, str]:
    path = _store(root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _save(root: Path, data: dict[str, str]) -> None:
    _store(root).write_text(
        json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n"
    )


def save(root: Path, name: str, text: str) -> str:
    name = " ".join(name.split())[:MAX_NAME]
    text = text[:MAX_TEXT]
    if not name or not text.strip():
        raise ValueError("a snippet needs a name and some text")
    data = _load(root)
    data[name] = text
    _save(root, data)
    return name


def get(root: Path, name: str) -> str | None:
    return _load(root).get(" ".join(name.split())[:MAX_NAME])


def remove(root: Path, name: str) -> bool:
    data = _load(root)
    if data.pop(" ".join(name.split())[:MAX_NAME], None) is None:
        return False
    _save(root, data)
    return True


def names(root: Path) -> list[str]:
    return sorted(_load(root))


if __name__ == "__main__":  # ponytail: round-trip + bounds
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        assert names(r) == []
        assert save(r, "sig", "Best,\nArnav") == "sig"
        assert get(r, "sig") == "Best,\nArnav"
        assert names(r) == ["sig"]
        assert save(r, "x" * 100, "y")[:10] == "xxxxxxxxxx"  # name bounded
        try:
            save(r, "", "text")
            raise SystemExit("empty name must raise")
        except ValueError:
            pass
        assert remove(r, "sig") and not remove(r, "sig")
        assert get(r, "missing") is None
    print("snippets ok")
