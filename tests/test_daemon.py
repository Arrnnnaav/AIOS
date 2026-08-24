from dataclasses import dataclass

from ghostcursor.daemon import ForegroundIdentity, ForegroundWatcher
from ghostcursor.packs.registry import PackRegistry


@dataclass
class FakeForeground:
    value: ForegroundIdentity | None

    def __call__(self):
        return self.value


def test_watcher_logs_match_and_does_not_repeat_unchanged_identity():
    logs = []
    source = FakeForeground(ForegroundIdentity(1, "Code.exe", "project - Visual Studio Code"))
    watcher = ForegroundWatcher(PackRegistry(), foreground_source=source, log=logs.append)

    assert watcher.poll_once().pack_id == "vscode"
    assert watcher.poll_once().pack_id == "vscode"
    assert len(logs) == 1
    assert "pack activated 'vscode'" in logs[0]


def test_watcher_logs_actionable_truncated_pack_miss():
    logs = []
    title = "A" * 100
    source = FakeForeground(ForegroundIdentity(2, "unknown.exe", title))
    watcher = ForegroundWatcher(PackRegistry(), foreground_source=source, log=logs.append)

    assert watcher.poll_once() is None
    assert "pack miss" in logs[0]
    assert "unknown.exe" in logs[0]
    assert "A" * 60 in logs[0]
    assert "A" * 61 not in logs[0]
    assert "executable and title failed" in logs[0]


def test_watcher_logs_match_miss_reason_when_only_executable_matches():
    logs = []
    source = FakeForeground(ForegroundIdentity(3, "Code.exe", "Command Prompt"))
    watcher = ForegroundWatcher(PackRegistry(), foreground_source=source, log=logs.append)

    assert watcher.poll_once() is None
    assert "executable matched; title pattern failed" in logs[0]
