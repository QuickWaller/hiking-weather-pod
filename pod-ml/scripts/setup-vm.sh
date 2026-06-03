#!/usr/bin/env bash
# Bring up the pod-ml Python environment on a fresh Linux runner (Debian/Ubuntu LTS).
# Idempotent — safe to re-run. Run from anywhere inside the repo after cloning:
#
#   git clone <your remote> && cd <repo>/pod-ml && bash scripts/setup-vm.sh
#
# Prereqs (install once on a bare VM):  sudo apt update && sudo apt install -y python3 python3-pip curl git tmux
set -euo pipefail

cd "$(dirname "$0")/.."   # -> pod-ml/
echo "[setup-vm] pod-ml at: $(pwd)"

# 1. uv (fast Python env manager) — pip first, else the official installer.
if ! command -v uv >/dev/null 2>&1; then
  echo "[setup-vm] installing uv..."
  pip3 install --user uv 2>/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
echo "[setup-vm] uv: $(uv --version)"

# 2. venv + deps (including dev: pytest, ruff)
uv venv
uv pip install -e ".[dev]"

# 3. verify the install
echo "[setup-vm] verifying (ruff + pytest)..."
.venv/bin/python -m ruff check src tests
.venv/bin/python -m pytest -q

# 4. install the pod-ml git hook (lint+test on pod-ml commits)
bash scripts/install-hooks.sh || echo "[setup-vm] (hook install skipped — not a git checkout?)"

cat <<'EOF'

[setup-vm] Environment ready. Two credential steps before downloads will work:

  1. CDS (ERA5) — create  pod-ml/.cdsapirc  with:
         url: https://cds.climate.copernicus.eu/api
         key: <your CDS personal access token>

  2. Earthdata (GPM) — run once (interactive; persists to netrc):
         .venv/bin/python -c "import earthaccess; earthaccess.login(persist=True)"
     (The GES DISC client approval is per-account and already done.)

Then re-derive data and run a job (use tmux so it survives disconnect):
     .venv/bin/python -m podml.download_era5 --full
     .venv/bin/python -m podml.probe && .venv/bin/python -m podml.plots
EOF
