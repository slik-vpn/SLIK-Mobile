#!/usr/bin/env python3
"""Read-only smoke diagnostics for SLIK Mobile deploy readiness.

The script intentionally performs only static/read-only checks: it does not import
runtime modules, write JSON files, call Telegram, create invoices, or modify .env.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHECKS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def check_syntax(relative_path: str) -> None:
    path = ROOT / relative_path
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        record(f"syntax {relative_path}", False, f"{exc.msg} at line {exc.lineno}")
    else:
        record(f"syntax {relative_path}", True)


def check_contains(text: str, needle: str, source: str) -> None:
    record(f"{source} contains {needle!r}", needle in text)


def check_not_contains(text: str, needle: str, source: str) -> None:
    record(f"{source} does not contain {needle!r}", needle not in text)


def check_systemd_user_docs(unit_texts: dict[str, str], readme_text: str) -> None:
    uses_slik_user = any(
        re.search(r"^\s*(User|Group)=slik-mobile\s*$", text, re.MULTILINE)
        for text in unit_texts.values()
    )
    explicit_creation_documented = bool(
        re.search(r"\b(useradd|adduser)\b[^\n]*\bslik-mobile\b", readme_text)
        or re.search(r"\bslik-mobile\b[^\n]*\b(useradd|adduser)\b", readme_text)
    )
    record(
        "User=slik-mobile/Group=slik-mobile not used without documented user creation",
        not uses_slik_user or explicit_creation_documented,
        "Document explicit user creation with useradd/adduser before enabling User=/Group=."
        if uses_slik_user and not explicit_creation_documented
        else "",
    )


def check_bot_contract(bot_text: str) -> None:
    identifiers = [
        "buy_esim",
        "profile",
        "profile_orders",
        "profile_invite",
        "profile_bonuses",
        "admin_panel",
        "admin_orders",
        "admin_clients",
        "admin_payments",
        "order_status:",
        "client_card:",
        "client_balance:",
        "pay_card",
        "check_payment_",
        "cancel_order",
        "support",
        "abandoned_continue:",
        "user_order:",
        "repeat_order:",
        "abandoned_reminder_sent",
        "ABANDONED_CHECKOUT_REMINDER_MINUTES",
        "expiry_reminder_sent",
        "ESIM_EXPIRY_REMINDER_DAYS_BEFORE",
    ]
    for identifier in identifiers:
        check_contains(bot_text, identifier, "bot/bot.py callback/data identifiers")

    handlers = [
        "def main_menu_keyboard",
        "def admin_panel_keyboard",
        "async def start(",
        "async def show_buy_esim(",
        "async def show_profile(",
        "async def show_my_orders(",
        "async def show_user_order(",
        "async def repeat_order(",
        "async def show_profile_invite(",
        "async def show_profile_bonuses(",
        "async def show_support_screen(",
        "async def show_admin_panel(",
        "async def show_admin_orders(",
        "async def show_admin_clients(",
        "async def show_admin_payments(",
        "async def handle_callback(",
        "async def choose_payment(",
        "async def show_existing_checkout_payment(",
        "async def abandoned_checkout_reminder_job(",
        "async def esim_expiry_reminder_job(",
        "async def notify_admin(",
        "def main(",
    ]
    for handler in handlers:
        check_contains(bot_text, handler, "bot/bot.py menu/handler functions")

    record(
        "is_revenue_order excludes waiting_payment",
        bool(re.search(
            r"def\s+is_revenue_order\(order: dict\).*?not in\s+\{[^}]*[\"']cancelled[\"'][^}]*[\"']waiting_payment[\"'][^}]*\}",
            bot_text,
            re.DOTALL,
        )),
    )

    reminder_job = re.search(
        r"async def abandoned_checkout_reminder_job\(.*?\n(?=\n\ndef |\n\nasync def |\n\n# ───)",
        bot_text,
        re.DOTALL,
    )
    reminder_job_text = reminder_job.group(0) if reminder_job else ""
    send_message_index = reminder_job_text.find("await context.bot.send_message")
    post_send_text = reminder_job_text[send_message_index:] if send_message_index >= 0 else ""
    record(
        "abandoned reminder updates fresh order after send",
        "mark_abandoned_reminder_sent_if_still_waiting(order_id)" in post_send_text,
    )
    record(
        "abandoned reminder does not save stale snapshot after send",
        "save_orders(" not in post_send_text,
    )
    record(
        "abandoned reminder fresh update helper reloads orders",
        bool(re.search(
            r"def\s+mark_abandoned_reminder_sent_if_still_waiting\(order_id: int\).*?fresh_orders\s*=\s*load_orders\(\).*?save_orders\(fresh_orders\)",
            bot_text,
            re.DOTALL,
        )),
    )

    expiry_job = re.search(
        r"async def esim_expiry_reminder_job\(.*?\n(?=\n\ndef |\n\nasync def |\n\n# ───)",
        bot_text,
        re.DOTALL,
    )
    expiry_job_text = expiry_job.group(0) if expiry_job else ""
    expiry_send_index = expiry_job_text.find("await context.bot.send_message")
    expiry_post_send_text = expiry_job_text[expiry_send_index:] if expiry_send_index >= 0 else ""
    record(
        "expiry reminder job is scheduled",
        "schedule_esim_expiry_reminders(app)" in bot_text
        and 'name="esim_expiry_reminders"' in bot_text,
    )
    record(
        "expiry reminder updates fresh order after send",
        "mark_expiry_reminder_sent_if_still_issued(order_id)" in expiry_post_send_text,
    )
    record(
        "expiry reminder does not save stale snapshot after send",
        bool(expiry_post_send_text) and "save_orders(" not in expiry_post_send_text,
    )
    record(
        "expiry reminder fresh update helper reloads orders",
        bool(re.search(
            r"def\s+mark_expiry_reminder_sent_if_still_issued\(order_id: int\).*?fresh_orders\s*=\s*load_orders\(\).*?save_orders\(fresh_orders\)",
            bot_text,
            re.DOTALL,
        )),
    )


def main() -> int:
    check_syntax("bot/bot.py")
    check_syntax("bot/bot_healthcheck.py")

    bot_text = read_text("bot/bot.py")
    readme_text = read_text("README.md")
    service_text = read_text("deploy/slik-mobile.service")
    healthcheck_text = read_text("deploy/slik-mobile-healthcheck.service")

    check_not_contains(service_text, "/opt/slik-mobile", "deploy/slik-mobile.service")
    check_not_contains(service_text, "/.venv/", "deploy/slik-mobile.service")
    check_contains(service_text, "/opt/SLIK-Mobile", "deploy/slik-mobile.service")
    check_contains(service_text, "/opt/SLIK-Mobile/venv/bin/python", "deploy/slik-mobile.service")
    check_contains(healthcheck_text, "/opt/SLIK-Mobile", "deploy/slik-mobile-healthcheck.service")
    check_contains(healthcheck_text, "/opt/SLIK-Mobile/venv/bin/python", "deploy/slik-mobile-healthcheck.service")
    check_systemd_user_docs(
        {
            "deploy/slik-mobile.service": service_text,
            "deploy/slik-mobile-healthcheck.service": healthcheck_text,
        },
        readme_text,
    )
    check_bot_contract(bot_text)

    failed = [(name, detail) for name, ok, detail in CHECKS if not ok]
    for name, ok, detail in CHECKS:
        status = "PASS" if ok else "FAIL"
        suffix = f" — {detail}" if detail else ""
        print(f"[{status}] {name}{suffix}")

    if failed:
        print(f"\nSmoke check failed: {len(failed)} issue(s).", file=sys.stderr)
        return 1

    print(f"\nSmoke check passed: {len(CHECKS)} check(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
