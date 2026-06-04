#!/usr/bin/env bash
# Create the `hermes-pod-ml` SSH account on the ML VM for the Hermes agent.
#
# Design: the agent logs in as an UNPRIVILEGED user (no sudo for general shell, can't
# touch the download data directly). It operates the downloads only through one vetted
# command — `podctl` — which it may run AS the download owner (`claude`) via a single
# narrow NOPASSWD sudo rule. So the agent has full control of the *download operations*
# (status/validate/restart/repull) and an audit trail, but cannot wipe `claude`'s home.
#
# Run on the ML VM as root (or with sudo):
#     sudo bash setup-account.sh "ssh-ed25519 AAAA... hermes@hermes-vm"
#
# Pass the Hermes agent's PUBLIC key as the first argument (generate it on the Hermes VM
# with `ssh-keygen -t ed25519 -C hermes@hermes-vm` and paste the .pub contents).
set -euo pipefail

PUBKEY="${1:?usage: setup-account.sh \"<agent ssh public key>\"}"
AGENT_USER="hermes-pod-ml"
OWNER="claude"                       # the user that owns the repo + runs the downloads
REPO="/home/$OWNER/cyber-deck-and-weather-station/pod-ml"
PODCTL="$REPO/scripts/podctl"

[ -d "$REPO" ] || { echo "repo not found at $REPO — fix REPO/OWNER in this script"; exit 1; }

# 1. Create the account (no password login, no sudo group membership).
if ! id "$AGENT_USER" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$AGENT_USER"
  echo "created user $AGENT_USER"
else
  echo "user $AGENT_USER already exists"
fi

# 2. Install the agent's SSH public key.
install -d -m 700 -o "$AGENT_USER" -g "$AGENT_USER" "/home/$AGENT_USER/.ssh"
echo "$PUBKEY" > "/home/$AGENT_USER/.ssh/authorized_keys"
chown "$AGENT_USER:$AGENT_USER" "/home/$AGENT_USER/.ssh/authorized_keys"
chmod 600 "/home/$AGENT_USER/.ssh/authorized_keys"
echo "installed authorized_keys"

# 3. Make podctl executable and let the agent run ONLY podctl as the download owner.
chmod +x "$PODCTL" "$REPO/scripts/"*.sh 2>/dev/null || true
SUDOERS="/etc/sudoers.d/hermes-podml"
echo "$AGENT_USER ALL=($OWNER) NOPASSWD: $PODCTL" > "$SUDOERS"
chmod 440 "$SUDOERS"
visudo -cf "$SUDOERS" >/dev/null && echo "installed sudo rule: $AGENT_USER may run podctl as $OWNER"

# 4. Convenience: a `podctl` shim on the agent's PATH that runs it as the owner, so the
#    agent (and the skill) can just type `podctl ...`.
cat > "/usr/local/bin/podctl" <<EOF
#!/usr/bin/env bash
exec sudo -u $OWNER $PODCTL "\$@"
EOF
chmod 755 "/usr/local/bin/podctl"
echo "installed /usr/local/bin/podctl shim (runs as $OWNER)"

# 5. Let the agent READ logs directly (for tailing) without sudo.
chmod o+rx "/home/$OWNER" 2>/dev/null || true   # traverse only; not recursive
for f in gpm_pull.log era5_pull.log hang_check.log weekly_topup.log podctl_audit.log; do
  [ -f "$REPO/$f" ] && chmod o+r "$REPO/$f" || true
done

cat <<EOF

Done. Test from the Hermes VM:
    ssh $AGENT_USER@<this-vm-ip> 'podctl status'

The agent's shell is unprivileged; it manages downloads only through 'podctl'.
To instead give it an UNRESTRICTED shell (max power, less safe), skip this script and
just point Hermes' SSH backend at the '$OWNER' user directly.
EOF
