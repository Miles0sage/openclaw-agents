#!/usr/bin/env python3
"""OpenClaw CLI wrapper."""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional


class Colors:
    """ANSI output colors."""

    GREEN = "\033[92m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


TERMINAL_STATUSES = {"completed", "success", "done", "failed", "error", "cancelled"}
SUCCESS_STATUSES = {"completed", "success", "done"}


@dataclass(frozen=True)
class Config:
    gateway_url: str
    auth_token: Optional[str]


class CliError(Exception):
    """CLI-level error."""


class HttpError(Exception):
    """HTTP error with status and parsed response payload."""

    def __init__(self, message: str, status: Optional[int] = None, payload: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload


def _config() -> Config:
    gateway_url = os.getenv("OPENCLAW_GATEWAY_URL", "http://localhost:18789").rstrip("/")
    auth_token = os.getenv("OPENCLAW_AUTH_TOKEN")
    return Config(gateway_url=gateway_url, auth_token=auth_token)


def _require_auth_token(config: Config) -> str:
    if not config.auth_token:
        raise CliError("OPENCLAW_AUTH_TOKEN is required for this command")
    return config.auth_token


def _parse_json_or_text(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _request(
    method: str,
    config: Config,
    path: str,
    token: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> Any:
    if not path.startswith("/"):
        path = f"/{path}"
    url = f"{config.gateway_url}{path}"

    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["X-Auth-Token"] = token

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return _parse_json_or_text(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        parsed = _parse_json_or_text(raw)
        message = f"HTTP {exc.code}"
        if isinstance(parsed, dict):
            message = str(
                parsed.get("error")
                or parsed.get("detail")
                or parsed.get("message")
                or message
            )
        raise HttpError(message, status=exc.code, payload=parsed) from exc
    except urllib.error.URLError as exc:
        raise CliError(f"Connection failed: {exc.reason}") from exc


def _as_json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True)


def _extract_job_id(data: Any) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    for key in ("job_id", "id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _extract_status(data: Any) -> str:
    if isinstance(data, dict):
        status = data.get("status")
        if isinstance(status, str):
            return status.lower()
    return "unknown"


def _is_terminal(status: str) -> bool:
    return status.lower() in TERMINAL_STATUSES


def _is_success(status: str) -> bool:
    return status.lower() in SUCCESS_STATUSES


def cmd_health(args: argparse.Namespace, config: Config) -> int:
    data = _request("GET", config, "/health")
    if args.json:
        print(_as_json(data))
        return 0

    status = data.get("status", "unknown") if isinstance(data, dict) else "unknown"
    print(f"{Colors.GREEN}OK{Colors.RESET} Gateway healthy")
    print(f"{Colors.CYAN}Gateway:{Colors.RESET} {config.gateway_url}")
    print(f"{Colors.CYAN}Status:{Colors.RESET} {status}")
    return 0


def cmd_run(args: argparse.Namespace, config: Config) -> int:
    token = _require_auth_token(config)

    if not args.json:
        print(f"{Colors.CYAN}Submitting job...{Colors.RESET}")
    submit_data = _request("POST", config, "/api/jobs", token=token, payload={"prompt": args.prompt})
    job_id = _extract_job_id(submit_data)
    if not job_id:
        raise CliError("API response missing job_id/id")

    if not args.wait:
        if args.json:
            print(_as_json(submit_data))
        else:
            print(f"{Colors.GREEN}Submitted{Colors.RESET} job {Colors.BOLD}{job_id}{Colors.RESET}")
        return 0

    if not args.json:
        print(f"{Colors.CYAN}Waiting for completion (polling every 3s)...{Colors.RESET}")

    final = None
    while True:
        time.sleep(3)
        status_data = _request("GET", config, f"/api/jobs/{job_id}", token=token)
        status = _extract_status(status_data)
        final = status_data
        if not args.json:
            print(f"{Colors.CYAN}Status:{Colors.RESET} {status}")
        if _is_terminal(status):
            break

    if args.json:
        print(_as_json(final))
    else:
        status = _extract_status(final)
        color = Colors.GREEN if _is_success(status) else Colors.RED
        print(f"{color}Final status:{Colors.RESET} {status}")

    return 0 if _is_success(_extract_status(final)) else 1


def cmd_status(args: argparse.Namespace, config: Config) -> int:
    token = _require_auth_token(config)
    data = _request("GET", config, f"/api/jobs/{args.job_id}", token=token)
    status = _extract_status(data)

    if args.json:
        print(_as_json(data))
        return 1 if status in {"failed", "error", "cancelled"} else 0

    job_id = _extract_job_id(data) or args.job_id
    print(f"{Colors.CYAN}Job:{Colors.RESET} {job_id}")
    print(f"{Colors.CYAN}Status:{Colors.RESET} {status}")
    if isinstance(data, dict):
        if "prompt" in data:
            print(f"{Colors.CYAN}Prompt:{Colors.RESET} {data['prompt']}")
        if data.get("error"):
            print(f"{Colors.RED}Error:{Colors.RESET} {data['error']}")
    if status in {"failed", "error", "cancelled"}:
        return 1
    return 0


def cmd_jobs(args: argparse.Namespace, config: Config) -> int:
    token = _require_auth_token(config)
    data = _request("GET", config, f"/api/jobs?limit={args.limit}", token=token)

    if args.json:
        print(_as_json(data))
        return 0

    jobs: list[Any] = []
    if isinstance(data, list):
        jobs = data
    elif isinstance(data, dict):
        if isinstance(data.get("jobs"), list):
            jobs = data["jobs"]
        elif isinstance(data.get("items"), list):
            jobs = data["items"]

    print(f"{Colors.CYAN}Recent jobs:{Colors.RESET} {len(jobs)}")
    if not jobs:
        return 0

    for job in jobs:
        if not isinstance(job, dict):
            continue
        job_id = job.get("job_id") or job.get("id") or "unknown"
        status = str(job.get("status", "unknown"))
        print(f"- {job_id} ({status})")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenClaw CLI")
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--json", action="store_true", help="Print raw JSON output")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health", parents=[shared], help="GET /health")

    run_parser = subparsers.add_parser("run", parents=[shared], help='POST /api/jobs with {"prompt": "..."}')
    run_parser.add_argument("prompt", help="Prompt text")
    run_parser.add_argument("--wait", action="store_true", help="Poll every 3s until completion")

    status_parser = subparsers.add_parser("status", parents=[shared], help="GET /api/jobs/{job_id}")
    status_parser.add_argument("job_id", help="Job ID")

    jobs_parser = subparsers.add_parser("jobs", parents=[shared], help="GET /api/jobs?limit=20")
    jobs_parser.add_argument("--limit", type=int, default=20, help="Result limit (default: 20)")

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    config = _config()

    try:
        if args.command == "health":
            return cmd_health(args, config)
        if args.command == "run":
            return cmd_run(args, config)
        if args.command == "status":
            return cmd_status(args, config)
        if args.command == "jobs":
            return cmd_jobs(args, config)
        raise CliError(f"Unknown command: {args.command}")
    except HttpError as exc:
        if getattr(args, "json", False):
            payload = exc.payload if exc.payload is not None else {"error": str(exc), "status": exc.status}
            print(_as_json(payload))
        else:
            status = f" (HTTP {exc.status})" if exc.status is not None else ""
            print(f"{Colors.RED}Error{status}:{Colors.RESET} {exc}")
        return 1
    except CliError as exc:
        if getattr(args, "json", False):
            print(_as_json({"error": str(exc)}))
        else:
            print(f"{Colors.RED}Error:{Colors.RESET} {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
