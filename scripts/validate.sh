#!/usr/bin/env bash
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
for script in "$root"/scripts/*.sh "$root"/scripts/*.sbatch; do
    bash -n "$script"
done
python3 - "$root/scripts/compare_gromacs_energy.py" \
    "$root/contrib/run_openapi.py" <<'PY'
import pathlib
import sys

for argument in sys.argv[1:]:
    path = pathlib.Path(argument)
    compile(path.read_text(), str(path), "exec")
PY
test -s "$root/cases/argon8/argon.gro"
test -s "$root/cases/argon8/topol.top"
test -s "$root/cases/argon8/md.mdp"
test -s "$root/cases/ionpair_pme/ionpair.gro"
test -s "$root/cases/ionpair_pme/topol.top"
test -s "$root/cases/ionpair_pme/md.mdp"
if grep -RInE '/public/home/|/home/[A-Za-z0-9_.-]+/' \
    "$root"/README* "$root"/references \
    "$root"/scripts/gromacs_*.sh "$root"/scripts/gromacs_*.sbatch \
    "$root"/scripts/compare_gromacs_energy.py \
    "$root"/contrib \
    "$root"/clusters "$root"/cases; then
    echo "private absolute path found" >&2
    exit 1
fi
echo "repository validation passed"
