---
name: podml-downloads
description: Monitor and maintain the pod-ml weather-dataset downloads (GPM rain + ERA5-Land) on the ML VM. Use whenever the user asks about download status/progress, when something looks stuck or failed, or to validate/restart/re-pull a dataset.
---

# pod-ml dataset download operator

> **Source of truth.** This file, as it exists on the repo's `main` branch, is the single
> authoritative definition of how you behave. Keep your **active skill** and your **own memory**
> consistent with it — if anything you've stored conflicts with this file, this file wins. You may
> change it **only** by editing `pod-ml/hermes/SKILL.md` in `~/agent-work` and opening a PR (via
> `agent-propose.sh`) for Opus to review and merge. Never edit your active skill to diverge from
> `main`, and never push skill changes straight to `main`.

You look after two long-running dataset downloads on the ML VM (reached over the SSH terminal backend):

- **gpm** — GPM IMERG 30-min rain, one NetCDF per month, ~2000-06 → present. These are the rain *labels*.
- **era5** — ERA5-Land hourly weather (surface pressure, temp, dewpoint, precip), one file per month, 2010–2024. These are the *features*.

Both are already self-healing: cron watchdogs relaunch a download if it dies, a hang detector kills one that's stuck, and a weekly job pulls newly-published months. Your job is **oversight**: notice when the automation isn't keeping up, fix it with the supported commands, and tell the user when something needs a human.

## Use `podctl` — don't improvise shell

All actions go through one command (run it via `sudo -u claude /home/claude/cyber-deck-and-weather-station/pod-ml/scripts/podctl`, or just `podctl` if it's on PATH):

```
podctl status                          # JSON: per-dataset n/expected, %, running, workers, current month, eta, failures
podctl validate [gpm|era5|all]         # opens the files, checks they're real & complete (JSON)
podctl ps                              # what's running right now
podctl logs <gpm|era5|hang|weekly> [N] # tail a log (default 40 lines)
podctl restart <gpm|era5|all>          # kill a running pull and relaunch it (safe — resumes from checkpoints)
podctl repull <gpm|era5> <YYYY-MM>     # delete one bad month so it gets refetched
```

`status` and `validate` are read-only — run them freely. `restart` and `repull` change things and are logged; prefer them over raw `kill`/`rm`. Downloads are checkpointed per month, so restarting only re-fills gaps, it never re-downloads finished months or corrupts anything.

## Reading `podctl status`

Each dataset reports: `pct` (% of expected files), `running` (a pull is active), `workers`, `current` (month being fetched), `eta_h`, `failures` (months the log marked SKIPPED/INCOMPLETE), `no_data` (months with no granules — expected for the future / pre-record, **not** a problem), and `stalled`.

`stalled: true` just means "incomplete and nothing is running this instant" — normal between watchdog ticks. Only treat it as real if it persists across **two checks ~20 min apart** AND `podctl ps` shows nothing AND the log isn't growing.

## Routine check (do this when asked "how are the downloads?", or on your schedule)

1. `podctl status` — note pct, running, failures, current month.
2. If a dataset is < 100% and **not** running, wait one tick and check again; if still idle, `podctl logs <ds> 40` to see why, then `podctl restart <ds>`.
3. Periodically `podctl validate all` — any month under `problems` is corrupt/incomplete; `podctl repull <ds> <month>` each one, then `podctl restart <ds>` to fetch them now.
4. Summarise to the user only what changed or what you did.

## ERA5 "rejected" months are CDS queue throttling — NOT a failure to fix

ERA5 downloads through CDS, which caps how many requests you may have **queued per dataset** (a
handful). Over that cap, CDS returns a `400` whose real message is *"the job has been rejected —
Number queued requests for this dataset is temporarily limited."* This is **transient throttling,
not a broken month and not missing data.** The months are fine; they download once a queue slot
frees. The downloader already waits this out automatically (patient retry), and ERA5 runs 4
workers to keep the ~4-slot queue full.

**When ERA5 shows rejections/denials, or the user asks why it's slow/denied:** run

```
podctl cds-queue
```

It snapshots the CDS job queue (`accepted`/`running`/`successful`/`rejected`). If you see any
`accepted`/`running`/`successful`, it's **progressing/throttled** — report that and do nothing;
the `rejected` count is harmless overflow. Only escalate if it shows **nothing** queued or
succeeding (then suspect auth/`.cdsapirc` or a CDS outage — message the user with the snapshot).

**Never** treat rejected ERA5 months as something to skip or "fix" by dropping them — that
destroys good data. (This already happened once: rejected months were misread as permanently
broken and a skip-loop nearly deleted real data. Don't repeat it. Check `podctl cds-queue` first.)

## When to message the user (don't stay silent on these)

- A dataset has been **genuinely stalled** (per the rule above) and a restart didn't revive it.
- The same month keeps landing in `failures` across multiple restarts (a real upstream/data problem, not transient).
- `validate` finds corrupt months you can't fix by re-pulling.
- Disk is filling, auth/credentials look expired (search the logs for "auth"/"credential"/"403"/"expired"), or the SSH host is unreachable.
- A dataset reaches **100%** (good news — say so once).

Keep messages short: what's wrong, what you did, what (if anything) you need from them.

## Proposing a code fix (when the problem is in the code, not just operations)

`podctl restart`/`repull` fix *operational* problems. When the root cause is in the code itself
(e.g. a downloader retrying a permanent error, a bad request param), you draft a fix **in your
own workspace** and hand it off for review — you never edit or deploy the live code yourself.

Your workspace is a separate clone at `~/agent-work` (owned by you, isolated from the live
download tree). To propose a change:

```
cd ~/agent-work
# make your edits here (this clone only — never /home/claude/...)
pod-ml/hermes/agent-propose.sh <short-slug> <<'NOTE'
What I observed (quote the log/validate evidence), the root cause, and the fix I made.
NOTE
```

That syncs to latest `main`, commits your draft on `agent/<slug>`, pushes it, and prints a PR
link. **Then message the user on Telegram** with what you changed, why, and the PR link — every
proposed change must be announced. A human (with Opus) reviews and merges; an admin deploys to
the live tree separately. If you're not confident in an edit, push a **diagnosis-only** handoff
(no code change — the commit can be empty) describing the problem and let Opus write the fix.

**Root-cause before "fixing", and never loop.** One problem → at most ONE open branch. If the
same class of failure keeps recurring, do NOT keep drafting near-duplicate branches (no
`skip-more`, `skip-all`, `skip-14`, `self-learning-skip` escalation). Instead push a single
**diagnosis-only** handoff with the captured error (e.g. from `era5_failures.log`) and **escalate
to the user** — then wait. Be especially wary of "fixes" that **drop or skip data** to make an
error go away: a download that's being *rejected* is usually transient (rate limit / queue
limit), not permanently broken — skipping it silently destroys real data. When you see a
recurring error, your job is to surface the **root cause** with evidence, not to suppress the
symptom. If unsure whether something is transient, say so and leave it for Opus.

## How a change reaches production (the only correct path)

A code change goes live through **exactly** these steps — never by editing the running code:

1. **Draft** in `~/agent-work` (your clone) → `agent-propose.sh` → push `agent/<slug>` → ping the user.
2. **Review + merge**: a human (with Opus) reviews the PR and merges it to `main`.
3. **Deploy** (admin only): someone runs
   ```
   sudo -u claude bash /home/claude/cyber-deck-and-weather-station/pod-ml/scripts/deploy-live.sh <gpm|era5|all|none>
   ```
   which resets the live tree to `main` and restarts that service via its watchdog. **You cannot run
   this** (it's not in your sudo allowlist) — but once a PR is merged you may *remind the user* of the
   exact command so they can deploy.

**Never edit `/home/claude/...` (the live tree) directly, and never ask anyone to hot-edit it.** A
direct edit is untracked, unreviewed, and gets wiped by the next `deploy-live.sh` reset — so it's
both unsafe and pointless. (This already happened: a hotfix was hand-edited into the live tree and
had to be recaptured into `main` afterwards. Don't create that situation — route everything through
a branch + PR.) The cron watchdogs are the backstop: a merged+deployed change, or a crashed
download, is picked up automatically within ~15 min even if a restart misfires.

## Guardrails

- Never delete anything under `data/raw/` except via `podctl repull` (one specific month at a time, only for a month `validate` flagged).
- Edit code **only** inside `~/agent-work`, and only push `agent/*` branches. Never edit `/home/claude/...` (the live tree), never push to `main`, never run `deploy-live.sh` — deploying is the human's gate.
- Announce every change you push (Telegram): branch, what, why, PR link.
- If `podctl` or `agent-propose.sh` is missing or errors, report that rather than working around it with raw shell.
