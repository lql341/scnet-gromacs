#!/usr/bin/env python3
"""Check vendored adapter integrity and pinned-source agreement.

Offline: verify every file against scripts/vendor-manifest.json.
Online:  fetch the pinned upstream blobs and compare bytes.

The script never reads credentials and never contacts SCNet.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "scripts" / "vendor-manifest.json"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def raw_url(repository, commit, path):
    repo = repository.rstrip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    if repo.startswith("https://github.com/"):
        repo = "https://raw.githubusercontent.com/" + repo[len("https://github.com/") :]
    return "{}/{}/{}".format(repo, commit, path.lstrip("/"))


def fetch(url, attempts=3):
    last = None
    for attempt in range(attempts):
        try:
            with urlopen(url, timeout=30) as response:
                return response.read()
        except (HTTPError, URLError, OSError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(1 + attempt)
    raise last


def load_manifest():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("vendor manifest must be an object")
    return data


def check_local(manifest):
    errors = []
    results = {}
    for section in ("files", "derivatives"):
        for relative, meta in (manifest.get(section) or {}).items():
            path = ROOT / relative
            if not path.is_file():
                errors.append("missing local file: " + relative)
                continue
            actual = digest(path.read_bytes())
            expected = meta.get("sha256")
            results[relative] = {"sha256": actual, "matches_manifest": actual == expected}
            if actual != expected:
                errors.append("local checksum mismatch: " + relative)
    return results, errors


def check_online(manifest):
    results = {}
    errors = []
    repo = manifest.get("repository")
    commit = manifest.get("commit")
    upstream_repo = manifest.get("upstream_repository") or repo
    upstream_commit = manifest.get("upstream_commit") or commit
    if not (repo and commit and upstream_repo and upstream_commit):
        return results, ["vendor manifest is missing repository/commit provenance"]
    for relative, meta in (manifest.get("files") or {}).items():
        path = meta.get("upstream_path") or relative
        url = raw_url(upstream_repo, upstream_commit, path)
        try:
            remote = fetch(url)
        except (HTTPError, URLError, OSError) as exc:
            errors.append("cannot fetch {}: {}".format(url, exc))
            continue
        local = (ROOT / relative).read_bytes()
        results[relative] = {
            "url": url,
            "matches_pinned": local == remote,
            "sha256": digest(remote),
        }
        if local != remote:
            errors.append("pinned upstream mismatch: " + relative)
    for relative, meta in (manifest.get("derivatives") or {}).items():
        if repo == upstream_repo and meta.get("modified"):
            # A locally modified derivative has no upstream byte-for-byte oracle.
            continue
        path = meta.get("upstream_path") or relative
        url = raw_url(repo, commit, path)
        try:
            remote = fetch(url)
        except (HTTPError, URLError, OSError) as exc:
            errors.append("cannot fetch {}: {}".format(url, exc))
            continue
        local = (ROOT / relative).read_bytes()
        results[relative] = {
            "url": url,
            "matches_pinned": local == remote,
            "sha256": digest(remote),
        }
        if local != remote:
            errors.append("pinned derivative mismatch: " + relative)
    return results, errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--online", action="store_true", help="compare with pinned upstream blobs")
    parser.add_argument("--json", action="store_true", help="emit machine-readable status")
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest()
        local, errors = check_local(manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("adapter check failed: {}".format(exc), file=sys.stderr)
        return 1
    online = {}
    if args.online:
        online, online_errors = check_online(manifest)
        errors.extend(online_errors)
    result = {
        "ok": not errors,
        "manifest": str(MANIFEST.relative_to(ROOT)),
        "local": local,
        "online": online,
        "errors": errors,
    }
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("adapter_manifest={}".format(result["manifest"]))
        print("local_checks={}".format("ok" if not any("local" in e for e in errors) else "failed"))
        if args.online:
            print("pinned_checks={}".format("ok" if not online_errors else "failed"))
        for error in errors:
            print("error: " + error, file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
