"""Watchdog for the SLIK Mobile Telegram bot systemd service.

The script is intended to be run by systemd timer. It checks the local service,
Telegram API reachability, recent timeout bursts, and stuck main process state.
When a recovery condition is detected it restarts ``slik-mobile`` and optionally
notifies the admin chat via Telegram.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import httpx

SERVICE_NAME = os.environ.get("SLIK_SERVICE_NAME", "slik-mobile")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "")
STATE_FILE = Path(os.environ.get("SLIK_HEALTHCHECK_STATE", "/var/lib/slik-mobile/healthcheck-state.json"))
LOG_FILE = Path(os.environ.get("SLIK_HEALTHCHECK_LOG", "/var/log/slik-mobile-healthcheck.log"))
FAILURE_THRESHOLD = int(os.environ.get("SLIK_HEALTHCHECK_FAILURE_THRESHOLD", "3"))
TIMEOUT_SERIES_THRESHOLD = int(os.environ.get("SLIK_HEALTHCHECK_TIMEOUT_SERIES_THRESHOLD", "3"))
TELEGRAM_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
TIMEOUT_RE = re.compile(r"(?:httpx\.)?ConnectTimeout|(?:telegram\.error\.)?TimedOut")

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("slik-mobile-healthcheck")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def run_command(args: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"consecutive_failures": 0}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def service_is_active() -> tuple[bool, str]:
    result = run_command(["systemctl", "is-active", SERVICE_NAME])
    status = result.stdout.strip() or result.stderr.strip() or "unknown"
    return result.returncode == 0 and status == "active", status


def main_pid() -> int | None:
    result = run_command(["systemctl", "show", SERVICE_NAME, "--property=MainPID", "--value"])
    try:
        pid = int(result.stdout.strip())
    except ValueError:
        return None
    return pid or None


def process_state(pid: int | None) -> str:
    if not pid:
        return "missing"
    result = run_command(["ps", "-o", "stat=", "-p", str(pid)])
    if result.returncode != 0:
        return "missing"
    return result.stdout.strip() or "unknown"


def recent_timeout_count() -> int:
    result = run_command(
        ["journalctl", "-u", SERVICE_NAME, "--since", "-3 minutes", "--no-pager"],
        timeout=20,
    )
    text = f"{result.stdout}\n{result.stderr}"
    return len(TIMEOUT_RE.findall(text))


def telegram_api_ok() -> tuple[bool, str]:
    if not BOT_TOKEN:
        return False, "TELEGRAM_BOT_TOKEN is not set"
    try:
        with httpx.Client(timeout=TELEGRAM_TIMEOUT) as client:
            response = client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe")
            response.raise_for_status()
            payload = response.json()
    except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:
        return False, f"Telegram API timeout: {type(exc).__name__}"
    except httpx.HTTPError as exc:
        return False, f"Telegram API HTTP error: {type(exc).__name__}: {exc}"
    except ValueError as exc:
        return False, f"Telegram API invalid JSON: {exc}"
    if not payload.get("ok"):
        return False, f"Telegram API returned ok=false: {payload}"
    return True, "Telegram API getMe ok"


def restart_service(reason: str) -> tuple[bool, str]:
    result = run_command(["systemctl", "restart", SERVICE_NAME], timeout=30)
    output = (result.stdout + result.stderr).strip()
    if result.returncode == 0:
        logger.warning("Restarted %s. reason=%s", SERVICE_NAME, reason)
        return True, output or "restart ok"
    logger.error("Failed to restart %s. reason=%s output=%s", SERVICE_NAME, reason, output)
    return False, output or "restart failed"


def notify_admin(reason: str, timestamp: str) -> None:
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        logger.info("Admin recovery notification skipped: token or chat id is missing")
        return
    text = (
        "⚠️ SLIK Mobile Bot Recovery\n\n"
        f"Причина:\n{reason}\n\n"
        "Сервис автоматически перезапущен.\n\n"
        f"Время: {timestamp}"
    )
    try:
        with httpx.Client(timeout=TELEGRAM_TIMEOUT) as client:
            response = client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": ADMIN_CHAT_ID, "text": text},
            )
            response.raise_for_status()
        logger.info("Admin recovery notification sent")
    except httpx.HTTPError as exc:
        logger.warning("Failed to send admin recovery notification: %s", exc)


def main() -> int:
    timestamp = utc_now()
    state = load_state()
    active, service_status = service_is_active()
    pid = main_pid()
    proc_state = process_state(pid)
    timeout_count = recent_timeout_count()
    api_ok, api_state = telegram_api_ok()

    reasons: list[str] = []
    if not active:
        reasons.append(f"service is not active: {service_status}")
    if proc_state.startswith(("D", "Z")) or proc_state == "missing":
        reasons.append(f"stuck or missing process: pid={pid}, state={proc_state}")
    if not api_ok:
        reasons.append(api_state)
    if timeout_count >= TIMEOUT_SERIES_THRESHOLD:
        reasons.append(f"timeout burst in journal: {timeout_count} timeout entries")

    if reasons:
        state["consecutive_failures"] = int(state.get("consecutive_failures", 0)) + 1
    else:
        state["consecutive_failures"] = 0
    state.update({
        "checked_at": timestamp,
        "service_active": active,
        "service_status": service_status,
        "main_pid": pid,
        "process_state": proc_state,
        "telegram_api_state": api_state,
        "recent_timeout_count": timeout_count,
    })
    save_state(state)

    logger.info(
        "healthcheck service=%s active=%s pid=%s process_state=%s api=%s failures=%s timeouts=%s",
        SERVICE_NAME,
        active,
        pid,
        proc_state,
        api_state,
        state["consecutive_failures"],
        timeout_count,
    )

    if reasons and int(state["consecutive_failures"]) >= FAILURE_THRESHOLD:
        reason = "; ".join(reasons) + f"; consecutive failures={state['consecutive_failures']}"
        restarted, restart_output = restart_service(reason)
        state["last_restart_at"] = timestamp
        state["last_restart_reason"] = reason
        state["last_restart_output"] = restart_output
        state["consecutive_failures"] = 0 if restarted else state["consecutive_failures"]
        save_state(state)
        if restarted:
            notify_admin(reason, timestamp)
            return 0
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
