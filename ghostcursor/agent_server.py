"""Read-only access to what Orbyn knows, for another agent on this computer.

A Model Context Protocol server over stdin/stdout (JSON-RPC 2.0, one message
per line): an agent the person already uses (a coding agent, a desktop
assistant) can ask the Company Brain a question and read the workflows the
person saved, instead of the person pasting them in. After YC's Summer 2026
requests "Company Brain" (know-how as something agents can use) and "Software
for Agents" (a machine-readable interface, not buttons).

    py -3.12 -m ghostcursor.agent_server [scope]

Rule 6. The other agent may send what it reads to a cloud model, so this is
egress: it answers only when the person switched "agent access" on AND the
organisation allows the ``agents`` service (so local-only blocks it); every
reply is scrubbed like text bound for a cloud model (private details and
private words) whenever hiding is on; sensitive facts are never returned;
each call leaves a content-free audit line. Read-only: there is no tool that
writes, plans, clicks or types.

ponytail: three tools and the four methods a client needs; no resources,
prompts, or streaming. Add them when a client asks for one.
"""

from __future__ import annotations

import json
import sys

from ghostcursor import audit, policy, redact, settings

PROTOCOL = "2024-11-05"
MAX_QUERY, MAX_REPLY = 500, 12_000

TOOLS = [
    {
        "name": "recall",
        "description": "Search the Company Brain on this computer: reviewed facts "
        "about how this person or company works, each with its source. Read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "maxLength": MAX_QUERY}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_workflows",
        "description": "Names of the step-by-step workflows this person saved in Orbyn.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_workflow",
        "description": "The ordered steps of one saved workflow, as instructions "
        "for a person. Read-only: this does not run it.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string", "maxLength": 120}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
]


def allowed() -> bool:
    return settings.agent_access() and policy.allows("agents")


def _outbound(text: str) -> str:
    """What may leave: scrubbed whenever hiding is on, and never long."""

    if policy.redact_egress() or settings.redact_egress():
        text = redact.scrub(text, terms=settings.private_terms())[0]
    else:  # keys and card numbers never ride along, hiding on or off
        text = redact.scrub(text, redact.SECRETS)[0]
    return text[:MAX_REPLY]


def call(name: str, args, scope: str, *, knowledge=None, skills_dir=None) -> str:
    """One tool call; raises ValueError for anything out of shape."""

    if not isinstance(args, dict):
        raise ValueError("arguments must be an object")
    if name == "recall":
        query = args.get("query")
        if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY:
            raise ValueError("query must be 1 to 500 characters")
        if knowledge is None:
            from ghostcursor.workspace.knowledge import Knowledge

            knowledge = Knowledge()
        facts = knowledge.recall(query, scope, k=8)  # never a sensitive fact
        return "\n".join(f"- {f.text} (source: {f.source})" for f in facts) or (
            "Nothing in the Company Brain matches."
        )
    from ghostcursor.workspace import task_skills

    if name == "list_workflows":
        return "\n".join(task_skills.list_skills(dest_dir=skills_dir)) or (
            "No saved workflows."
        )
    if name == "get_workflow":
        wanted = args.get("name")
        if not isinstance(wanted, str) or len(wanted) > 120:
            raise ValueError("name must be text")
        try:
            plan = task_skills.load_skill(wanted, dest_dir=skills_dir)
        except Exception as exc:  # a hand-edited file out of schema
            raise ValueError("that workflow could not be read") from exc
        if plan is None:
            raise ValueError("no workflow of that name")
        return "\n".join(
            f"{n}. {s.instruction}" for n, s in enumerate(plan.steps, start=1)
        )
    raise ValueError("unknown tool")


def handle(message, scope: str = "default", **stores) -> dict | None:
    """The reply to one JSON-RPC message, or None for a notification."""

    if not isinstance(message, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
    mid, method = message.get("id"), message.get("method")
    if mid is None:
        return None  # a notification: nothing to answer

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if method == "initialize":
        return ok(
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "orbyn", "version": "0.1.0"},
            }
        )
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params")
        params = params if isinstance(params, dict) else {}
        if not allowed():  # checked per call: a switch flipped mid-session applies
            text, failed = (
                "Orbyn agent access is off (Brain, Setup), or the organisation "
                "does not allow it. Nothing was shared.",
                True,
            )
        else:
            try:
                text = _outbound(
                    call(params.get("name"), params.get("arguments") or {}, scope, **stores)
                )
                failed = False
            except ValueError as exc:
                text, failed = str(exc), True
            audit.record(
                "egress",
                provider="agents",
                model=None,
                failure="refused" if failed else None,
                images=0,
            )
        return ok({"content": [{"type": "text", "text": text}], "isError": failed})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}


def main(argv=None, stdin=None, stdout=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    scope = argv[0] if argv else "default"
    for line in stdin:
        if not line.strip():
            continue
        try:
            reply = handle(json.loads(line), scope)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
    audit.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
