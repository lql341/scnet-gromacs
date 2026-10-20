#!/usr/bin/env bash
# Compute-node module/device probe. Required: GROMACS_RUN_ROOT.
set -euo pipefail
: "${GROMACS_RUN_ROOT:?set a writable unique run root}"
module_name="${GROMACS_MODULE:-gromacs/2026.3}"
binary="${GROMACS_BINARY:-gmx_mpi}"
run="$GROMACS_RUN_ROOT/probe-${SLURM_JOB_ID:-manual-$$}"
mkdir -p "$run"
exec > >(tee "$run/probe.log") 2>&1

module purge
module load "$module_name"
echo "host=$(hostname)"
echo "module=$module_name"
echo "binary=$(command -v "$binary")"
"$binary" --version
if command -v rocminfo >/dev/null 2>&1; then
    rocminfo 2>&1 | grep -E 'Name:.*gfx|Agent [0-9]+|Marketing Name' | head -40 || true
fi
if command -v rocm-smi >/dev/null 2>&1; then
    rocm-smi --showproductname --showdriverversion 2>&1 || true
fi
