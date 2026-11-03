"""The owner sets Orbyn up once; staff use it (D187).

No server. The owner publishes a signed bundle -- approved Company Brain facts,
task skills and agents -- to a shared folder IT names (``TeamFolder`` policy:
a SharePoint/OneDrive-synced folder or a file share). Each staff PC loads it
only if it verifies against the owner's public key IT pinned
(``TeamOwnerKey``), and never an older bundle than the last one it loaded.

Roles come from the key, not from a setting a user could flip: whoever holds
the private key matching ``TeamOwnerKey`` is the owner; everyone else is
staff. What staff receive is guidance only -- facts are context, skills and
agents still run through the gated Teach/Act path (plan approval, observed
controls, deny list, ESC).

What the bundle never holds: sensitive facts, candidates, screen text, the
conversation, or anything from ``kb.sqlite``/``sessions.sqlite`` (rule 6).
Fact text is scrubbed of embedded secrets on export (``redact``).

    py -3.12 -m ghostcursor.workspace.team init       # owner: make the key
    py -3.12 -m ghostcursor.workspace.team publish    # owner
    py -3.12 -m ghostcursor.workspace.team sync       # staff
    py -3.12 -m ghostcursor.workspace.team report     # owner: every PC's shared audit
    py -3.12 -m ghostcursor.workspace.team status
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from ghostcursor import audit, policy, redact
from ghostcursor.providers import keys

TEAM_SCOPE = "team"
KEY_NAME = "team-owner"
BUNDLE, SIGNATURE = "team.json", "team.sig"
MAX_BUNDLE = 4 * 1024 * 1024
_DOMAIN = b"orbyn-team-bundle-v1\n"
SKILL_PREFIX = "team-"


class TeamError(ValueError):
    pass


def _canonical(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _public_b64(private: Ed25519PrivateKey) -> str:
    from cryptography.hazmat.primitives import serialization

    raw = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return base64.b64encode(raw).decode("ascii")


def _owner_private(key_lookup=keys.get_key) -> Ed25519PrivateKey | None:
    raw = key_lookup(KEY_NAME)
    if not raw:
        return None
    try:
        return Ed25519PrivateKey.from_private_bytes(base64.b64decode(raw))
    except ValueError:
        return None


def init_owner(*, key_lookup=keys.get_key, key_store=keys.set_key) -> str:
    """Make the owner key once (kept in Credential Manager); returns the public
    key for IT to set as ``TeamOwnerKey``. An existing key is kept."""

    private = _owner_private(key_lookup)
    if private is None:
        from cryptography.hazmat.primitives import serialization

        private = Ed25519PrivateKey.generate()
        raw = private.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        key_store(KEY_NAME, base64.b64encode(raw).decode("ascii"))
    return _public_b64(private)


def role(*, key_lookup=keys.get_key) -> str:
    """'solo' (no team policy), 'owner' (holds the pinned key) or 'staff'."""

    pinned = policy.team_owner_key()
    if policy.team_folder() is None or pinned is None:
        return "solo"
    private = _owner_private(key_lookup)
    return (
        "owner" if private is not None and _public_b64(private) == pinned else "staff"
    )


def _folder() -> Path:
    folder = policy.team_folder()
    if folder is None:
        raise TeamError("no team folder: IT sets the TeamFolder policy")
    return Path(folder) / "orbyn"


def build_bundle(
    knowledge, *, scope: str, skills: dict, agent_specs: list, sequence: int
) -> dict:
    brain = knowledge.export_scope(scope)  # usable, non-sensitive, scrubbed
    return {
        "version": 1,
        "sequence": sequence,
        "published_at": round(time.time(), 3),
        "facts": [f["text"] for f in brain["facts"]],
        "skills": skills,
        "agents": agent_specs,
    }


def sign(bundle: dict, private: Ed25519PrivateKey) -> tuple[bytes, bytes]:
    raw = _canonical(bundle)
    return raw, base64.b64encode(private.sign(_DOMAIN + raw))


def verify(raw: bytes, signature: bytes, public_b64: str) -> dict:
    """The bundle, only if the pinned owner key signed exactly these bytes."""

    if len(raw) > MAX_BUNDLE:
        raise TeamError("the team bundle is too large")
    try:
        public = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_b64))
        public.verify(base64.b64decode(signature.strip()), _DOMAIN + raw)
    except (ValueError, InvalidSignature) as exc:
        raise TeamError("the team bundle is not signed by your owner") from exc
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("version") != 1:
        raise TeamError("not an Orbyn team bundle")
    if not isinstance(value.get("sequence"), int) or isinstance(
        value["sequence"], bool
    ):
        raise TeamError("the team bundle has no sequence number")
    for key, kind in (("facts", list), ("skills", dict), ("agents", list)):
        if not isinstance(value.get(key), kind):
            raise TeamError(f"the team bundle's {key} are malformed")
    return value


def publish(
    knowledge, *, scope: str, skills_dir=None, agents_root=None, key_lookup=keys.get_key
) -> dict:
    """Owner only: sign this PC's approved facts, skills and agents into the
    team folder. Returns counts."""

    from ghostcursor.workspace import agents, task_skills

    if role(key_lookup=key_lookup) != "owner":
        raise TeamError("only the owner (the holder of TeamOwnerKey) can publish")
    private = _owner_private(key_lookup)
    folder = _folder()
    folder.mkdir(parents=True, exist_ok=True)
    previous = 0
    try:  # unverified: anyone with write access could have put it there
        previous = int(json.loads((folder / BUNDLE).read_bytes()).get("sequence", 0))
    except (OSError, ValueError, AttributeError, TypeError):
        previous = 0
    skills = {}
    for name in task_skills.list_skills(dest_dir=skills_dir):
        if name.startswith(SKILL_PREFIX):
            continue  # a skill this PC received is never re-published as its own
        plan = task_skills.load_skill(name, dest_dir=skills_dir)
        skills[name] = [
            {
                "instruction": redact.scrub(s.instruction)[0],
                "expected_change": s.expected_change.value,
                "action": s.action,
                "text": redact.scrub(s.text)[0],
            }
            for s in plan.steps
        ]
    specs = [
        {**d, "description": redact.scrub(d["description"])[0], "goal_template": redact.scrub(d["goal_template"])[0]}
        for d in (s.as_dict() for s in (agents.list_specs(agents_root) if agents_root else []))
    ]
    bundle = build_bundle(
        knowledge,
        scope=scope,
        skills=skills,
        agent_specs=specs,
        sequence=previous + 1,
    )
    raw, signature = sign(bundle, private)
    for name, data in ((BUNDLE, raw), (SIGNATURE, signature)):
        partial = folder / (name + ".partial")
        partial.write_bytes(data)
        os.replace(partial, folder / name)
    counts = {
        "facts": len(bundle["facts"]),
        "skills": len(skills),
        "agents": len(specs),
    }
    audit.record("team_publish", **counts)
    return counts


def _seen_path(knowledge) -> Path:
    return Path(knowledge.path).with_name("team-sequence.txt")


def sync(knowledge, *, skills_dir=None, agents_root=None) -> dict:
    """Staff (and the owner's other PCs): load the newest signed bundle. Team
    facts replace the ``team`` scope as approved facts; skills and agents are
    saved with a ``team-`` prefix. Refuses an unsigned, re-signed or older
    bundle. Returns counts."""

    from ghostcursor.providers.errors import ProviderError
    from ghostcursor.providers.schemas import parse_teach_plan
    from ghostcursor.workspace import agents, task_skills

    pinned = policy.team_owner_key()
    if pinned is None:
        raise TeamError("no owner key: IT sets the TeamOwnerKey policy")
    folder = _folder()
    try:
        raw, signature = (
            (folder / BUNDLE).read_bytes(),
            (folder / SIGNATURE).read_bytes(),
        )
    except OSError as exc:
        audit.record("team_sync", outcome="missing")
        raise TeamError("nothing published to the team folder yet") from exc
    try:
        bundle = verify(raw, signature, pinned)
    except TeamError:
        audit.record("team_sync", outcome="refused")
        raise
    seen_path = _seen_path(knowledge)
    try:
        seen = int(seen_path.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        seen = 0
    if bundle["sequence"] < seen:
        audit.record("team_sync", outcome="rollback")
        raise TeamError("the team folder holds an older bundle than this PC loaded")

    wanted = [
        " ".join(str(t).split())
        for t in bundle["facts"]
        if isinstance(t, str) and t.strip()
    ]
    kept = set()
    for _action, fid in knowledge.ingest(wanted, source="team: owner", scope=TEAM_SCOPE):
        fact = knowledge.get(fid) if fid else None
        if fact is None or fact.status == "superseded":
            continue
        kept.add(fid)
        if fact.status != "approved":
            knowledge.approve(fid)  # the owner already approved it
    for fact in knowledge.list(scope=TEAM_SCOPE):
        if fact.fid not in kept and fact.status not in ("retired", "superseded"):
            knowledge.retire(fact.fid)  # gone from the bundle, or added locally

    skills = 0
    for name, steps in bundle["skills"].items():
        try:
            plan = parse_teach_plan(json.dumps({"steps": steps}))  # closed schema
            task_skills.save_skill(SKILL_PREFIX + str(name), plan, dest_dir=skills_dir)
            skills += 1
        except (ProviderError, ValueError):
            continue
    count = 0
    if agents_root is not None:
        for value in bundle["agents"]:
            try:
                spec = agents.parse_agent(json.dumps(value))
                spec = agents.AgentSpec(
                    **{
                        **spec.as_dict(),
                        "name": SKILL_PREFIX + spec.name,
                        "apps": tuple(spec.apps),
                        "skills": tuple(spec.skills),
                        "deny": tuple(spec.deny),
                    }
                )
                agents.save(agents_root, spec)
                count += 1
            except (ProviderError, ValueError, TypeError):
                continue
    seen_path.parent.mkdir(parents=True, exist_ok=True)
    seen_path.write_text(str(bundle["sequence"]), encoding="utf-8")
    counts = {"facts": len(kept), "skills": skills, "agents": count}
    audit.record("team_sync", outcome="loaded", **counts)
    return counts


def share_audit(source: Path | None = None) -> Path | None:
    """With ``ShareAudit`` on, copy this PC's audit log into the team folder
    under an opaque per-PC name. Off by default; returns the copy or None."""

    import hashlib
    import platform

    if not policy.share_audit():
        return None
    folder = _folder() / "audit"
    name = hashlib.sha256(
        f"{platform.node()}|{os.environ.get('USERNAME', '')}".encode()
    ).hexdigest()[:16]
    dest = folder / f"{name}.jsonl"
    audit.export(dest, source)
    return dest


def report(folder: Path | None = None) -> list[dict]:
    """The owner's view of every shared audit log: per PC, whether its chain
    is intact, who used it, when it was last active, and counts of approvals,
    steps done/refused/failed and model requests. Events only, as recorded."""

    folder = folder or _folder() / "audit"
    rows = []
    for path in sorted(folder.glob("*.jsonl")):
        intact, lines, broken = audit.verify(path)
        row = {"pc": path.stem, "intact": intact, "broken_at": broken, "events": lines,
               "users": set(), "last": None, "approvals": 0, "done": 0,
               "refused": 0, "failed": 0, "requests": 0}  # fmt: skip
        for raw in path.read_bytes().splitlines():
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue  # a corrupt line: verify already flagged the chain
            row["users"].add(str(entry.get("user", "")))
            at = entry.get("at")
            if isinstance(at, (int, float)) and not isinstance(at, bool):
                row["last"] = max(row["last"] or 0, at)
            event, outcome = entry.get("event"), entry.get("outcome")
            row["approvals"] += event in ("plan_approved", "drive_approved")
            row["requests"] += event == "egress"
            if event == "act_step" and outcome in ("done", "refused", "failed"):
                row[outcome] += 1
        row["users"] = sorted(u for u in row["users"] if u)
        rows.append(row)
    return rows


def main(argv=None) -> int:
    from ghostcursor.workspace.knowledge import Knowledge
    from ghostcursor.workspace.session import default_root

    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "status"
    try:
        if command == "init":
            print("Owner key ready. Ask IT to set the TeamOwnerKey policy to:")
            print(init_owner())
            return 0
        if command == "report":
            for r in report():
                when = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["last"])) if r["last"] else "-"
                chain = "intact" if r["intact"] else f"BROKEN at line {r['broken_at']}"
                print(f"{r['pc']}  {', '.join(r['users']) or '-'}  last {when}  chain {chain}  "
                      f"approvals {r['approvals']}  steps {r['done']} done / {r['refused']} refused / "
                      f"{r['failed']} failed  model requests {r['requests']}")
            return 0
        if command == "status":
            print(
                f"role: {role()}; team folder: {'set' if policy.team_folder() else 'not set'}"
            )
            return 0
        knowledge = Knowledge()
        if command == "publish":
            scope = argv[1] if len(argv) > 1 else "default"
            print(
                f"published: {publish(knowledge, scope=scope, agents_root=default_root())}"
            )
            share_audit()
            return 0
        if command == "sync":
            print(f"loaded: {sync(knowledge, agents_root=default_root())}")
            share_audit()
            return 0
    except TeamError as exc:
        print(f"team: {exc}")
        return 1
    print(
        "usage: python -m ghostcursor.workspace.team init | status | publish [scope] | sync | report"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
