#!/usr/bin/env python3
"""Compare CPU-oracle and HIP energy time series for a tiny GROMACS case.

The comparison is deliberately narrow: both runs must have written
``status=passed``, consumed the same input files, and produced the same time
grid and energy columns. Each checked term must stay inside a documented
absolute-plus-relative tolerance. This is not a bitwise trajectory comparison
and is not evidence of production performance.
"""

import argparse
import math
import re
import sys
from pathlib import Path

DEFAULT_TERMS = ("Potential", "Kinetic En.", "Temperature")
TERM_LEGENDS = {
    "Potential": "Potential",
    "Kinetic-En.": "Kinetic En.",
    "Temperature": "Temperature",
    "LJ-(SR)": "LJ (SR)",
    "Coulomb-(SR)": "Coulomb (SR)",
    "Coul.-recip.": "Coul. recip.",
    "Total-Energy": "Total Energy",
}
LEGEND_RE = re.compile(r'^@\s+s(\d+)\s+legend\s+"(.*)"\s*$')
REQUIRED_INPUTS = {"topol.top", "md.mdp"}


class CompareError(Exception):
    """Raised when an input is missing or malformed."""


def read_kv(path):
    values = {}
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip()
    return values


def read_input_hashes(run_dir):
    path = run_dir / "inputs.sha256"
    if not path.is_file():
        raise CompareError(
            "{} is missing; rerun the smoke script so input provenance is recorded".format(
                path
            )
        )
    hashes = {}
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        fields = line.split()
        if len(fields) != 2:
            raise CompareError(
                "{}:{} is not a sha256sum line".format(path, lineno)
            )
        digest, name = fields
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise CompareError(
                "{}:{} has an invalid sha256 digest".format(path, lineno)
            )
        hashes[Path(name).name] = digest
    if not REQUIRED_INPUTS.issubset(hashes):
        raise CompareError(
            "{} does not record {}".format(
                path, ", ".join(sorted(REQUIRED_INPUTS))
            )
        )
    return hashes


def parse_terms(result):
    raw = result.get("energy_terms", "")
    if not raw:
        return DEFAULT_TERMS
    terms = tuple(term.strip() for term in raw.split(",") if term.strip())
    if not terms:
        return DEFAULT_TERMS
    return tuple(TERM_LEGENDS.get(term, term) for term in terms)


def parse_energy(path, terms):
    if not path.is_file():
        raise CompareError("{} is missing".format(path))

    legends = {}
    rows = []
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("@"):
            match = LEGEND_RE.match(line)
            if match:
                legends[int(match.group(1))] = match.group(2)
            continue
        fields = line.split()
        try:
            values = [float(field) for field in fields]
        except ValueError:
            raise CompareError(
                "{}:{} contains a non-numeric data field".format(path, lineno)
            )
        if not all(math.isfinite(value) for value in values):
            raise CompareError(
                "{}:{} contains a non-finite data field".format(path, lineno)
            )
        rows.append(values)

    if not rows:
        raise CompareError("{} has no data rows".format(path))
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise CompareError("{} has inconsistent row widths".format(path))

    wanted = set(terms)
    columns = {}
    for index, name in legends.items():
        if name in wanted:
            if index + 1 >= width:
                raise CompareError(
                    "{} legend {!r} has no matching data column".format(path, name)
                )
            columns[name] = [row[index + 1] for row in rows]
    missing = [term for term in terms if term not in columns]
    if missing:
        raise CompareError(
            "{} is missing energy columns: {}".format(path, ", ".join(missing))
        )
    return [row[0] for row in rows], columns


def compare_term(cpu, hip, atol, rtol):
    max_abs = 0.0
    max_rel = 0.0
    worst_margin = -math.inf
    for cpu_value, hip_value in zip(cpu, hip):
        diff = abs(cpu_value - hip_value)
        scale = max(abs(cpu_value), abs(hip_value))
        allowed = atol + rtol * scale
        max_abs = max(max_abs, diff)
        if scale > 0.0:
            max_rel = max(max_rel, diff / scale)
        worst_margin = max(worst_margin, diff - allowed)
    return max_abs, max_rel, worst_margin


def format_delta(value):
    return "{:.3e}".format(value)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Compare CPU-oracle and HIP GROMACS energy output."
    )
    parser.add_argument("cpu_run", type=Path, help="CPU run directory")
    parser.add_argument("hip_run", type=Path, help="HIP run directory")
    parser.add_argument(
        "--energy-atol",
        type=float,
        default=0.05,
        help="absolute tolerance for Potential/Kinetic in kJ/mol (default: 0.05)",
    )
    parser.add_argument(
        "--temperature-atol",
        type=float,
        default=0.5,
        help="absolute tolerance for Temperature in K (default: 0.5)",
    )
    parser.add_argument(
        "--rtol",
        type=float,
        default=1e-3,
        help="relative tolerance applied per data point (default: 1e-3)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="optional path for the plain-text comparison report",
    )
    args = parser.parse_args(argv)

    try:
        results = {}
        for run_dir, expected_mode in (
            (args.cpu_run, "cpu"),
            (args.hip_run, "hip"),
        ):
            if not run_dir.is_dir():
                raise CompareError("{} is not a directory".format(run_dir))
            result = read_kv(run_dir / "result.txt")
            results[expected_mode] = result
            if result.get("status") != "passed":
                raise CompareError(
                    "{} did not write status=passed".format(run_dir / "result.txt")
                )
            if result.get("mode") != expected_mode:
                raise CompareError(
                    "{} has mode={!r}, expected {!r}".format(
                        run_dir / "result.txt",
                        result.get("mode"),
                        expected_mode,
                    )
                )

        cpu_terms = parse_terms(results["cpu"])
        hip_terms = parse_terms(results["hip"])
        if cpu_terms != hip_terms:
            raise CompareError(
                "energy term lists differ: CPU={} HIP={}".format(
                    ",".join(cpu_terms), ",".join(hip_terms)
                )
            )
        terms = cpu_terms

        cpu_hashes = read_input_hashes(args.cpu_run)
        hip_hashes = read_input_hashes(args.hip_run)
        if cpu_hashes != hip_hashes:
            raise CompareError(
                "input checksums differ between CPU and HIP runs: {}".format(
                    args.cpu_run / "inputs.sha256"
                )
            )

        cpu_times, cpu_columns = parse_energy(
            args.cpu_run / "energy.xvg", terms
        )
        hip_times, hip_columns = parse_energy(
            args.hip_run / "energy.xvg", terms
        )
        if len(cpu_times) != len(hip_times):
            raise CompareError(
                "frame counts differ: CPU={} HIP={}".format(
                    len(cpu_times), len(hip_times)
                )
            )
        for index, (cpu_time, hip_time) in enumerate(zip(cpu_times, hip_times), 1):
            if abs(cpu_time - hip_time) > 1e-9:
                raise CompareError(
                    "time grid differs at frame {}: CPU={} HIP={}".format(
                        index, cpu_time, hip_time
                    )
                )

        lines = [
            "GROMACS CPU/HIP energy comparison",
            "CPU run: {}".format(args.cpu_run.name),
            "HIP run: {}".format(args.hip_run.name),
            "input checksums: identical ({})".format(
                ", ".join(sorted(cpu_hashes))
            ),
            "frames: {}".format(len(cpu_times)),
            "energy terms: {}".format(", ".join(terms)),
            "",
            "{:<20} {:>12} {:>12} {:>14}  {}".format(
                "term", "max_abs", "max_rel", "worst_margin", "status"
            ),
        ]

        failed = False
        for term in terms:
            atol = args.temperature_atol if term == "Temperature" else args.energy_atol
            max_abs, max_rel, worst_margin = compare_term(
                cpu_columns[term], hip_columns[term], atol, args.rtol
            )
            passed = worst_margin <= 0.0
            failed = failed or not passed
            lines.append(
                "{:<20} {:>12} {:>12} {:>14}  {}".format(
                    term,
                    format_delta(max_abs),
                    format_delta(max_rel),
                    format_delta(worst_margin),
                    "PASS" if passed else "FAIL",
                )
            )

        lines.extend(
            [
                "",
                "tolerance: |CPU-HIP| <= atol + rtol * max(|CPU|, |HIP|)",
                "atol: energy terms={} kJ/mol, Temperature={} K, rtol={}".format(
                    args.energy_atol, args.temperature_atol, args.rtol
                ),
                "final CPU: " + ", ".join(
                    "{}={:.6g}".format(term, cpu_columns[term][-1])
                    for term in terms
                ),
                "final HIP: " + ", ".join(
                    "{}={:.6g}".format(term, hip_columns[term][-1])
                    for term in terms
                ),
                "comparison={}".format("failed" if failed else "passed"),
            ]
        )

        text = "\n".join(lines) + "\n"
        sys.stdout.write(text)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(text)
        return 1 if failed else 0
    except CompareError as exc:
        sys.stderr.write("comparison error: {}\n".format(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
