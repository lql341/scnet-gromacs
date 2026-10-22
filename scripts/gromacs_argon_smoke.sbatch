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
module_name="${GROMACS_MODULE-gromacs/2026.3-dtk26.04-z100}"
binary="${GROMACS_BINARY:-gmx_mpi}"
mode="${GROMACS_GPU_MODE:-cpu}"
gpu_pme="${GROMACS_GPU_PME:-0}"
gpu_arch="${GROMACS_EXPECT_GPU_ARCH:-}"
expect_version="${GROMACS_EXPECT_VERSION:-}"
energy_terms="${GROMACS_ENERGY_TERMS:-Potential,Kinetic-En.,Temperature,LJ-(SR)}"
ranks="${GROMACS_MPI_RANKS:-1}"
ranks_per_node="${GROMACS_MPI_RANKS_PER_NODE:-}"
omp_threads="${GROMACS_OMP_THREADS:-${SLURM_CPUS_PER_TASK:-2}}"
npme="${GROMACS_NPME:-}"
expect_gpu_count="${GROMACS_EXPECT_GPU_COUNT:-}"
force_gpu_aware="${GROMACS_FORCE_GPU_AWARE_MPI:-0}"
launcher="${GROMACS_MPI_LAUNCHER:-srun}"
launcher_args="${GROMACS_MPI_LAUNCHER_ARGS:-}"
module_path="${GROMACS_MODULEPATH:-}"
env_script="${GROMACS_ENV_SCRIPT:-}"
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
if [ -n "$npme" ] && [ "$ranks" -le 1 ]; then
    echo 'GROMACS_NPME requires multiple MPI ranks' >&2
    exit 2
fi
if [ "$force_gpu_aware" = 1 ]; then
    export GMX_FORCE_GPU_AWARE_MPI=1
fi

if [ -n "$module_name" ]; then
    module purge
    if [ -n "$module_path" ]; then
        module use "$module_path"
    fi
    module load "$module_name"
elif [ -n "$env_script" ]; then
    # shellcheck disable=SC1090
    source "$env_script"
fi
"$binary" --version >"$run/version.txt" 2>&1
actual_version=$(awk '/^GROMACS version:/ {print $3; exit}' "$run/version.txt")
if [ -n "$expect_version" ] && [ "$actual_version" != "$expect_version" ]; then
    printf 'host=%s\nmodule=%s\nmode=%s\ngromacs_version=%s\ngromacs_expect=%s\nstatus=failed_version\n' \
        "$(hostname)" "$module_name" "$mode" "${actual_version:-unknown}" \
        "$expect_version" >"$run/result.txt"
    echo "expected GROMACS version $expect_version, got ${actual_version:-unknown}" >&2
    exit 3
fi
printf 'host=%s\nmodule=%s\nbinary=%s\nenv_script=%s\nmode=%s\npme_gpu=%s\ngpu_arch=%s\ngromacs_version=%s\ngromacs_expect=%s\nenergy_terms=%s\nmpi_ranks=%s\nomp_threads=%s\nnpme=%s\nexpect_gpu_count=%s\nforce_gpu_aware=%s\ncase=%s\n' \
    "$(hostname)" "$module_name" "$binary" "$env_script" "$mode" "$gpu_pme" "$gpu_arch" \
    "$actual_version" "$expect_version" "$energy_terms" "$ranks" \
    "$omp_threads" "$npme" "$expect_gpu_count" "$force_gpu_aware" "$gro" \
    | tee "$run/result.txt"
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

mdrun_args=(-s "$deffnm.tpr" -deffnm "$deffnm" -ntomp "$omp_threads")
if [ -n "$npme" ]; then
    mdrun_args+=(-npme "$npme")
fi
if [ "$mode" = hip ]; then
    mdrun_args+=(-nb gpu)
    if [ "$gpu_pme" = 1 ]; then
        # Only valid for a case with PME electrostatics enabled in md.mdp.
        # -npme is handled above and is only set for multiple MPI ranks.
        mdrun_args+=(-pme gpu)
    fi
elif [ "$mode" != cpu ]; then
    echo "unsupported GROMACS_GPU_MODE=$mode" >&2
    exit 2
fi
if [ "$ranks" -gt 1 ]; then
    case "$launcher" in
        mpirun|mpiexec)
            if [ -n "$launcher_args" ]; then
                read -r -a extra_launcher_args <<< "$launcher_args"
                "$launcher" "${extra_launcher_args[@]}" -np "$ranks" \
                    "$gmx" mdrun "${mdrun_args[@]}" >mdrun.log 2>&1
            else
                "$launcher" -np "$ranks" "$gmx" mdrun "${mdrun_args[@]}" \
                    >mdrun.log 2>&1
            fi
            ;;
        *)
            srun_args=(--ntasks="$ranks" --cpus-per-task="$omp_threads")
            if [ -n "$ranks_per_node" ]; then
                srun_args+=(--ntasks-per-node="$ranks_per_node")
            fi
            "$launcher" "${srun_args[@]}" \
                "$gmx" mdrun "${mdrun_args[@]}" >mdrun.log 2>&1
            ;;
    esac
else
    "$gmx" mdrun "${mdrun_args[@]}" >mdrun.log 2>&1
fi

grep -Eq "Using ${ranks} MPI process" "${deffnm}.log"
if [ -n "$npme" ] && [ "$ranks" -gt 1 ]; then
    grep -Eq "Using ${npme} separate PME ranks" "${deffnm}.log"
fi
if [ "$mode" = hip ]; then
    grep -Eq '[0-9]+ GPUs? selected for this run\.' mdrun.log
    if [ -n "$expect_gpu_count" ]; then
        selected_gpus=$(grep -Eo '[0-9]+ GPUs? selected for this run\.' mdrun.log \
            | head -1 | awk '{print $1}')
        if [ "$selected_gpus" != "$expect_gpu_count" ]; then
            echo "expected $expect_gpu_count GPUs, selected ${selected_gpus:-unknown}" >&2
            exit 4
        fi
    fi
    if [ -n "$gpu_arch" ]; then
        grep -Eq "Name:.*${gpu_arch}" device.txt
    fi
    if [ "$gpu_pme" = 1 ]; then
        grep -Eq 'PME tasks? will do .* on the GPU' mdrun.log
    fi
    if [ "${GROMACS_REQUIRE_GPU_AWARE_MPI:-0}" = 1 ]; then
        ! grep -q 'GPU-aware MPI was not detected' mdrun.log
    fi
fi

{
    printf '%s\n' "$energy_terms" | tr ',' '\n' | sed '/^[[:space:]]*$/d'
    printf '0\n'
} | "$gmx" energy -f "$deffnm.edr" -o energy.xvg >energy.log 2>&1

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
