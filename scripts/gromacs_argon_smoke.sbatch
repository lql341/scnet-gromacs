#!/usr/bin/env bash
# Run a bundled deterministic GROMACS case on a compute node.
# Required: GROMACS_RUN_ROOT. Set GROMACS_GPU_MODE=hip for HIP/DCU mode.
# Set GROMACS_CASE_ROOT to cases/ionpair_pme and GROMACS_GPU_PME=1 for PME.
#SBATCH --job-name=scnet_gmx_argon
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --time=00:15:00
set -euo pipefail

: "${GROMACS_RUN_ROOT:?set a writable unique run root}"
module_name="${GROMACS_MODULE:-gromacs/2026.3}"
binary="${GROMACS_BINARY:-gmx_mpi}"
mode="${GROMACS_GPU_MODE:-cpu}"
gpu_pme="${GROMACS_GPU_PME:-0}"
case_root="${GROMACS_CASE_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)/cases/argon8}"
gro="${GROMACS_CASE_GRO:-argon.gro}"
deffnm="${GROMACS_DEFFNM:-argon}"
run="$GROMACS_RUN_ROOT/argon-${mode}-${SLURM_JOB_ID:-manual-$$}"
mkdir -p "$run"
cp "$case_root/$gro" "$case_root/topol.top" "$case_root/md.mdp" "$run/"

if [ "$gpu_pme" = 1 ] && [ "$mode" != hip ]; then
    echo 'GROMACS_GPU_PME=1 requires GROMACS_GPU_MODE=hip' >&2
    exit 2
fi
case "$gpu_pme" in
    0|1) ;;
    *) echo "unsupported GROMACS_GPU_PME=$gpu_pme" >&2; exit 2 ;;
esac

module purge
module load "$module_name"
printf 'host=%s\nmodule=%s\nbinary=%s\nmode=%s\npme_gpu=%s\ncase=%s\n' \
    "$(hostname)" "$module_name" "$binary" "$mode" "$gpu_pme" "$gro" \
    | tee "$run/result.txt"
"$binary" --version >"$run/version.txt" 2>&1
gmx="$binary"

cd "$run"
sha256sum "$gro" topol.top md.mdp >inputs.sha256
if [ "$mode" = hip ]; then
    if command -v rocminfo >/dev/null 2>&1; then
        rocminfo 2>&1 | grep -E 'Name:.*gfx|Marketing Name|Agent [0-9]+' \
            | head -40 >device.txt || true
    else
        printf '%s\n' 'rocminfo=unavailable' >device.txt
    fi
fi
"$gmx" grompp -f md.mdp -c "$gro" -p topol.top -o "$deffnm.tpr" \
    >grompp.log 2>&1

mdrun_args=(-s "$deffnm.tpr" -deffnm "$deffnm" -ntomp "${SLURM_CPUS_PER_TASK:-2}")
if [ "$mode" = hip ]; then
    mdrun_args+=(-nb gpu)
    if [ "$gpu_pme" = 1 ]; then
        # Only valid for a case with PME electrostatics enabled in md.mdp.
        # Single-rank PME GPU must not pass -npme; GROMACS rejects that as a
        # request for a parallel simulation. Set GROMACS_NPME only when the
        # job really has multiple MPI ranks.
        mdrun_args+=(-pme gpu)
        if [ -n "${GROMACS_NPME:-}" ]; then
            mdrun_args+=(-npme "$GROMACS_NPME")
        fi
    fi
elif [ "$mode" != cpu ]; then
    echo "unsupported GROMACS_GPU_MODE=$mode" >&2
    exit 2
fi
"$gmx" mdrun "${mdrun_args[@]}" >mdrun.log 2>&1

if [ "$mode" = hip ]; then
    grep -Eq '[0-9]+ GPU selected for this run\.' mdrun.log
    if [ "$gpu_pme" = 1 ]; then
        grep -Eq 'PME tasks? will do .* on the GPU' mdrun.log
    fi
fi

"$gmx" energy -f "$deffnm.edr" -o energy.xvg <<'EOF' >energy.log 2>&1
Potential
Kinetic-En.
Temperature
0
EOF

grep -Eq 'Writing final coordinates\.|Finished mdrun' mdrun.log
awk '
  $0 !~ /^[@#]/ && NF >= 2 {
      seen = 1
      for (i = 1; i <= NF; ++i)
          if ($i != $i || $i !~ /^[-+0-9.eE]+$/)
              exit 1
  }
  END { exit seen ? 0 : 1 }
' energy.xvg
sha256sum "$deffnm.gro" "$deffnm.tpr" energy.xvg | tee -a result.txt
if [ "$mode" = hip ]; then
    cat device.txt >>result.txt
fi
echo 'status=passed' | tee -a result.txt
