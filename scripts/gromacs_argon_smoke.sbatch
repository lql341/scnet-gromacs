#!/usr/bin/env bash
# Run the bundled deterministic Argon case on a compute node.
# Required: GROMACS_RUN_ROOT. Set GROMACS_GPU_MODE=hip for HIP/DCU mode.
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
case_root="${GROMACS_CASE_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)/cases/argon8}"
run="$GROMACS_RUN_ROOT/argon-${mode}-${SLURM_JOB_ID:-manual-$$}"
mkdir -p "$run"
cp "$case_root"/{argon.gro,topol.top,md.mdp} "$run/"

module purge
module load "$module_name"
printf 'host=%s\nmodule=%s\nbinary=%s\nmode=%s\n' \
    "$(hostname)" "$module_name" "$binary" "$mode" | tee "$run/result.txt"
"$binary" --version >"$run/version.txt" 2>&1
gmx="$binary"

cd "$run"
if [ "$mode" = hip ]; then
    if command -v rocminfo >/dev/null 2>&1; then
        rocminfo 2>&1 | grep -E 'Name:.*gfx|Marketing Name|Agent [0-9]+' \
            | head -40 >device.txt || true
    else
        printf '%s\n' 'rocminfo=unavailable' >device.txt
    fi
fi
"$gmx" grompp -f md.mdp -c argon.gro -p topol.top -o argon.tpr \
    >grompp.log 2>&1

mdrun_args=(-s argon.tpr -deffnm argon -ntomp "${SLURM_CPUS_PER_TASK:-2}")
if [ "$mode" = hip ]; then
    # This no-charge Argon case has no PME electrostatics; offload the
    # non-bonded path without forcing an unsupported PME GPU path.
    mdrun_args+=(-nb gpu)
elif [ "$mode" != cpu ]; then
    echo "unsupported GROMACS_GPU_MODE=$mode" >&2
    exit 2
fi
"$gmx" mdrun "${mdrun_args[@]}" >mdrun.log 2>&1

if [ "$mode" = hip ]; then
    grep -Eq '[0-9]+ GPU selected for this run\.' mdrun.log
fi

"$gmx" energy -f argon.edr -o energy.xvg <<'EOF' >energy.log 2>&1
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
sha256sum argon.gro argon.tpr energy.xvg | tee -a result.txt
if [ "$mode" = hip ]; then
    cat device.txt >>result.txt
fi
echo 'status=passed' | tee -a result.txt
