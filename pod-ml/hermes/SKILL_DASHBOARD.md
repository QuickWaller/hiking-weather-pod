---
name: podml-dashboard
description: Manage and update the pod-ml status dashboard (dashboard_server.py, port 8000) on the ML VM. Use when the user asks about the website/dashboard, asks you to update it, or reports it's down.
---

# pod-ml dashboard operator

> **Source of truth.** This file, as it exists on the repo's `main` branch, is authoritative.
> You may change it **only** by editing `pod-ml/hermes/SKILL_DASHBOARD.md` in `~/agent-work`
> and opening a PR via `agent-propose.sh` for Opus to review. Never edit your active skill to
> diverge from `main`.

You manage `dashboard_server.py` — the pod-ml status website that runs on port 8000 of the ML VM.
It shows download progress, validation status, and log tails for GPM, ERA5-core, and ERA5-more_labels_1.
**You only touch the dashboard when the user asks** — no proactive monitoring; just respond.

## Two servers — important

There are **two** Python servers on the VM. Don't confuse them:

| Server | Port | File | Used by |
|---|---|---|---|
| `dashboard_server.py` | 8000 | `scripts/dashboard_server.py` | Browser, `/api` endpoint |
| `status_server.py` | (CLI only) | `scripts/status_server.py` | `podctl status` (agent) |

`podctl status` and `podctl dashboard` both operate on `dashboard_server.py` at port 8000.
`status_server.py` is separate — it's the JSON backend for the agent's own status checks.
When the user or you checks `/api` or the browser, that's `dashboard_server.py`.

## Commands

All dashboard actions go through the **`/usr/local/bin/podctl` shim** — always use that, never
the raw script path. The shim wraps every call with `sudo -u claude` automatically:

```
podctl dashboard           # status: running, pid, uptime_s (JSON)
podctl dashboard restart   # kill + relaunch (logged to podctl_audit.log)
podctl dashboard deploy    # pull origin/main dashboard_server.py into live tree + restart
podctl logs dashboard [N]  # tail dashboard_server.log (default 40 lines)
```

## Checking and restarting

When the user asks if the dashboard is up:

1. `podctl dashboard` — check `running` field.
2. If `running: false`, try `podctl dashboard restart`.
3. If it's still down, `podctl logs dashboard 80` — look for tracebacks or import errors.
4. Report back: what you found, what you did, what (if anything) needs the user.

If a restart fails and the log shows a Python error, the code needs fixing — use the
standard code-fix path (`agent-work` → `agent-dashboard.sh` once fixed, see below).

## Editing the dashboard

Dashboard edits skip the PR review gate — they deploy directly to `main` and go live immediately.
Use `agent-dashboard.sh` (not `agent-propose.sh`):

```bash
cd ~/agent-work
git fetch origin
git checkout main
git reset --hard origin/main        # sync to latest first — always

# ... edit pod-ml/scripts/dashboard_server.py ...

pod-ml/hermes/agent-dashboard.sh <short-slug> <<'NOTE'
What changed and why (e.g. "add more_labels_1 row to ERA5 table").
NOTE
```

`agent-dashboard.sh`:
- Commits the change to `main` and pushes directly (no PR needed)
- Calls `podctl dashboard deploy` to update the live file and restart the server
- **Only stages `dashboard_server.py`** — errors if you accidentally touched other files

**Always announce changes on Telegram** after running: what you changed, why, and that it's live.

## What you may edit

- `pod-ml/scripts/dashboard_server.py` — the entire status website lives here. It generates
  HTML dynamically; the content (file counts, logs, etc.) updates automatically as downloads
  progress. You'd edit it to: add a new dataset row, change the layout, fix a display bug,
  add a chart, or update styling.

**Do not use `agent-dashboard.sh` for anything else.** Changes to `podctl`, watchdogs, Python
modules, SKILL.md, or data files still go through `agent-propose.sh` + PR.

## How a change reaches production

```
edit in ~/agent-work
       ↓
agent-dashboard.sh <slug>   →  git push origin main
                               podctl dashboard deploy
                                   ↓
                               git checkout origin/main -- dashboard_server.py  (live tree)
                               restart dashboard_server.py
                               ↓
                           live at http://localhost:8000
```

Compare with the standard path (code fix): `agent-work` → `agent-propose.sh` → PR → admin runs `deploy-live.sh`.

## Live tree state after agent-dashboard.sh

`podctl dashboard deploy` updates `dashboard_server.py` in the live tree via
`git checkout origin/main -- file`. This leaves the live tree with HEAD behind
origin/main and the file staged. **This is normal and expected.**

`deploy-live.sh` (the admin deploy script) handles this correctly — it compares
the working tree to origin/main, not HEAD, so the staged file is not a blocker.
If an admin needs to run `deploy-live.sh` after you've deployed a dashboard change,
it will just work.

## Guardrails

- Only edit `pod-ml/scripts/dashboard_server.py` via this path. Everything else uses PRs.
- Never edit any live file directly — not `/home/claude/...`, not anywhere outside `~/agent-work`. Even if permissions let you, a direct edit is untracked and gets wiped by the next deploy.
- Always use `/usr/local/bin/podctl` (the shim), not the raw script path. The shim adds `sudo -u claude`; without it, `podctl deploy` will fail with a permission error on the audit log or the live tree.
- If `podctl dashboard deploy` fails with a permission error, **stop and escalate** — don't try to write the live file directly. The fix is to ensure you're going through the shim.
- Announce every change on Telegram after deploying: what changed and why.
- If `agent-dashboard.sh` fails with "unexpected staged files", unstage them and re-check — you've accidentally staged something outside the dashboard.
- If the push is rejected (branch protection), escalate to the user rather than force-pushing.
