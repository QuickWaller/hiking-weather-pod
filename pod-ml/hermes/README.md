# Hermes agent → pod-ml downloads

Lets the [Hermes Agent](https://github.com/NousResearch/hermes-agent) (on its own VM, DeepSeek
via Telegram) monitor and maintain the dataset downloads on the **ML VM**: check status, validate
files, restart a stuck pull, re-pull a bad month, and message you when something needs a human.

## How it fits together

```
  You ──Telegram──▶ Hermes Agent (Hermes VM, DeepSeek)
                          │  SSH terminal backend
                          ▼
                    hermes-pod-ml@ML-VM   (unprivileged login)
                          │  sudo -u claude  (one rule: podctl only)
                          ▼
                    podctl  ──▶ status_server.py --json   (read)
                            ──▶ podml.validate --json      (read)
                            ──▶ gpm/era5_watchdog.sh       (restart)
                            ──▶ rm month + clear sentinel  (repull)
```

The deterministic safety net already runs on the ML VM via cron (watchdogs relaunch dead pulls,
`hang_check.sh` kills stuck ones, `weekly_topup.sh` fetches new months). Hermes is **oversight on
top** — it doesn't replace that machinery, it watches it and intervenes through `podctl`.

## Pieces

| File | Where it lives | Purpose |
|------|----------------|---------|
| `../scripts/podctl` | ML VM (repo) | The operator vocabulary: status / validate / ps / logs / restart / repull |
| `../scripts/status_server.py` | ML VM (repo) | Now serves `GET /status.json` and `--json` one-shot |
| `../src/podml/validate.py` | ML VM (repo) | Deep integrity check of the downloaded months |
| `setup-account.sh` | run once on ML VM | Creates the `hermes-pod-ml` account + scoped sudo + `podctl` PATH shim |
| `SKILL.md` | Hermes VM skill library | Teaches the agent the vocabulary + when to alert |
| `config.example.yaml` | Hermes VM `~/.hermes/config.yaml` | DeepSeek + SSH backend + Telegram allowlist |

## Setup

**1. On the Hermes VM — make a key for the agent:**
```bash
ssh-keygen -t ed25519 -f ~/.ssh/hermes_pod_ml_ed25519 -C hermes@hermes-vm
cat ~/.ssh/hermes_pod_ml_ed25519.pub
```

**2. On the ML VM — create the account (as root), pasting that public key:**
```bash
sudo bash setup-account.sh "ssh-ed25519 AAAA... hermes@hermes-vm"
```

**3. From the Hermes VM — confirm SSH + podctl work:**
```bash
ssh -i ~/.ssh/hermes_pod_ml_ed25519 hermes-pod-ml@<ML-VM-IP> 'podctl status'
```

**4. Configure Hermes** — copy `config.example.yaml` to `~/.hermes/config.yaml`, fill your
Telegram chat/user ids and `ML_VM_HOST`, and put your secrets in `~/.hermes/.env`:
```
DEEPSEEK_API_KEY=sk-...
TELEGRAM_BOT_TOKEN=...
ML_VM_HOST=192.168.2.156
```

**5. Install the skill** — copy `SKILL.md` to the agent's skill library
(`~/.hermes/skills/podml-downloads/SKILL.md`), then start the gateway and message the bot
"how are the downloads?" to check the loop end-to-end.

> Find your Telegram ids by messaging your bot once and reading the gateway log, or with
> [@userinfobot](https://t.me/userinfobot).

## Recurring checks

Use Hermes' built-in cron to have the agent run the routine check (in `SKILL.md`) on a schedule —
e.g. every few hours — so it pings you proactively, not only when asked.

## Code-fix loop (bot drafts, you merge, admin deploys)

For problems that are in the *code* (not just operational), the bot drafts a fix in an isolated
workspace and hands it off — it never edits or deploys the live tree.

```
  Hermes(DeepSeek) finds a code-level issue
        │  (in ~/agent-work — a separate clone, owned by hermes-pod-ml)
        ▼
  agent-propose.sh <slug>  ──▶ pushes agent/<slug> + pings you on Telegram (what/why/PR link)
        │
        ▼
  You + Opus review the PR ──▶ merge to main   (branch protection keeps the gate)
        │
        ▼
  admin: deploy-live.sh [gpm|era5|all]  ──▶ resets live tree to origin/main + restarts
```

Setup (once, on the ML VM, after `setup-account.sh`):
```bash
sudo bash /home/claude/cyber-deck-and-weather-station/pod-ml/hermes/setup-agent-workspace.sh
# then seed the push token as the script instructs
```

Enforcement:
- The bot works only in `~/agent-work` and pushes only `agent/*` — it has no write access to the live tree.
- `deploy-live.sh` is **not** in the bot's sudo allowlist (which permits only `podctl`), so the bot cannot self-deploy.
- Enable **branch protection on `main`** (require a PR) so neither the bot nor a leaked token can reach `main` directly. This is the real gate; the rest is convention.

## Security posture

- The agent's login is **unprivileged**; it can only mutate downloads through `podctl`, and every
  restart/repull is appended to `podctl_audit.log` (with the SSH caller recorded).
- It **cannot** blanket-delete `data/raw` — `repull` removes one named month at a time.
- Telegram is locked to your chat/user id; anyone else messaging the bot is ignored.
- **Max-power alternative (less safe):** to give the agent an unrestricted shell instead, skip
  `setup-account.sh` and point the SSH backend at the `claude` user. Then a hallucinated or
  injected command can reach the data — keep an off-box snapshot of `data/raw` if you do this.
- **Claude Code on DeepSeek (optional, for code repairs):** if you want the agent to escalate to
  Claude Code for diagnosing/patching the downloader, route Claude Code through a proxy
  (`claude-code-router` or LiteLLM exposing an Anthropic-compatible `/v1/messages`) and set
  `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN`. Tool-use is less reliable than native Claude, so
  treat it as suggest-then-approve.
