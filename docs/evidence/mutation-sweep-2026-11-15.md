# D018 mutation sweep, 15 Nov 2026

Captured output of the sweep script, unedited, in a code block.

```
D018 mutation sweep, tier-1 review fixes of 15 Nov 2026 (tree after 46dc0ef)
KILLED   ghostcursor/settings.py :: return True # there but unreadable -> return False # there but unreadable
KILLED   ghostcursor/policy.py :: return LOCAL if settings.local_only() else org_max_egress() -> return org_max_egress()
KILLED   ghostcursor/redact.py :: if slashes % 2 and found[0] in "nrt" and len(found) > 1: -> if False:
KILLED   ghostcursor/redact.py :: and chr(92) not in (term[0], term[-1]) -> (removed)
KILLED   ghostcursor/agent_server.py :: return redact.scrub(text, terms=settings.private_terms())[0][:MAX_REPL -> return redact.scrub(text, redact.SECRETS
KILLED   ghostcursor/agent_server.py :: except Exception: # a locked store -> except ZeroDivisionError: # a locked sto
KILLED   ghostcursor/providers/clients.py :: trust_env="//127.0.0.1" not in config.base_url and "//localhost" not i -> trust_env=True,
KILLED   ghostcursor/workspace/app.py :: (hide(name.replace("-", " ")), [hide(s.instruction) for s in plan.step -> (name.replace("-", " "), [hide(s.instruc
KILLED   ghostcursor/workspace/app.py :: "org_egress": policy.org_max_egress(), -> "org_egress": policy.max_egress(),
```
