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

## Second sweep: re-review fixes, keep-secrets switch, key pattern

First run, as printed (one survivor: no test put a word starting with f
right after a form-feed escape):

```
D018 mutation sweep, tier-1 re-review fixes of 15 Nov 2026 (tree after d0e39dd)
KILLED   ghostcursor/redact.py :: "(?:[\s_-]| -> "(?:[\s]|
KILLED   ghostcursor/redact.py :: [nrtfb]))(?:" -> [nrt]))(?:"
SURVIVED ghostcursor/redact.py :: found[0].lower() in "nrtfb" -> found[0].lower() in "nrt"
KILLED   ghostcursor/redact.py :: \b(?:(?:sk|pk|rk)[-_]|gh[pousr]_|github_pat_|xox[baprs]-) -> \b(?:sk|pk|rk|gho|ghp|github_pat_|xox[ba
KILLED   ghostcursor/redact.py :: |\bAKIA[0-9A-Z]{16}\b -> |\bAKIA[0-9A-Za-z ]{16}
KILLED   ghostcursor/providers/clients.py :: return ipaddress.ip_address(host).is_loopback -> return host.startswith("127.")
KILLED   ghostcursor/providers/clients.py :: trust_env=not is_loopback(config.base_url), -> trust_env=True,
KILLED   ghostcursor/inference/ollama.py :: if is_loopback(endpoint) -> if False
KILLED   ghostcursor/providers/gateway.py :: if keep and placeholder[1:].rsplit("_", 1)[0] in redact.SECR -> if False:
KILLED   ghostcursor/workspace/app.py :: settings.set_keep_secrets_hidden(body.get("on") is True) -> settings.set_keep_secrets_hidden(bool(bo
```

After adding that case to `tests/test_workspace_redact.py`, as printed:

```
D018 mutation sweep, tier-1 re-review fixes of 15 Nov 2026 (tree after d0e39dd)
KILLED   ghostcursor/redact.py :: "(?:[\s_-]| -> "(?:[\s]|
KILLED   ghostcursor/redact.py :: [nrtfb]))(?:" -> [nrt]))(?:"
KILLED   ghostcursor/redact.py :: found[0].lower() in "nrtfb" -> found[0].lower() in "nrt"
KILLED   ghostcursor/redact.py :: \b(?:(?:sk|pk|rk)[-_]|gh[pousr]_|github_pat_|xox[baprs]-) -> \b(?:sk|pk|rk|gho|ghp|github_pat_|xox[ba
KILLED   ghostcursor/redact.py :: |\bAKIA[0-9A-Z]{16}\b -> |\bAKIA[0-9A-Za-z ]{16}
KILLED   ghostcursor/providers/clients.py :: return ipaddress.ip_address(host).is_loopback -> return host.startswith("127.")
KILLED   ghostcursor/providers/clients.py :: trust_env=not is_loopback(config.base_url), -> trust_env=True,
KILLED   ghostcursor/inference/ollama.py :: if is_loopback(endpoint) -> if False
KILLED   ghostcursor/providers/gateway.py :: if keep and placeholder[1:].rsplit("_", 1)[0] in redact.SECR -> if False:
KILLED   ghostcursor/workspace/app.py :: settings.set_keep_secrets_hidden(body.get("on") is True) -> settings.set_keep_secrets_hidden(bool(bo
```

The ollama.py guard changed after this sweep (it now keeps the plain call when
no proxy is configured). Re-run of that one mutant, `if is_loopback(endpoint)
and urllib.request.getproxies():` -> `if False:`, pytest summary line as printed:

```
1 failed, 115 passed in 3.67s
```
