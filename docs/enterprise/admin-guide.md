# Orbyn for small companies: admin guide (D187)

The owner sets Orbyn up once; staff use it. There is no Orbyn server: policy
comes from Group Policy or Intune, shared knowledge comes from a folder you
already have (SharePoint/OneDrive or a file share), and every PC keeps its own
audit log.

## 1. Install on every PC

Pick one:

- **MSIX (Intune, SCCM, winget).** Build `dist\Orbyn` with
  `pwsh -File tools\build_orbyn.ps1`, then package and sign it:
  `pwsh -File tools\package_msix.ps1 -Publisher "CN=<your cert subject>" -CertPath code.pfx -CertPassword <pw>`.
  Upload `dist\Orbyn.msix` to Intune as a line-of-business app. The `-Publisher`
  must equal the certificate's Subject exactly.
- **Per-machine script.** From an elevated shell:
  `pwsh -File tools\Install-Orbyn.ps1 -AllUsers` installs to Program Files with
  all-users shortcuts. Add `-Uninstall` to remove it. User data is kept.

The packaged app bundles its own Python; PCs need nothing else. Until the
build is signed, Windows SmartScreen will warn.

## 2. Set policy

Copy `tools\policy\Orbyn.admx` to `%SystemRoot%\PolicyDefinitions` (or your
central store) and `tools\policy\en-US\Orbyn.adml` to its `en-US` folder.
Orbyn then appears under Administrative Templates in both Computer and User
Configuration. In Intune, import the same ADMX under Configuration > Import
ADMX. Values live under `HKLM\Software\Policies\Orbyn` (machine first, then
user). A policy only ever lowers what Orbyn may do.

| Policy | Recommended for a small company |
|---|---|
| MaxEgress | 1 (text) unless you need pictures; 0 keeps everything on the PC |
| RedactEgress | Enabled |
| DisableAct | Enabled until you trust it; staff then get guidance only |
| AllowedApps | The apps you train on, e.g. `excel.exe;outlook.exe;msedge.exe` |
| BlockedApps | Password managers, banking apps |
| AllowedProviders | `company` (and `ollama` for the local model) |
| CompanyEndpoint / CompanyModel | Your model gateway, see 3 (each user opts in) |
| TeamFolder / TeamOwnerKey | See 4 |
| ShareAudit | Enabled if the owner should see every PC's log |

Allow-lists fail closed: a value that is set but unreadable allows nothing.

## 3. One company model account

Run an OpenAI-compatible gateway (Azure OpenAI behind API Management,
LiteLLM, or your provider's org endpoint) and set `CompanyEndpoint` to its
https URL. Each person then sees a "company model" switch in the
workspace's Privacy view, off by default; once they turn it on, Orbyn tries
the gateway before any personal account. A policy alone never adds a place
text is sent. If the gateway needs a
key, deploy it to each PC's Credential Manager rather than the registry:

    cmdkey /generic:Orbyn/company /user:orbyn /pass:<key>

The key then stays out of policy files and user settings. Personal keys stay
possible unless `AllowedProviders` excludes them.

## 4. The team folder

1. Create a folder the **owner can write** and **staff can only read**, for
   example a SharePoint library synced by OneDrive. The folder's permissions
   are the first line of defence; the signature is the second.
2. On the owner's PC: `py -3.12 -m ghostcursor.workspace.team init`. It
   prints a public key. Put it in `TeamOwnerKey`, and the folder path in
   `TeamFolder`, for every PC.
3. The owner approves facts in the Brain and saves task skills and agents,
   then runs `... team publish`. Sensitive facts and candidates are never
   published, and secrets inside fact text are scrubbed.
4. Staff PCs run `... team sync`. A bundle loads only if the pinned key signed
   it and it is not older than the last one loaded. Team facts land in the
   `team` scope and are used beside each person's own; team skills and agents
   are saved with a `team-` prefix and still run through plan approval.

The owner is whoever holds the private key that matches `TeamOwnerKey`. It is
in the owner's Credential Manager; back it up somewhere safe. To change owner,
run `init` on the new owner's PC and update the policy.

## 5. Audit

Every PC appends to `%LOCALAPPDATA%\GhostCursor\audit\audit.jsonl`: plan
approvals, each Act step and its outcome, signed-plugin runs, every model
request (provider, model, failure, picture count), and team publish/sync. It
records the Windows user name and app names, never goals, screen text, window
titles, handles, process ids or paths. Each line carries the hash of the line
before it.

    py -3.12 -m ghostcursor.audit verify          # "chain intact" or the broken line
    py -3.12 -m ghostcursor.audit export <file>

With `ShareAudit` on, `team sync` and `team publish` copy the log to
`<TeamFolder>\orbyn\audit\<opaque id>.jsonl`. The hash chain shows edits and
deletions inside a copy; it cannot stop someone with write access replacing
a whole file, so keep staff write access off the audit folder.

## Not yet

- SSO/SCIM: there is no Orbyn service to sign in to, so there are no Orbyn
  accounts. Windows sign-in and folder permissions are the identity.
- An owner dashboard over the shared audit logs.
- Live acceptance on Excel, Outlook and a browser app (see `ROADMAP.md`).
