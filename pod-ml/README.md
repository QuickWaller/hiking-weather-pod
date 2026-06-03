# pod-ml — Weather prediction model for the hiking pod

Trains a small tree model on free reanalysis/precip data, to be exported to plain C and baked into
the pod firmware — replacing the current untested weighted-scoring weather algorithm.

> Full design rationale — every choice, with diagrams — lives in [`docs/`](docs/). This README is the
> working summary + status. See [docs/01-pipeline.md](docs/01-pipeline.md) and
> [docs/02-design-decisions.md](docs/02-design-decisions.md).

## What we're building (v1)

A **point-based** weather-severity predictor (zoning deferred to v2). Two models, framed as two hazards:

- **(a) Acute danger** — *max severity* class in the next H hours (ridge/exposure). Probe this first.
- **(b) River risk** — *24h rain accumulation* class (sustained soaker → dangerous crossings). Later.

Key design decisions (the non-obvious ones):

- **Predict horizon by sweeping lead {6,12,24,48h}**; report **skill-over-climatology (Brier Skill
  Score)**, never raw accuracy (at long horizons "no rain" scores ~85% while adding nothing).
- **Label = max severity in [T, T+H]**, not total accumulation, for the acute model.
- **Pressure tendency is the high-trust backbone**; temp/humidity are low-trust (siting/radiative bias on
  a backpack). Lean on rates (bias cancels in subtraction), not absolute level.
- **Sensor-sim layer** makes ERA5 look like the BME280 (offset, temp-comp, altitude error, cadence,
  quantization, asymmetric warm-bias augmentation). Even the skill probe runs through it.
- **Feature parity**: the pod's C++ feature functions are the single source of truth — compiled and
  called from Python via cffi, so training runs the exact on-device code (zero training-serving skew).
- **Ordinal threshold decomposition** (K−1 binary "severity ≥ k" classifiers), mapped onto the banner
  (yellow=P(≥2), red=P(≥4), buzzer=P(≥5)) — not a single softmax. Per-threshold operating points.
- **Validation**: contiguous past→future split, embargo = H at boundaries, climatology from a fixed
  reference period. Never random/shuffled (weather is autocorrelated → leakage).
- **Export** (v2): compact tree interpreter (flat arrays + ~30-line walk), not m2cgen unrolled if/else.

## Pipeline status

- [x] 1. Scaffold + environment
- [x] 2. Data acquisition + verification — ERA5-Land (5 NZ points, 1991–2024, 298k hrs, no gaps) +
       GPM IMERG labels (`precipitation` mm/hr, half-hourly, period-beginning) both verified
- [ ] 3. Sensor-sim + feature engineering  ← *current*
- [ ] 4. Label construction (max-severity + accumulation, embargo, timestamp alignment)
- [ ] 5. Skill probe (horizon sweep, BSS vs climatology)
- [ ] 6. Expand: more cells, threshold-decomposition models, tuning  *(gated on step 5)*
- [ ] 7. v2: zoning (SKATER), tree-interpreter export, flash to pod

## Environment setup

Using [`uv`](https://docs.astral.sh/uv/) (recommended — fast, manages the venv):

```powershell
# one-time: install uv
pip install uv

# create env + install deps
uv venv
uv pip install -e .
```

Or plain venv + pip if you prefer the familiar:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

## Development (lint + tests)

```powershell
uv pip install -e ".[dev]"      # pytest, ruff
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest -q
```

Tests pin the feature math (especially the `trailing_slope` OLS kernel against hand-computed truth) and
guard the parity invariant that **wind can never become a feature**. Run both before moving between steps.

### Pre-commit hook

A git pre-commit hook runs ruff + pytest automatically — but **only when `pod-ml/` files are staged**
(this is a shared repo with `pod/` firmware, `deck/`, etc.). Install once (and after a fresh clone —
git hooks aren't version-controlled):

```bash
bash scripts/install-hooks.sh
```

Source of truth: `scripts/pre-commit`. Bypass in a pinch with `git commit --no-verify`.

## Remote runner & multi-machine workflow

Long jobs (training sweeps, the GPM downloads) run on an always-on **Linux VM** so they don't tie up a
laptop. There is **no web server / no endpoints** — the only interface is **SSH + git over Tailscale**.

```
 laptop / phone ──SSH──► Proxmox VM (always-on: tmux jobs, git push results)
        │                       ▲ all over Tailscale
        └──── GitHub repo (code + results/docs/figures = source of truth) ────┘
 Pod (RP2350) ── USB ──► laptop ── git ──► repo ──► VM pulls   (logs for validate_log.py, later)
```

- **Git is the source of truth.** Both machines clone the repo; `pull` before work, `push` after — don't run
  conflicting jobs on both at once.
- **Jobs run on the VM** in `tmux` (survive disconnect), or via Claude Code's background tasks when Claude is
  running on the VM. Commit outputs, then `git pull` on the laptop to view figures.
- **Data is re-derived, not synced** — `data/`, `.venv/`, and credentials are gitignored, so on the VM just
  re-run the download scripts (reproducible) instead of copying big NetCDFs.

**One-time VM bring-up** (Debian/Ubuntu LTS · 4 GB · 1 socket × 4 cores · ~32 GB disk · on the tailnet):

```bash
sudo apt update && sudo apt install -y python3 python3-pip curl git tmux
git clone <your remote> && cd <repo>/pod-ml
bash scripts/setup-vm.sh          # uv + deps + tests + hook; prints the credential reminders
```

Then set credentials on the VM (`.cdsapirc` + `earthaccess.login(persist=True)`) and launch jobs in `tmux`.
**Pod logs** (field validation, later): the Pod is a microcontroller, not networked — copy its logs over USB
to the laptop, commit under `logs/`, push, and the VM picks them up for `validate_log.py`.

## Data access (needed for step 2)

- **ERA5-Land**: register at <https://cds.climate.copernicus.eu>, accept the ERA5-Land licence, put your
  API key in `~/.cdsapirc`. (Free.)
- **GPM IMERG**: register for a NASA Earthdata login at <https://urs.earthdata.nasa.gov>. (Free.)

## Layout

```
config/        domain + variable config (NZ bbox, time ranges, candidate variables)
src/podml/     config.py (paths/config) · dataio.py (load) · download_era5.py · download_gpm.py · features.py
data/          raw/ + processed/ (gitignored — large NetCDF/HDF)
notebooks/     exploration
tests/         unit tests (feature math + parity guards); golden-vector parity tests later
```
