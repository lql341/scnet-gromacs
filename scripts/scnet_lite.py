#!/usr/bin/env python3
"""Self-contained minimal SCNet OpenAPI client for scnet-hashcat.

This is a trimmed subset of the transport layer from scnet-hpc
(https://github.com/lql341/scnet-hpc, MIT license, (c) lql341), reduced to the
endpoints a distributed hashcat run needs:

  auth / region discovery / center     submit / job status / cancel
  log tail (file content)              efile list/mkdir/upload/download/remove
  account / queues / limits

No third-party dependencies; Python 3.8+ standard library only.

Credentials, in resolution order:
  1. SCNET_OPENAPI_USER / SCNET_OPENAPI_ACCESS_KEY / SCNET_OPENAPI_SECRET_KEY
  2. OS credential store, service scnet-hpc-openapi (shared with scnet-hpc)

config.json contains only non-secret choices, including default_region_id.

Every command prints a JSON object to stdout. Errors go to stderr with a
non-zero exit status.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from scnet_credentials import CredentialError, load_openapi_credentials
from scnet_version import VERSION
USER_AGENT = f"scnet-hashcat/{VERSION}"

DEFAULT_AUTH_BASE = "https://api.scnet.cn"
DEFAULT_CENTER_URL = "https://www.scnet.cn/ac/openapi/v2/center"
DEFAULT_USER_URL = "https://www.scnet.cn/ac/openapi/v2/user"
TOKEN_CACHE_TTL = 4 * 60 * 60

# Raw scheduler state -> normalized state. Terminal states are the ones the
# wait command treats as final.
STATUS_MAP = {
    "statR": "RUNNING",
    "statQ": "PENDING",
    "statH": "HELD",
    "statS": "SUSPENDED",
    "statE": "EXITING",
    "statC": "COMPLETED",
    "statW": "WAITING",
    "statX": "OTHER",
    "statDE": "CANCELLED",
    "statD": "FAILED",
    "statEX": "ABNORMAL",
    "statT": "TIMEOUT",
    "statN": "NODE_ERROR",
    "statRQ": "REQUEUED",
}
TERMINAL_STATES = {
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "ABNORMAL",
    "TIMEOUT",
    "NODE_ERROR",
}


def default_region():
    explicit = env("SCNET_HASHCAT_REGION") or env("SCNET_OPENAPI_REGION_ID")
    if explicit:
        return explicit
    root = Path(env("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    for app in ("scnet-hashcat", "scnet-hpc"):
        try:
            data = json.loads((root / app / "config.json").read_text(encoding="utf-8"))
            value = (data.get("openapi") or {}).get("default_region_id")
            if value:
                return str(value)
        except (OSError, ValueError, AttributeError):
            continue
    return None


class ClientError(Exception):
    """Any failure that should surface as a non-zero exit with a message."""


# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def canonical_signature(
    access_key: str, timestamp: str, user: str, secret_key: str
) -> str:
    message = json.dumps(
        {"accessKey": access_key, "timestamp": timestamp, "user": user},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hmac.new(
        secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def service_endpoint(base_url: str, service: str, suffix: str) -> str:
    split = urlsplit(base_url.rstrip("/"))
    path = split.path.rstrip("/")
    service_part = f"/{service}"
    if not path.endswith(service_part):
        path += service_part
    path += "/" + suffix.lstrip("/")
    return urlunsplit((split.scheme, split.netloc, path, "", ""))


class Client:
    """Authenticated OpenAPI client with token/region caching."""

    def __init__(self, timeout: int = 60):
        self.timeout = timeout
        self._regions_cache: list[dict[str, Any]] | None = None
        self._center_cache: dict[str, dict[str, Any]] = {}

    # -- low level ---------------------------------------------------------

    def request(
        self,
        method: str,
        url: str,
        *,
        token: str | None = None,
        json_body: Any | None = None,
        form: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        request_headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if headers:
            request_headers.update(headers)
        if token:
            request_headers["token"] = token
        data: bytes | None = None
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        elif form is not None:
            data = urlencode(form).encode("utf-8")
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = Request(url, data=data, method=method, headers=request_headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise ClientError(f"HTTP {exc.code} from SCNet OpenAPI: {detail[:500]}")
        except (URLError, TimeoutError, OSError) as exc:
            raise ClientError(f"SCNet OpenAPI request failed: {exc}")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ClientError("SCNet OpenAPI returned a non-JSON response")
        if not isinstance(payload, dict):
            raise ClientError("SCNet OpenAPI response must be a JSON object")
        code = str(payload.get("code", ""))
        if code != "0":
            raise ClientError(
                f"SCNet OpenAPI error {code}: {payload.get('msg') or 'unknown error'}"
            )
        return payload.get("data")

    def request_raw(self, method: str, url: str, **kwargs: Any) -> tuple[bytes, str]:
        """Like request() but returns raw bytes plus content-type (downloads)."""
        token = kwargs.pop("token", None)
        request_headers = {"Accept": "*/*", "User-Agent": USER_AGENT}
        if token:
            request_headers["token"] = token
        request = Request(url, method=method, headers=request_headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return response.read(), response.headers.get("Content-Type", "")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise ClientError(f"HTTP {exc.code} from SCNet OpenAPI: {detail[:500]}")
        except (URLError, TimeoutError, OSError) as exc:
            raise ClientError(f"SCNet OpenAPI request failed: {exc}")

    def multipart(
        self,
        url: str,
        token: str,
        fields: Mapping[str, Any],
        file_name: str,
        file_bytes: bytes,
        content_type: str = "application/octet-stream",
    ) -> Any:
        boundary = "----scnet-hashcat-" + uuid.uuid4().hex
        parts: list[bytes] = []
        for name, value in fields.items():
            parts.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode("utf-8")
            )
        safe_name = file_name.replace('"', "_").replace("\r", "_").replace("\n", "_")
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
            + file_bytes
            + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode("ascii"))
        request = Request(
            url,
            data=b"".join(parts),
            method="POST",
            headers={
                "token": token,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
            raise ClientError(f"OpenAPI multipart upload failed: {exc}")
        if not isinstance(payload, dict):
            raise ClientError("OpenAPI multipart response must be a JSON object")
        if str(payload.get("code", "")) != "0":
            raise ClientError(
                f"SCNet OpenAPI error {payload.get('code')}: {payload.get('msg')}"
            )
        return payload.get("data")

    # -- credentials -------------------------------------------------------

    def _credentials(self) -> dict[str, str]:
        try:
            credentials, _ = load_openapi_credentials()
        except CredentialError as exc:
            raise ClientError(str(exc)) from None
        if not credentials:
            raise ClientError("OpenAPI credentials missing; configure scnet-hpc or inject USER/ACCESS_KEY/SECRET_KEY environment variables. Never put secrets in config.json.")
        return credentials

    # -- token / region cache (shared with scnet-hpc on purpose) -----------

    @staticmethod
    def _token_cache_paths() -> tuple[Path, Path]:
        root = Path(env("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "scnet-hpc"
        return root / "openapi-regions.json", root / "openapi-regions.lock"

    @staticmethod
    def _credential_fingerprint(user: str, access_key: str, secret_key: str) -> str:
        value = "\0".join((user, access_key, secret_key)).encode("utf-8")
        return hashlib.sha256(value).hexdigest()

    @classmethod
    def _read_token_cache(cls, fingerprint: str) -> list[dict[str, Any]] | None:
        path, _ = cls._token_cache_paths()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                payload.get("fingerprint") != fingerprint
                or time.time() - float(payload.get("created_at", 0)) > TOKEN_CACHE_TTL
                or not isinstance(payload.get("regions"), list)
            ):
                return None
            return [item for item in payload["regions"] if isinstance(item, dict)]
        except (OSError, TypeError, ValueError):
            return None

    @classmethod
    def _write_token_cache(
        cls, fingerprint: str, regions: list[dict[str, Any]]
    ) -> bool:
        path, _ = cls._token_cache_paths()
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            temporary.write_text(
                json.dumps(
                    {
                        "created_at": time.time(),
                        "fingerprint": fingerprint,
                        "regions": regions,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
            return True
        except OSError:
            try:
                temporary.unlink()
            except OSError:
                pass
            return False

    @classmethod
    def _acquire_lock(cls) -> Path | None:
        _, lock = cls._token_cache_paths()
        try:
            lock.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        except OSError:
            return None
        for _ in range(50):
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
                return lock
            except FileExistsError:
                try:
                    if time.time() - lock.stat().st_mtime > 30:
                        lock.unlink()
                        continue
                except OSError:
                    pass
                time.sleep(0.2)
            except OSError:
                return None
        return None

    @staticmethod
    def _release_lock(lock: Path | None) -> None:
        if lock is not None:
            try:
                lock.unlink()
            except OSError:
                pass

    # -- regions / center ---------------------------------------------------

    def regions(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        if self._regions_cache is not None and not refresh:
            return self._regions_cache
        direct_token = env("SCNET_OPENAPI_TOKEN")
        if direct_token:
            region_id = default_region() or ""
            self._regions_cache = [
                {
                    "clusterId": region_id,
                    "clusterName": env("SCNET_OPENAPI_REGION_NAME", "configured"),
                    "token": direct_token,
                }
            ]
            return self._regions_cache

        credentials = self._credentials()
        fingerprint = self._credential_fingerprint(**credentials)
        if not refresh:
            cached = self._read_token_cache(fingerprint)
            if cached:
                self._regions_cache = cached
                return cached
        lock = self._acquire_lock()
        try:
            if not refresh:
                cached = self._read_token_cache(fingerprint)
                if cached:
                    self._regions_cache = cached
                    return cached
            timestamp = str(int(time.time()))
            signature = canonical_signature(
                credentials["access_key"],
                timestamp,
                credentials["user"],
                credentials["secret_key"],
            )
            auth_base = env("SCNET_OPENAPI_AUTH_BASE", DEFAULT_AUTH_BASE)
            data = self.request(
                "POST",
                auth_base.rstrip("/") + "/api/user/v3/tokens",
                headers={
                    "user": credentials["user"],
                    "accessKey": credentials["access_key"],
                    "signature": signature,
                    "timestamp": timestamp,
                },
            )
            if not isinstance(data, list):
                raise ClientError("token endpoint returned an unexpected data shape")
            self._regions_cache = [item for item in data if isinstance(item, dict)]
            if lock is not None:
                self._write_token_cache(fingerprint, self._regions_cache)
            return self._regions_cache
        finally:
            self._release_lock(lock)

    def select_region(self, requested: str | None) -> dict[str, Any]:
        usable = [
            item
            for item in self.regions()
            if str(item.get("clusterId", "")) != "0" and item.get("token")
        ]
        if requested:
            for item in usable:
                if str(item.get("clusterId")) == str(requested) or item.get(
                    "clusterName"
                ) == requested:
                    return item
            raise ClientError(f"OpenAPI region {requested!r} is not available")
        if len(usable) == 1:
            return usable[0]
        names = ", ".join(
            f"{item.get('clusterName')}({item.get('clusterId')})" for item in usable
        )
        raise ClientError(
            "multiple OpenAPI regions are available; select one with "
            f"--region or SCNET_OPENAPI_REGION_ID: {names}"
        )

    def center(self, requested: str | None) -> tuple[dict[str, Any], str, dict[str, Any]]:
        region = self.select_region(requested)
        region_id = str(region.get("clusterId", ""))
        token = str(region["token"])
        if region_id not in self._center_cache:
            center_url = env("SCNET_OPENAPI_CENTER_URL", DEFAULT_CENTER_URL)
            data = self.request("GET", center_url, token=token)
            if not isinstance(data, dict):
                raise ClientError("center endpoint returned an unexpected data shape")
            self._center_cache[region_id] = data
        return self._center_cache[region_id], token, region

    @staticmethod
    def enabled_url(center: Mapping[str, Any], field: str) -> str:
        values = center.get(field)
        if not isinstance(values, list):
            raise ClientError(f"center response has no {field}")
        for item in values:
            if not isinstance(item, dict):
                continue
            enabled = str(item.get("enable", "true")).lower() == "true"
            if enabled and item.get("url"):
                return str(item["url"])
        raise ClientError(f"center response has no enabled URL in {field}")

    def hpc_context(self, region: str | None) -> dict[str, Any]:
        """Resolve hpc url, token, scheduler id, and username for a region."""
        center, token, selected = self.center(region)
        hpc_url = self.enabled_url(center, "hpcUrls")
        schedulers = self.request(
            "GET", service_endpoint(hpc_url, "hpc", "/openapi/v2/cluster"), token=token
        )
        if not isinstance(schedulers, list):
            raise ClientError("cluster endpoint returned an unexpected data shape")
        requested = env("SCNET_OPENAPI_SCHEDULER_ID")
        chosen: Mapping[str, Any] | None = None
        if requested:
            chosen = next(
                (item for item in schedulers if str(item.get("id")) == str(requested)),
                None,
            )
            if chosen is None:
                raise ClientError(f"scheduler {requested!r} is not available")
        elif len(schedulers) == 1:
            chosen = schedulers[0]
        else:
            available = ", ".join(
                f"{item.get('text')}({item.get('id')})" for item in schedulers
            )
            raise ClientError(
                "multiple schedulers are available; set SCNET_OPENAPI_SCHEDULER_ID: "
                + available
            )
        user_info = center.get("clusterUserInfo") or {}
        username = env("SCNET_OPENAPI_USERNAME") or user_info.get("userName")
        if not username:
            raise ClientError("OpenAPI username is missing from center response")
        return {
            "hpc_url": hpc_url,
            "token": token,
            "scheduler_id": str(chosen["id"]),
            "username": str(username),
            "region": selected,
            "center": center,
        }

    def efile_context(self, region: str | None) -> tuple[str, str]:
        center, token, _ = self.center(region)
        return self.enabled_url(center, "efileUrls"), token

    # -- operations ---------------------------------------------------------

    def account(self, region: str | None) -> dict[str, Any]:
        _, token, selected = self.center(region)
        url = env("SCNET_OPENAPI_USER_URL", DEFAULT_USER_URL)
        data = self.request("GET", url, token=token)
        if not isinstance(data, dict):
            raise ClientError("user endpoint returned an unexpected data shape")
        return {
            "user": data.get("userName"),
            "account_name": data.get("accountName"),
            "account_status": data.get("accountStatus"),
            "balance": data.get("accountBalance"),
            "computer_center": data.get("computerCenter"),
            "region_id": selected.get("clusterId"),
            "region_name": selected.get("clusterName"),
            "raw": data,
        }

    def queues(self, region: str | None) -> list[dict[str, Any]]:
        ctx = self.hpc_context(region)
        params = urlencode({"strJobManagerID": ctx["scheduler_id"]})
        url = service_endpoint(
            ctx["hpc_url"],
            "hpc",
            f"/openapi/v2/queuenames/users/{quote(ctx['username'])}?{params}",
        )
        data = self.request("GET", url, token=ctx["token"])
        return [
            {
                "partition": item.get("queueName") or item.get("id"),
                "nodes": item.get("queNodes"),
                "free_nodes": item.get("queFreeNodes"),
                "cpus": item.get("queNcpus"),
                "free_cpus": item.get("queFreeNcpus"),
                "max_cpus_per_node": item.get("queMaxPPN"),
                "max_nodes": item.get("queMaxNodect"),
                "max_walltime": item.get("queMaxWalltime"),
                "max_dcus_per_node": item.get("queMaxDcuPN"),
                "charge_rate": item.get("queChargeRate"),
            }
            for item in (data or [])
            if isinstance(item, dict)
        ]

    def limits(self, region: str | None) -> dict[str, Any]:
        ctx = self.hpc_context(region)
        params = urlencode({"strJobManagerID": ctx["scheduler_id"]})
        data = self.request(
            "GET",
            service_endpoint(
                ctx["hpc_url"], "hpc", f"/openapi/v2/userquotas/userlimit?{params}"
            ),
            token=ctx["token"],
        )
        key_map = {
            "userMaxCpu": "user_max_cpus",
            "userMaxDcu": "user_max_dcus",
            "userMaxGpu": "user_max_gpus",
            "userMaxNode": "user_max_nodes",
            "userMaxMem": "user_max_memory_mb",
            "userMaxSubmitJob": "user_max_submitted_jobs",
            "userMaxRunJob": "user_max_running_jobs",
            "maxWallTime": "remaining_machine_time_seconds",
        }
        if not isinstance(data, dict):
            return {"raw": data}
        return {target: data.get(source) for source, target in key_map.items()}

    def submit(self, options: Mapping[str, Any]) -> dict[str, Any]:
        name = str(options["name"])
        command = str(options["command"])
        work_dir = str(options["work_dir"])
        queue = str(options["queue"])
        if not work_dir.startswith("/"):
            raise ClientError("work directory must be absolute")
        if any(ch in name for ch in "\r\n") or any(ch in queue for ch in "\r\n"):
            raise ClientError("job name and queue must not contain newlines")
        nodes = int(options.get("nodes") or 1)
        cpus = int(options.get("cpus") or 1)
        gpus = int(options.get("gpus") or 0)
        dcus = int(options.get("dcus") or 0)
        walltime = str(options.get("walltime") or "24:00:00")
        stdout = options.get("stdout") or f"{work_dir.rstrip('/')}/std.out.%j"
        stderr = options.get("stderr") or f"{work_dir.rstrip('/')}/std.err.%j"
        ctx = self.hpc_context(options.get("region"))
        job_info = {
            "GAP_CMD_FILE": command,
            "GAP_NNODE": str(nodes),
            "GAP_NODE_STRING": str(options.get("node_string") or ""),
            "GAP_SUBMIT_TYPE": "cmd",
            "GAP_JOB_NAME": name,
            "GAP_WORK_DIR": work_dir,
            "GAP_QUEUE": queue,
            "GAP_NPROC": str(cpus),
            "GAP_PPN": "",
            "GAP_NGPU": str(gpus or ""),
            "GAP_NDCU": str(dcus or ""),
            "GAP_JOB_MEM": str(options.get("memory") or ""),
            "GAP_WALL_TIME": walltime,
            "GAP_EXCLUSIVE": "1" if options.get("exclusive") else "",
            "GAP_APPNAME": "BASE",
            "GAP_MULTI_SUB": "",
            "GAP_STD_OUT_FILE": stdout,
            "GAP_STD_ERR_FILE": stderr,
            "GAP_SCHEDULER_OPT_WEB": "\n".join(options.get("scheduler_options") or []),
            "GAP_CLUSTER_ID": str(ctx["region"].get("clusterId") or ""),
        }
        data = self.request(
            "POST",
            service_endpoint(
                ctx["hpc_url"], "hpc", "/openapi/v2/apptemplates/BASIC/BASE/job"
            ),
            token=ctx["token"],
            json_body={
                "strJobManagerID": ctx["scheduler_id"],
                "mapAppJobInfo": job_info,
            },
        )
        return {"job_id": str(data)}

    def job(self, job_id: str, region: str | None) -> dict[str, Any]:
        ctx = self.hpc_context(region)
        try:
            data = self.request("GET", service_endpoint(ctx["hpc_url"], "hpc", f"/openapi/v2/jobs/{quote(job_id)}"), token=ctx["token"])
        except ClientError as exc:
            if not any(s in str(exc).lower() for s in ("404", "not found", "does not exist", "不存在", "unexpected data shape")):
                raise
            data = None
        item = data if isinstance(data, dict) else {}
        state = item.get("jobStatus") or item.get("jobState") or item.get("state")
        finalizing = False
        source = "realtime"
        if not item.get("jobId") or state in ("statC", "COMPLETED"):
            end = datetime.now(timezone(timedelta(hours=8)))
            params = {"strClusterNameList": ctx["scheduler_id"], "timeType": "CUSTOM",
                      "isQueryByQueueTime": "false", "start": 0, "limit": 1, "jobId": job_id,
                      "startTime": (end - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S"),
                      "endTime": end.strftime("%Y-%m-%d %H:%M:%S")}
            history = self.request("GET", service_endpoint(ctx["hpc_url"], "hpc", "/openapi/v2/historyjobs") + "?" + urlencode(params), token=ctx["token"])
            rows = (history.get("items") or history.get("list") or history.get("rows") or []) if isinstance(history, dict) else (history or [])
            match = next((row for row in rows if str(row.get("jobId") or row.get("job_id")) == job_id), None)
            if match:
                item = {**item, **{k: v for k, v in match.items() if v is not None and v != ""}}
                source = "history"
            elif state in ("statC", "COMPLETED"):
                finalizing = True
            elif not item:
                raise ClientError("job not found in realtime or recent accounting history")
        raw_state = (
            item.get("jobStatus") or item.get("jobState") or item.get("state") or ""
        )
        return {
            "job_id": str(item.get("jobId") or item.get("job_id") or job_id),
            "name": item.get("jobName") or item.get("name"),
            "state": "FINALIZING" if finalizing else STATUS_MAP.get(str(raw_state), raw_state),
            "source": source,
            "raw_state": raw_state,
            "queue": item.get("queue") or item.get("queueName"),
            "nodes": item.get("nodeNumReq") or item.get("nodeUsed") or item.get("nodeNum") or item.get("nodect"),
            "cpus": item.get("procNumReq") or item.get("procNumUsed") or item.get("nproc") or item.get("jobProcNum"),
            "dcus": item.get("dcuNumReq") or item.get("dcuNumUsed"),
            "elapsed": item.get("jobRunTime") or item.get("jobWalltimeUsed"),
            "started_at": item.get("jobStartTime"),
            "ended_at": item.get("jobEndTime"),
            "exit_code": item.get("exitCode"),
            "platform_exit_status": item.get("jobExitStatus"),
            "reason": item.get("reason"),
            "work_dir": item.get("workDir") or item.get("workdir"),
            "stdout": item.get("outputPath"),
            "stderr": item.get("errorPath"),
            "raw": item,
        }

    def wait(self, job_id: str, region: str | None, interval: int, timeout: int) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last: dict[str, Any] = {}
        while True:
            last = self.job(job_id, region)
            if last["state"] in TERMINAL_STATES:
                return last
            if time.monotonic() >= deadline:
                raise ClientError(
                    f"job {job_id} still {last['state']} after {timeout}s"
                )
            time.sleep(interval)

    def cancel(self, job_id: str, region: str | None) -> dict[str, Any]:
        ctx = self.hpc_context(region)
        data = self.request(
            "DELETE",
            service_endpoint(ctx["hpc_url"], "hpc", "/openapi/v2/jobs"),
            token=ctx["token"],
            form={
                "jobMethod": env("SCNET_OPENAPI_CANCEL_METHOD", "5"),
                "strJobInfoMap": f"{ctx['scheduler_id']},{ctx['username']}:{job_id}:",
            },
        )
        return {"job_id": job_id, "cancelled": True, "result": data}

    def logs(
        self,
        path: str,
        region: str | None,
        lines: int = 200,
        page: int = 1,
        direction: str = "tail",
    ) -> dict[str, Any]:
        if not path.startswith("/"):
            raise ClientError("log path must be absolute")
        ctx = self.hpc_context(region)
        data = self.request(
            "POST",
            service_endpoint(ctx["hpc_url"], "hpc", "/openapi/v2/file/content"),
            token=ctx["token"],
            form={
                "hostName": "",
                "dirPath": path,
                "triggerNum": page,
                "rollDirection": "UP" if direction == "tail" else "DOWN",
            },
        )
        if not isinstance(data, dict):
            raise ClientError("log endpoint returned an unexpected data shape")
        result_lines = str(data.get("data") or "").splitlines()
        if direction == "tail":
            result_lines = result_lines[-lines:]
        else:
            result_lines = result_lines[:lines]
        return {
            "path": path,
            "total_pages": data.get("totalTriggerTimes"),
            "total_lines": data.get("allLineTotal"),
            "lines": result_lines,
        }

    # -- efile --------------------------------------------------------------

    def mkdir(self, path: str, region: str | None, parents: bool = True) -> dict[str, Any]:
        if not path.startswith("/") or any(ch in path for ch in "\r\n\x00"):
            raise ClientError("directory path must be a safe absolute path")
        efile_url, token = self.efile_context(region)
        url = (
            service_endpoint(efile_url, "efile", "/openapi/v2/file/mkdir")
            + "?"
            + urlencode(
                {
                    "path": path,
                    "createParents": "true" if parents else "false",
                }
            )
        )
        try:
            self.request("POST", url, token=token, json_body={})
        except ClientError as exc:
            # 911021 = "File already exists"; mkdir is idempotent for our use.
            if "911021" not in str(exc) and "already exists" not in str(exc).lower():
                raise
        return {"path": path, "created": True}

    def ls(self, path: str | None, region: str | None, limit: int = 200) -> dict[str, Any]:
        efile_url, token = self.efile_context(region)
        params: dict[str, Any] = {"start": 0, "limit": limit, "order": "asc", "orderBy": "name"}
        if path:
            params["path"] = path
        files = []
        while True:
            data = self.request("GET", service_endpoint(efile_url, "efile", "/openapi/v2/file/list") + "?" + urlencode(params), token=token)
            if not isinstance(data, dict):
                raise ClientError("file listing returned an unexpected data shape")
            batch = data.get("fileList") or []
            files.extend(batch)
            total = data.get("total")
            if not batch or (total is not None and len(files) >= int(total)) or (total is None and len(batch) < limit):
                break
            params["start"] = len(files)
        return {
            "path": data.get("path"),
            "total": data.get("total"),
            "files": [
                {
                    "name": item.get("name"),
                    "path": item.get("path"),
                    "size": item.get("size"),
                    "directory": item.get("isDirectory"),
                    "modified_at": item.get("lastModifiedTime"),
                    "permission": item.get("permission"),
                }
                for item in files
                if isinstance(item, dict)
            ],
        }

    def upload(
        self,
        local_path: str,
        remote_dir: str,
        region: str | None,
        cover: bool = False,
        chunk_size: int = 0,
    ) -> dict[str, Any]:
        local = Path(local_path).expanduser()
        if not local.is_file():
            raise ClientError(f"local file does not exist: {local}")
        if not remote_dir.startswith("/") or any(
            ch in remote_dir for ch in "\r\n\x00"
        ):
            raise ClientError("remote upload directory must be absolute")
        if chunk_size and chunk_size < 1024 * 1024:
            raise ClientError("chunk size must be at least 1 MiB or 0")
        if chunk_size and local.stat().st_size > chunk_size:
            return self._chunked_upload(local, remote_dir, region, cover, chunk_size)
        efile_url, token = self.efile_context(region)
        self.multipart(
            service_endpoint(efile_url, "efile", "/openapi/v2/file/upload"),
            token,
            {"cover": "cover" if cover else "uncover", "path": remote_dir},
            local.name,
            local.read_bytes(),
        )
        return {
            "local_path": str(local),
            "remote_dir": remote_dir,
            "remote_filename": local.name,
        }

    def _chunked_upload(
        self, local: Path, remote_dir: str, region: str | None, cover: bool, chunk_size: int
    ) -> dict[str, Any]:
        efile_url, token = self.efile_context(region)
        total_size = local.stat().st_size
        total_chunks = max(1, (total_size + chunk_size - 1) // chunk_size)
        filename = local.name
        cover_flag = "cover" if cover else "uncover"
        identifier = f"{total_size}-{filename}"
        endpoint = service_endpoint(efile_url, "efile", "/openapi/v2/file/burst")
        with local.open("rb") as stream:
            for chunk_number in range(1, total_chunks + 1):
                chunk = stream.read(chunk_size)
                if not chunk:
                    break
                self.multipart(
                    endpoint,
                    token,
                    {
                        "chunkNumber": chunk_number,
                        "cover": cover_flag,
                        "filename": filename,
                        "identifier": identifier,
                        "path": remote_dir,
                        "relativePath": filename,
                        "totalChunks": total_chunks,
                        "totalSize": total_size,
                        "chunkSize": chunk_size,
                        "currentChunkSize": len(chunk),
                    },
                    filename,
                    chunk,
                )
        self.request(
            "POST",
            service_endpoint(efile_url, "efile", "/openapi/v2/file/merge"),
            token=token,
            form={
                "cover": cover_flag,
                "filename": filename,
                "id": "",
                "identifier": identifier,
                "path": remote_dir,
                "relativePath": filename,
            },
        )
        return {
            "local_path": str(local),
            "remote_dir": remote_dir,
            "remote_filename": filename,
            "bytes": total_size,
            "chunks": total_chunks,
        }

    def download(
        self, remote_path: str, local_path: str, region: str | None, cover: bool = False
    ) -> dict[str, Any]:
        if not remote_path.startswith("/") or any(
            ch in remote_path for ch in "\r\n\x00"
        ):
            raise ClientError("remote download path must be absolute")
        local = Path(local_path).expanduser()
        if local.exists() and not cover:
            raise ClientError(f"local path already exists: {local}")
        efile_url, token = self.efile_context(region)
        url = (
            service_endpoint(efile_url, "efile", "/openapi/v2/file/download")
            + "?"
            + urlencode({"path": remote_path})
        )
        content, content_type = self.request_raw("GET", url, token=token)
        if "application/json" in content_type:
            try:
                payload = json.loads(content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict) and str(payload.get("code", "0")) != "0":
                raise ClientError(
                    f"SCNet OpenAPI error {payload.get('code')}: {payload.get('msg')}"
                )
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(content)
        return {"remote_path": remote_path, "local_path": str(local), "bytes": len(content)}

    def remove(self, paths: list[str], region: str | None) -> dict[str, Any]:
        """Delete remote files. The efile remove endpoint takes a `paths` query param."""
        for path in paths:
            if not path.startswith("/") or any(ch in path for ch in "\r\n\x00"):
                raise ClientError(f"remote path must be a safe absolute path: {path}")
        efile_url, token = self.efile_context(region)
        url = (
            service_endpoint(efile_url, "efile", "/openapi/v2/file/remove")
            + "?"
            + urlencode({"paths": ",".join(paths)})
        )
        self.request("POST", url, token=token, json_body={})
        return {"removed": paths}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scnet_lite",
        description="Minimal self-contained SCNet OpenAPI client (scnet-hashcat)",
    )
    parser.add_argument("--region", default=default_region())
    parser.add_argument("--timeout", type=int, default=60)
    sub = parser.add_subparsers(dest="op", required=True)

    sub.add_parser("doctor", help="check credentials and region resolution")
    sub.add_parser("account", help="show account, balance, status")
    sub.add_parser("queues", help="list queues/partitions")
    sub.add_parser("limits", help="show user quotas")

    submit = sub.add_parser("submit", help="submit a job")
    submit.add_argument("--name", required=True)
    submit.add_argument("--queue", required=True)
    submit.add_argument("--command", required=True)
    submit.add_argument("--work-dir", required=True)
    submit.add_argument("--nodes", type=int, default=1)
    submit.add_argument("--cpus", type=int, default=1)
    submit.add_argument("--gpus", type=int, default=0)
    submit.add_argument("--dcus", type=int, default=0)
    submit.add_argument("--memory", default="")
    submit.add_argument("--walltime", default="24:00:00")
    submit.add_argument("--stdout", default=None)
    submit.add_argument("--stderr", default=None)
    submit.add_argument("--exclusive", action="store_true")

    job = sub.add_parser("job", help="show one job")
    job.add_argument("job_id")

    wait = sub.add_parser("wait", help="wait for a job to reach a terminal state")
    wait.add_argument("job_id")
    wait.add_argument("--interval", type=int, default=10)
    wait.add_argument("--timeout", type=int, default=3600)

    cancel = sub.add_parser("cancel", help="cancel a job")
    cancel.add_argument("job_id")

    logs = sub.add_parser("logs", help="read a remote log file")
    logs.add_argument("--path", required=True)
    logs.add_argument("--lines", type=int, default=200)
    logs.add_argument("--page", type=int, default=1)
    logs.add_argument("--direction", choices=["tail", "head"], default="tail")

    mkdir = sub.add_parser("mkdir", help="create a remote directory")
    mkdir.add_argument("path")
    mkdir.add_argument("--no-parents", action="store_true")

    ls = sub.add_parser("ls", help="list a remote directory")
    ls.add_argument("path", nargs="?", default=None)
    ls.add_argument("--limit", type=int, default=200)

    upload = sub.add_parser("upload", help="upload a local file")
    upload.add_argument("local_path")
    upload.add_argument("remote_dir")
    upload.add_argument("--cover", action="store_true")
    upload.add_argument("--chunk-mib", type=int, default=0)

    download = sub.add_parser("download", help="download a remote file")
    download.add_argument("remote_path")
    download.add_argument("local_path")
    download.add_argument("--cover", action="store_true")

    rm = sub.add_parser("rm", help="remove remote files")
    rm.add_argument("paths", nargs="+")

    return parser


def run(client: Client, args: argparse.Namespace) -> Any:
    if args.op == "doctor":
        region = client.select_region(args.region)
        center, _, _ = client.center(args.region)
        user_info = center.get("clusterUserInfo") or {}
        ctx = client.hpc_context(args.region)
        return {
            "ok": True,
            "region_id": region.get("clusterId"),
            "region_name": region.get("clusterName"),
            "username": ctx["username"],
            "home_path": user_info.get("homePath"),
            "scheduler_id": ctx["scheduler_id"],
        }
    if args.op == "account":
        return client.account(args.region)
    if args.op == "queues":
        return {"items": client.queues(args.region)}
    if args.op == "limits":
        return client.limits(args.region)
    if args.op == "submit":
        return client.submit(vars(args))
    if args.op == "job":
        return client.job(args.job_id, args.region)
    if args.op == "wait":
        return client.wait(args.job_id, args.region, args.interval, args.timeout)
    if args.op == "cancel":
        return client.cancel(args.job_id, args.region)
    if args.op == "logs":
        return client.logs(args.path, args.region, args.lines, args.page, args.direction)
    if args.op == "mkdir":
        return client.mkdir(args.path, args.region, parents=not args.no_parents)
    if args.op == "ls":
        return client.ls(args.path, args.region, args.limit)
    if args.op == "upload":
        return client.upload(
            args.local_path,
            args.remote_dir,
            args.region,
            cover=args.cover,
            chunk_size=args.chunk_mib * 1024 * 1024,
        )
    if args.op == "download":
        return client.download(
            args.remote_path, args.local_path, args.region, cover=args.cover
        )
    if args.op == "rm":
        return client.remove(args.paths, args.region)
    raise ClientError(f"unknown command: {args.op}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    client = Client(timeout=args.timeout)
    try:
        payload = run(client, args)
    except ClientError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.op == "wait" and (
        payload.get("state") != "COMPLETED"
        or str(payload.get("exit_code")) not in ("None", "0", "0:0")
        or str(payload.get("platform_exit_status")) not in ("None", "", "0")
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
