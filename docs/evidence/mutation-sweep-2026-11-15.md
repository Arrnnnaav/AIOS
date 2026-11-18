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
AWS secret ending back to [backspace] (redact.py) -> 1 failed, 21 passed in 1.16s
```

Spill probe after the fix (5000 sealed facts of about 700 characters,
TMP and TEMP pointed at an empty scratch folder, recall run once), as printed:

```
5000 facts of ~700 chars, temp files while open: []
```

Before the fix the reviewer's probe on the same shape listed one
`etilqs_*` temp file of 4,919,296 bytes (reported by the reviewer, not
re-run here).

## Correction to the seventh check, and the last follow-ups

In the seventh check above, the line naming the AWS-secret mutant held a
literal backspace character (0x08) where `` was meant; it is shown above
as `[backspace]`, the only change made to that captured line. The review of
34000d8 found that its result line may belong to a different mutant than
the one named. The mutant is re-run below with the regex text written from
a script, together with the last review follow-ups. As printed:

```
D018 mutation sweep, last review follow-ups of 15 Nov 2026 (tree after 34000d8)
KILLED   ghostcursor/redact.py :: '(?P<key>[A-Za-z0-9/+=]{40})(?![A-Za-z0-9/+=])' -> '(?P<key>[A-Za-z0-9/+=]{40})\\b' :: 1 failed, 23 passed in 1.21s
KILLED   ghostcursor/redact.py :: '(?:[\\s\\"\':=]|\\\\[\\"nrt])+' -> '[\\s\\\\\\"\':=]+' :: 1 failed, 24 passed in 1.21s
KILLED   ghostcursor/workspace/brain.py :: 'self._db.execute("PRAGMA temp_store = MEMORY")  # VACUUM\'s copy neve -> '' :: 1 failed, 34 passed in 1.61s
```

## Eighth check: this computer's Office names hidden

Each mutant run with `py -3.12 -m pytest tests/test_enterprise_policy.py -x -q`; summary lines as printed:

```
identity_terms dropped from the private_terms merge (settings.py) -> 1 failed, 49 passed in 1.41s
OSError from the registry no longer caught (settings.py) -> 1 failed, 50 passed in 1.50s
```

## Ninth sweep: update check

First run, as printed (two survivors: no test pinned the headers sent or an older release):

```
D018 mutation sweep, update check, 15 Nov 2026
KILLED   ghostcursor/updates.py :: if not policy.allows("updates"): -> if False: :: 1 failed, 2 passed in 1.80s
SURVIVED ghostcursor/updates.py :: headers={"Accept": "application/vnd.github+json", "User-Agen -> headers={"Accept": "application/vnd.gith :: 3 passed in 1.55s
KILLED   ghostcursor/updates.py :: url.startswith(f"https://github.com/{REPOSITORY}/releases/") -> url.startswith("https://") :: 1 failed, 1 passed in 2.14s
SURVIVED ghostcursor/updates.py :: "newer": latest > mine -> "newer": latest != mine :: 3 passed in 1.05s
KILLED   ghostcursor/updates.py :: audit.record("egress", provider="updates", model=None, failu -> pass :: 1 failed in 2.07s
```

After adding `test_only_generic_headers_leave_and_an_older_release_is_not_newer`, as printed:

```
D018 mutation sweep, update check, 15 Nov 2026
KILLED   ghostcursor/updates.py :: if not policy.allows("updates"): -> if False: :: 1 failed, 2 passed in 1.53s
KILLED   ghostcursor/updates.py :: headers={"Accept": "application/vnd.github+json", "User-Agen -> headers={"Accept": "application/vnd.gith :: 1 failed, 3 passed in 1.43s
KILLED   ghostcursor/updates.py :: url.startswith(f"https://github.com/{REPOSITORY}/releases/") -> url.startswith("https://") :: 1 failed, 1 passed in 1.24s
KILLED   ghostcursor/updates.py :: "newer": latest > mine -> "newer": latest != mine :: 1 failed, 3 passed in 1.28s
KILLED   ghostcursor/updates.py :: audit.record("egress", provider="updates", model=None, failu -> pass :: 1 failed in 1.30s
```

## Tenth to thirteenth sweeps, 16 Nov 2026: offline chooser, mail to Brain, propose_fact, offline gates

Offline chooser, mail and propose_fact, first run (three survivors), as printed:

```
D018 mutation sweep, offline chooser, mail to Brain, propose_fact, 16 Nov 2026
KILLED   ghostcursor/providers/gateway.py :: providers=tuple(policy.LOCAL_PROVIDERS), -> (removed) :: 1 failed, 119 passed in 6.76s
SURVIVED ghostcursor/providers/gateway.py :: if exc.kind is FailureKind.CANCELLED or cancelled(): raise -> (removed) :: 120 passed in 6.73s
KILLED   ghostcursor/providers/gateway.py :: raise exc from None # no local answer either -> raise # no local answer either :: 1 failed, 57 passed in 3.45s
KILLED   ghostcursor/providers/gateway.py :: lambda content: parse_choice(json.loads(content), offered), -> lambda content: parse_choice(json.loads( :: 1 failed, 118 passed in 8.04s
SURVIVED ghostcursor/workspace/connectors.py :: if not isinstance(mid, str) or not mid.isdigit() or len(mid) -> if not isinstance(mid, str): :: 15 passed in 2.49s
KILLED   ghostcursor/workspace/connectors.py :: if found != subject: -> if False: :: 1 failed, 7 passed in 3.00s
KILLED   ghostcursor/workspace/connectors.py :: status, data = client.fetch(mid.encode("ascii"), "(BODY.PEEK -> status, data = client.fetch(mid.encode(" :: 1 failed, 7 passed in 2.95s
SURVIVED ghostcursor/workspace/connectors.py :: if part.get_content_type() == "text/plain" and not part.get_ -> if part.get_content_type() == "text/plai :: 15 passed in 2.55s
KILLED   ghostcursor/agent_server.py :: if len(pending) >= MAX_PENDING: -> if False: :: 1 failed, 11 passed in 5.23s
KILLED   ghostcursor/agent_server.py :: [fact], source=("agent: " + " ".join(source.split()))[:120], -> [fact], source=" ".join(source.split())[ :: 1 failed, 10 passed in 4.42s
```

After adding tests for a stopped choice, malformed message ids and an
attachment placed first, as printed:

```
D018 mutation sweep, offline chooser, mail to Brain, propose_fact, 16 Nov 2026
KILLED   ghostcursor/providers/gateway.py :: providers=tuple(policy.LOCAL_PROVIDERS), -> (removed) :: 1 failed, 119 passed in 6.60s
KILLED   ghostcursor/providers/gateway.py :: if exc.kind is FailureKind.CANCELLED or cancelled(): raise -> (removed) :: 1 failed, 120 passed in 7.31s
KILLED   ghostcursor/providers/gateway.py :: raise exc from None # no local answer either -> raise # no local answer either :: 1 failed, 57 passed in 2.96s
KILLED   ghostcursor/providers/gateway.py :: lambda content: parse_choice(json.loads(content), offered), -> lambda content: parse_choice(json.loads( :: 1 failed, 118 passed in 6.70s
KILLED   ghostcursor/workspace/connectors.py :: if not isinstance(mid, str) or not mid.isdigit() or len(mid) -> if not isinstance(mid, str): :: 1 failed, 7 passed in 2.28s
KILLED   ghostcursor/workspace/connectors.py :: if found != subject: -> if False: :: 1 failed, 7 passed in 2.29s
KILLED   ghostcursor/workspace/connectors.py :: status, data = client.fetch(mid.encode("ascii"), "(BODY.PEEK -> status, data = client.fetch(mid.encode(" :: 1 failed, 7 passed in 2.03s
KILLED   ghostcursor/workspace/connectors.py :: if part.get_content_type() == "text/plain" and not part.get_ -> if part.get_content_type() == "text/plai :: 1 failed, 7 passed in 2.11s
KILLED   ghostcursor/agent_server.py :: if len(pending) >= MAX_PENDING: -> if False: :: 1 failed, 11 passed in 3.37s
KILLED   ghostcursor/agent_server.py :: [fact], source=("agent: " + " ".join(source.split()))[:120], -> [fact], source=" ".join(source.split())[ :: 1 failed, 10 passed in 3.42s
```

Offline gates and the local answer parser (the last line was run separately
for voice.py, its summary line as printed):

```
D018 mutation sweep, offline gates and local answer parser, 16 Nov 2026
KILLED   ghostcursor/providers/chatgpt.py :: if not policy.allows("chatgpt"): # before the browser opens, -> if False: :: 1 failed, 51 passed in 4.89s
KILLED   ghostcursor/listen.py :: local = policy.max_egress() == policy.LOCAL -> local = False :: 1 failed, 52 passed in 3.92s
KILLED   ghostcursor/listen_kws.py :: if policy.max_egress() == policy.LOCAL: # offline: nothing i -> if False: :: 1 failed, 52 passed in 4.73s
KILLED   ghostcursor/providers/gateway.py :: kept = {k: v for k, v in raw.items() if k in allowed} -> kept = dict(raw) :: 1 failed, 121 passed in 7.24s
KILLED   ghostcursor/providers/gateway.py :: single = answer.get("probability", answer.get("confidence")) -> single = None :: 1 failed, 121 passed in 7.21s
ghostcursor/voice.py :: local = policy.max_egress() == policy.LOCAL -> local = False :: 1 failed, 53 deselected in 3.50s
```

Offline-only fallback and the name check, as printed:

```
D018 mutation sweep, offline-only fallback and name agreement, 16 Nov 2026
KILLED   ghostcursor/providers/gateway.py :: if policy.allows("jev"): raise -> (removed) :: 1 failed, 57 passed in 4.07s
KILLED   ghostcursor/providers/gateway.py :: return _agreed(choice, step, controls) -> return choice :: 1 failed, 119 passed in 7.46s
KILLED   ghostcursor/providers/gateway.py :: return choice if choice.choice == best else Choice(ABSTAIN,  -> return choice :: 1 failed, 119 passed in 10.74s
KILLED   ghostcursor/providers/gateway.py :: return Choice(ABSTAIN, {}) if not choice.abstained else choi -> return choice :: 1 failed, 119 passed in 7.92s
```

## Fourteenth check, 16 Nov 2026: review follow-ups

Each mutant run with `py -3.12 -m pytest <file> -x -q`; summary lines as printed:

```
ghostcursor/providers/gateway.py :: providers=tuple(policy.LOCAL_PROVIDERS) -> providers=None :: 1 failed, 54 passed in 3.81s
ghostcursor/workspace/connectors.py :: size check -> if False :: 1 failed, 7 passed in 2.39s
```

## Fifteenth check, 16 Nov 2026: mail by UID, export import

Each mutant run with `py -3.12 -m pytest <file> -x -q`; summary lines as printed:

```
ghostcursor/workspace/connectors.py :: client.uid("SEARCH", ...) -> client.search(...) :: 1 failed, 8 passed in 1.08s
ghostcursor/workspace/knowledge.py :: len(cells) >= 2 -> cells :: 1 failed, 44 passed in 2.82s
```

## Sixteenth check, 17 Nov 2026: name-check ties

Mutants run with `py -3.12 -m pytest tests/test_providers.py -x -q`; summary lines as printed:

```
tie rule removed (any tie allowed, first control wins) -> 1 failed, 123 passed in 20.42s
ghostcursor/providers/gateway.py :: tie only when one window -> any tie allowed :: 1 failed, 123 passed in 5.93s
```

## Seventeenth sweep, 18 Nov 2026: suggested goals and review follow-ups

As printed. Two survivors on the first run: the suggestion-id check is
equivalent (an id that matches no stored suggestion is refused as "gone"
anyway); the data label on error replies had no test, added, and the last
line is that mutant re-run:

```
D018 mutation sweep, suggested goals and review follow-ups, 18 Nov 2026
KILLED   ghostcursor/workspace/agent_inbox.py :: if len(rows) >= MAX_WAITING: -> if False: :: 1 failed, 14 passed in 3.58s
KILLED   ghostcursor/workspace/agent_inbox.py :: if any(r.get("goal", "").casefold() == goal.casefold() for r -> if False: :: 1 failed, 13 passed in 3.97s
KILLED   ghostcursor/workspace/agent_inbox.py :: temp.write_text(_seal(json.dumps(rows)), encoding="ascii") -> temp.write_text(json.dumps(rows), encodi :: 1 failed, 13 passed in 3.37s
KILLED   ghostcursor/workspace/app.py :: return {"goal": found["goal"]} if action == "agent_goal_use" -> if action == "agent_goal_use": self.hand :: 1 failed, 118 passed in 53.35s
SURVIVED ghostcursor/workspace/app.py :: if not isinstance(sid, str) or not sid.isalnum() or len(sid) -> if not isinstance(sid, str): :: 120 passed in 53.43s
KILLED   ghostcursor/workspace/app.py :: safe = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-") or -> safe = stem :: 1 failed, 119 passed in 53.79s
KILLED   ghostcursor/workspace/app.py :: if now - _last_error_log[0] < gap_s: -> if False: :: 1 failed, 119 passed in 53.48s
SURVIVED ghostcursor/agent_server.py :: text, failed = DATA_NOTE + _outbound(str(exc)), True -> text, failed = _outbound(str(exc)), True :: 120 passed in 53.76s
ghostcursor/agent_server.py :: DATA_NOTE on error replies removed (after adding test_error_replies_are_labelled_as_data_too) :: 1 failed, 14 passed in 3.96s
```

## Eighteenth sweep, 18 Nov 2026: local fact extraction

First run, as printed (one survivor: the bad-input test ran while a stand-in
already refused, so the input check was never the reason):

```
D018 mutation sweep, local fact extraction, 18 Nov 2026
KILLED   ghostcursor/providers/gateway.py :: purpose="extracting facts on this computer", providers=tuple -> purpose="extracting facts on this comput :: 1 failed, 229 deselected in 31.85s
KILLED   ghostcursor/providers/gateway.py :: tainted={"document_text": tainted_chunks("document", materia -> tainted={}, trusted_text=material, :: 1 failed, 229 deselected in 6.92s
KILLED   ghostcursor/providers/schemas.py :: if len(words.split()) >= 3: # a word or two is not a fact -> if True: :: 1 failed, 229 deselected in 5.54s
KILLED   ghostcursor/providers/schemas.py :: if not isinstance(facts, list) or len(facts) > MAX_EXTRACTED -> if not isinstance(facts, list): :: 1 failed, 1 passed, 229 deselected in 5.69s
KILLED   ghostcursor/providers/schemas.py :: if not isinstance(fact, str) or len(fact) > MAX_EXTRACTED_CH -> if not isinstance(fact, str): :: 1 failed, 1 passed, 229 deselected in 5.59s
SURVIVED ghostcursor/workspace/app.py :: or len(material) > 20_000 or "\0" in material ): raise Value -> ): raise ValueError("choose a text file  :: 3 passed, 229 deselected in 5.53s
```

After moving the bad inputs to where only the input check can refuse them
(the whole sweep re-run; its last line, as printed):

```
KILLED   ghostcursor/workspace/app.py :: or len(material) > 20_000 or "\0" in material ): raise Value -> ): raise ValueError("choose a text file  :: 1 failed, 2 passed, 229 deselected in 6.84s
```
