"""Launch the pilot manager for ONE counted manager-path attempt.

The 11 September campaign ran `act_acceptance`, which calls
`approve_action_graph`/`execute_approved_graph` directly and never mints an
`ActExecutionRequest`. Its own docstring says "This is not a production install
path." So the manager layer -- the one-use execution request (D121), the
foreground handoff and its four refusals (D123), and the UI-thread presentation
bridge (D124) -- has hermetic tests and killed mutations but no counted live
campaign (D137).

This harness does exactly one thing the other one cannot: it starts the real
manager and gets out of the way. Every approval is a human pressing
`Approve & run` in the native window. Nothing here proposes, authorizes,
approves, dispatches or verifies -- `act_audit_path` is the documented opt-in
observation sink, and `launch_manager` refuses to let it supply any of those.

Retained with the evidence per D121: live evidence must keep the harness, not
just the transcript.

    py -3.12 manager_campaign.py <attempt-number> <audit-directory>
"""

import os
import sys
from pathlib import Path

REPO = Path(r"D:\PROJECTS\AIOS")
sys.path.insert(0, str(REPO))


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    attempt = int(sys.argv[1])
    audit_root = Path(sys.argv[2]).resolve()
    audit_root.mkdir(parents=True, exist_ok=True)

    # One scope for the whole campaign, exported by the caller. A process that
    # inherits none derives its own, and three attempts would then carry three
    # scopes -- the hazard the seventh review found after it would have cost a
    # full campaign (D133).
    for name in ("GHOSTCURSOR_CAMPAIGN_SCOPE", "GHOSTCURSOR_CAMPAIGN_SALT"):
        if not os.environ.get(name):
            print(f"refusing: {name} is not set; export one scope for all attempts")
            return 2

    audit_path = audit_root / f"act-live-manager-campaign-attempt-{attempt}.jsonl"
    if audit_path.exists():
        print(f"refusing: {audit_path.name} already exists; never overwrite a run")
        return 2

    from ghostcursor.manager import launch_manager

    print(f"attempt {attempt}: audit -> {audit_path}")
    print("Goal:  build the ghostcursor investor deck in powerpoint")
    print("Mode:  Act.  Choose the PowerPoint window, then Approve & run.")
    return launch_manager(act_audit_path=audit_path)


if __name__ == "__main__":
    raise SystemExit(main())
