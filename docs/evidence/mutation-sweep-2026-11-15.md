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
and urllib.request.getproxies():` -> `if False:`, command
`py -3.12 -m pytest tests/test_providers.py -x -q --basetemp=.tmp/pytest-mut
-p no:cacheprovider`, pytest summary line as printed:

```
1 failed, 115 passed in 3.67s
```

## Third sweep: follow-ups of the third review

As printed:

```
D018 mutation sweep, third review follow-ups of 15 Nov 2026 (tree after cbaaca3)
KILLED   ghostcursor/redact.py :: |gsk_|nvapi-|tvly-|hf_) -> )
KILLED   ghostcursor/redact.py :: A(?:KI|SI)A[0-9A-Z]{16} -> AKIA[0-9A-Z]{16}
KILLED   ghostcursor/redact.py :: |\bAIza[-_A-Za-z0-9]{35}\b -> (removed)
KILLED   ghostcursor/redact.py :: if slashes % 2 and found[0] in "nrtfb" -> if slashes % 2 and found[0].lower() in "
KILLED   ghostcursor/providers/gateway.py :: placeholder, json.dumps(plain)[1:-1] -> placeholder, json.dumps(original)[1:-1]
KILLED   ghostcursor/workspace/app.py :: if urllib.request.getproxies() else urllib.request.urlopen(r -> if False else urllib.request.urlopen(req
```

## Fourth check: Google key ending in a hyphen

Mutant: `AIza[-_A-Za-z0-9]{35}(?![-\w])` -> `AIza[-_A-Za-z0-9]{35}\b` (the
pattern before the fix). Command `py -3.12 -m pytest
tests/test_workspace_redact.py -x -q --basetemp=.tmp/pytest-mut -p
no:cacheprovider`, summary line as printed:

```
1 failed, 18 passed in 1.31s
```

## Fifth sweep: remaining key shapes and plain-text paths

First run, as printed (one survivor: no test checked that the context a
cloud model receives stays valid JSON):

```
D018 mutation sweep, remaining gaps of 15 Nov 2026 (tree after 29fcfc3)
KILLED   ghostcursor/redact.py :: |glpat-|npm_|xai-|pplx-|r8_) -> )
KILLED   ghostcursor/redact.py :: "key" in m.re.groupindex -> False
KILLED   ghostcursor/redact.py :: if json_text and slashes % 2 -> if slashes % 2
KILLED   ghostcursor/redact.py :: if json_text and slashes % 2 -> if False and slashes % 2
SURVIVED ghostcursor/providers/gateway.py :: terms=terms, json_text=True -> terms=terms
```

After adding `test_the_context_a_cloud_model_gets_stays_valid_json_with_private_words`
to tests/test_providers.py, as printed:

```
D018 mutation sweep, remaining gaps of 15 Nov 2026 (tree after 29fcfc3)
KILLED   ghostcursor/redact.py :: |glpat-|npm_|xai-|pplx-|r8_) -> )
KILLED   ghostcursor/redact.py :: "key" in m.re.groupindex -> False
KILLED   ghostcursor/redact.py :: if json_text and slashes % 2 -> if slashes % 2
KILLED   ghostcursor/redact.py :: if json_text and slashes % 2 -> if False and slashes % 2
KILLED   ghostcursor/providers/gateway.py :: terms=terms, json_text=True -> terms=terms
```

## Sixth sweep: Company Brain sealed at rest

Command per mutant `py -3.12 -m pytest tests/test_workspace_knowledge.py -x -q`. As printed:

```
D018 mutation sweep, Company Brain sealed at rest, 15 Nov 2026 (tree after da8f4ea)
KILLED   ghostcursor/workspace/knowledge.py :: (_seal(text), source, scope, "candidate", sensitivity, now, now, -> (text, source, scope, "candidate", sensitivity, no
KILLED   ghostcursor/workspace/knowledge.py :: (_seal(text), source, scope, self.clock()), -> (text, source, scope, self.clock()),
KILLED   ghostcursor/workspace/knowledge.py :: self._db.execute("DROP TABLE IF EXISTS main.facts_fts") -> (removed)
KILLED   ghostcursor/workspace/knowledge.py :: "CREATE VIRTUAL TABLE temp.facts_fts USING -> "CREATE VIRTUAL TABLE IF NOT EXISTS main.facts_fts
KILLED   ghostcursor/workspace/knowledge.py :: and f.text != LOCKED -> (removed)
KILLED   ghostcursor/workspace/knowledge.py :: except Exception: # cannot seal now; next open tries again break -> except ZeroDivisionError: break
KILLED   ghostcursor/workspace/knowledge.py :: return Fact(row[0], _unseal(row[1]), *row[2:]) -> return Fact(*row)
```

## Seventh check: index spill and AWS secret ending

Each mutant run with `py -3.12 -m pytest <file> -x -q`; summary lines as printed:

```
temp_store pragma removed (knowledge.py) -> 1 failed, 43 passed in 2.53s
AWS secret ending back to  (redact.py) -> 1 failed, 21 passed in 1.16s
```

Spill probe after the fix (5000 sealed facts of about 700 characters,
TMP and TEMP pointed at an empty scratch folder, recall run once), as printed:

```
5000 facts of ~700 chars, temp files while open: []
```

Before the fix the reviewer's probe on the same shape listed one
`etilqs_*` temp file of 4,919,296 bytes (reported by the reviewer, not
re-run here).
