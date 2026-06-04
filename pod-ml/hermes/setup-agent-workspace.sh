#!/usr/bin/env bash
# Create the bot's isolated CODE workspace on the ML VM.
#
# This is a SEPARATE clone owned by hermes-pod-ml at ~/agent-work — physically distinct from
# the live download tree (/home/claude/...). The bot drafts fixes here and pushes agent/*
# branches for review; it can never disturb the running downloads, and it has no write access
# to claude's live repo. Deploying a reviewed change to the live tree is a separate admin step
# (deploy-live.sh), which the bot's sudo rule deliberately does NOT cover.
#
# Run on the ML VM as root:  sudo bash setup-agent-workspace.sh
set -euo pipefail

AGENT_USER="hermes-pod-ml"
WORK="/home/$AGENT_USER/agent-work"
REMOTE="https://github.com/QuickWaller/cyber-deck-and-weather-station.git"

id "$AGENT_USER" >/dev/null 2>&1 || { echo "run setup-account.sh first (no $AGENT_USER user)"; exit 1; }

if [ ! -d "$WORK/.git" ]; then
  sudo -u "$AGENT_USER" git clone "$REMOTE" "$WORK"
else
  echo "workspace already exists at $WORK"
fi

# Identifiable bot author so `git log` clearly distinguishes bot drafts from human commits.
sudo -u "$AGENT_USER" git -C "$WORK" config user.name  "hermes-bot"
sudo -u "$AGENT_USER" git -C "$WORK" config user.email "hermes-bot@users.noreply.github.com"
sudo -u "$AGENT_USER" git -C "$WORK" config credential.helper store

cat <<EOF

Workspace ready at $WORK (owned by $AGENT_USER).

ONE manual step — seed the push token so the bot can push non-interactively
(the bot can't answer a credential prompt). Paste your QuickWaller PAT below:

  read -rsp 'QuickWaller PAT: ' PAT; echo
  echo "https://QuickWaller:\$PAT@github.com" | sudo -u $AGENT_USER tee /home/$AGENT_USER/.git-credentials >/dev/null
  sudo -u $AGENT_USER chmod 600 /home/$AGENT_USER/.git-credentials
  unset PAT

SECURITY: that stores the PAT in $AGENT_USER's home (plaintext, 600). The real
safeguard is branch protection on 'main' (require a PR review) so the bot — or a
leaked token — still can't reach main directly. Enable it in GitHub repo settings.
Later you can swap the shared PAT for a dedicated, revocable fine-grained token.
EOF
