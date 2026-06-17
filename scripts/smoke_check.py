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


def function_block(text: str, name: str) -> str:
    pattern = rf"^(async\s+def|def)\s+{re.escape(name)}\s*\(.*?\n(?=^(?:async\s+def|def)\s+|^# ───|\Z)"
    match = re.search(pattern, text, re.DOTALL | re.MULTILINE)
    return match.group(0) if match else ""


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


def check_bot_contract(bot_text: str, env_example_text: str) -> None:
    identifiers = [
        "buy_esim",
        "profile",
        "profile_orders",
        "profile_invite",
        "profile_bonuses",
        "admin_panel",
        "admin_business_sections",
        "admin_payment_sections",
        "admin_service_sections",
        "admin_orders",
        "admin_analytics",
        "admin_clients",
        "admin_news",
        "admin_payments",
        "admin_usd_rub",
        "admin_notification_chats",
        "notification_chats_help",
        "notification_chat:",
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
        "def admin_business_sections_keyboard",
        "def admin_payment_sections_keyboard",
        "def admin_service_sections_keyboard",
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
        "async def show_admin_business_sections(",
        "async def show_admin_payment_sections(",
        "async def show_admin_service_sections(",
        "async def show_admin_orders(",
        "async def show_admin_clients(",
        "async def show_admin_payments(",
        "async def handle_callback(",
        "async def choose_payment(",
        "async def show_existing_checkout_payment(",
        "async def abandoned_checkout_reminder_job(",
        "async def esim_expiry_reminder_job(",
        "async def notify_admin(",
        "async def cmd_chatid(",
        "def notification_chats_admin_text(",
        "def notification_chats_keyboard(",
        "def notification_chats_help_text(",
        "def notification_chats_help_keyboard(",
        "def get_notification_chat_id(",
        "def get_orders_chat_id(",
        "def get_client_activity_chat_id(",
        "def get_new_clients_chat_id(",
        "def get_payments_chat_id(",
        "def get_tech_alerts_chat_id(",
        "def notification_routes_text(",
        "async def cmd_notification_routes(",
        "def main(",
    ]
    for handler in handlers:
        check_contains(bot_text, handler, "bot/bot.py menu/handler functions")


    for needle in [
        '"notification_chats"',
        'ORDERS_CHAT_ID',
        'CLIENT_ACTIVITY_CHAT_ID',
        'NEW_CLIENTS_CHAT_ID',
        'PAYMENTS_CHAT_ID',
        'TECH_ALERTS_CHAT_ID',
        'CommandHandler("chatid",          cmd_chatid)',
        'get_client_activity_chat_id()',
        'get_new_clients_chat_id()',
        'get_orders_chat_id()',
        'notification_chats_help',
        '/chatid',
        '/notification_routes',
        'CommandHandler("notification_routes", cmd_notification_routes)',
    ]:
        check_contains(bot_text, needle, "bot/bot.py notification chats")

    record(
        "notification_chats_help callback renders instruction",
        bool(re.search(r'data == "notification_chats_help".*?notification_chats_help_text\(\)', bot_text, re.DOTALL)),
    )
    record(
        "notification_chats_help instruction mentions /chatid",
        bool(re.search(r"def notification_chats_help_text\(\).*?/chatid", bot_text, re.DOTALL)),
    )


    admin_prefix_match = re.search(r"admin_prefixes\s*=\s*\((.*?)\)", bot_text, re.DOTALL)
    admin_prefix_text = admin_prefix_match.group(1) if admin_prefix_match else ""
    for prefix in [
        '"admin_"',
        '"notification_chat:"',
        '"notification_chat_edit:"',
        '"notification_chat_test:"',
        '"notification_chat_clear:"',
        '"notification_chats_help"',
    ]:
        check_contains(admin_prefix_text, prefix, "bot/bot.py admin_prefixes notification gate")

    record(
        "notification_chats_help passes admin gate",
        '"notification_chats_help"' in admin_prefix_text or '"admin_notification_chats_help"' in bot_text,
    )

    track_action_text = function_block(bot_text, "track_action")
    notify_admin_text = function_block(bot_text, "notify_admin")
    send_admin_order_message_text = function_block(bot_text, "send_admin_order_message")

    record(
        "track_action uses get_client_activity_chat_id",
        "get_client_activity_chat_id()" in track_action_text,
    )
    record(
        "track_action logs client activity route",
        "type=client_activity" in track_action_text and "source=%s" in track_action_text,
    )
    record(
        "notify_admin/order notifications use get_orders_chat_id",
        "get_orders_chat_id()" in notify_admin_text,
    )
    record(
        "notify_admin/order notifications log orders route",
        "type=orders" in notify_admin_text and "source=%s" in notify_admin_text,
    )
    record(
        "send_admin_order_message does not call get_admin_chat_id",
        "get_admin_chat_id(" not in send_admin_order_message_text,
    )
    record(
        "new order notification is sent through notify_admin",
        "await notify_admin(context, order)" in bot_text,
    )
    record(
        "notify_admin does not route orders through get_admin_chat_id directly",
        "get_admin_chat_id(" not in notify_admin_text,
    )
    record(
        "track_action does not route client activity through ADMIN_CHAT_ID directly",
        "get_admin_chat_id(" not in track_action_text and "ADMIN_CHAT_ID" not in track_action_text,
    )
    record(
        "new client notification uses get_new_clients_chat_id",
        bool(re.search(r"async def notify_new_client\(.*?get_new_clients_chat_id\(\)", bot_text, re.DOTALL)),
    )
    record(
        "new client notification text exists",
        "🆕 <b>Новый клиент</b>" in bot_text,
    )
    record(
        "user profile tracks new_client_notified",
        '"new_client_notified": False' in bot_text and 'profile["new_client_notified"] = True' in bot_text,
    )
    record(
        "start distinguishes new and existing users",
        bool(re.search(
            r"async def start\(.*?is_new_client\s*=\s*str\(user\.id\) not in users_before_start.*?if is_new_client:.*?notify_new_client\(.*?else:.*?track_action\(context, user, \"открыл бот\"",
            bot_text,
            re.DOTALL,
        )),
    )


    record(
        "cashback feature flag env exists",
        "CASHBACK_ENABLED" in bot_text or "CASHBACK_ENABLED" in env_example_text,
    )
    record(
        "is_cashback_enabled helper exists",
        "def is_cashback_enabled()" in bot_text,
    )
    record(
        "award_cashback_if_needed checks is_cashback_enabled before awarding",
        bool(re.search(r"def\s+award_cashback_if_needed\(.*?if\s+not\s+is_cashback_enabled\(\).*?credit_slik_balance", bot_text, re.DOTALL)),
    )
    record(
        "notify_cashback_awarded only called after positive cashback",
        bool(re.search(r"if\s+cashback_amount\s*>\s*0\s*:\s*\n\s*await\s+notify_cashback_awarded", bot_text)),
    )
    record(
        "USD/RUB fallback env exists",
        "USD_RUB_FALLBACK_RATE" in bot_text and "USD_RUB_FALLBACK_RATE" in env_example_text,
    )
    record(
        "USD/RUB markup env exists",
        "USD_RUB_MARKUP_PERCENT" in bot_text and "USD_RUB_MARKUP_PERCENT" in env_example_text,
    )
    record(
        "USD/RUB min/max env exists",
        all(token in bot_text and token in env_example_text for token in ("USD_RUB_MIN_RATE", "USD_RUB_MAX_RATE")),
    )
    record(
        "normalize_rate rejects invalid 30 RUB rate",
        "USD_RUB_MIN_RATE <= rate <= USD_RUB_MAX_RATE" in function_block(bot_text, "normalize_rate")
        and "30 <= rate <= 200" not in function_block(bot_text, "normalize_rate"),
    )
    providers_text = function_block(bot_text, "usd_rub_source_providers")
    collect_text = function_block(bot_text, "collect_usd_rub_source_rates")
    calculate_text = function_block(bot_text, "calculate_usd_rub_market_rate")
    get_rate_text = function_block(bot_text, "get_usd_rub_rate")
    check_market_text = function_block(bot_text, "check_market_usd_rub_rate")
    extract_text = function_block(bot_text, "extract_rate_from_text")
    record(
        "normalize_rate accepts realistic 78.25 RUB rate",
        "USD_RUB_MIN_RATE <= rate <= USD_RUB_MAX_RATE" in function_block(bot_text, "normalize_rate")
        and "USD_RUB_MIN_RATE" in bot_text and "USD_RUB_MAX_RATE" in bot_text,
    )
    record(
        "Yandex parser is not the only mandatory USD/RUB source",
        all(source in providers_text for source in ("ЦБ РФ", "open.er-api.com", "exchangerate.host", "Яндекс"))
        and providers_text.find("ЦБ РФ") < providers_text.find("Яндекс"),
    )
    record(
        "market rate collection continues after provider returns None",
        "for source, provider in usd_rub_source_providers()" in collect_text
        and "results.append(item)" in collect_text
        and "returned invalid value" in collect_text,
    )
    record(
        "multiple valid USD/RUB sources are averaged",
        "len(filtered) >= 2" in calculate_text and "sum(float(item" in calculate_text and "среднее по" in calculate_text,
    )
    record(
        "invalid 30 source does not participate in average",
        "rate = normalize_rate(raw_rate)" in collect_text and "if rate is not None:" in collect_text,
    )
    record(
        "USD/RUB outlier is rejected when three or more sources are valid",
        "len(valid) >= 3" in calculate_text
        and "USD_RUB_MAX_SOURCE_DEVIATION_PERCENT" in calculate_text
        and "отклонение" in calculate_text,
    )
    record(
        "single valid USD/RUB source is used with warning method",
        "len(filtered) == 1" in calculate_text and "один источник" in calculate_text,
    )
    record(
        "USD/RUB fallback only after all providers fail",
        calculate_text.rfind('return USD_RUB_FALLBACK_RATE, "fallback"') > calculate_text.rfind("len(filtered) == 1"),
    )
    record(
        "Yandex parser does not reject today context by bare дн substring",
        "сегодня" not in extract_text and "дн|" not in extract_text and "\\bдн" in extract_text,
    )
    record(
        "Yandex parser rejects days labels rather than treating 30 days as rate",
        "\\bдней" in extract_text and "\\bдн" in extract_text and "ignored_context.search(context)" in extract_text,
    )
    record(
        "manual USD/RUB rate keeps payment priority",
        "manual_rate = get_manual_usd_rub_rate()" in get_rate_text
        and 'return round(manual_rate, 4), "manual"' in get_rate_text
        and get_rate_text.find("manual_rate = get_manual_usd_rub_rate()") < get_rate_text.find("collect_usd_rub_source_rates"),
    )
    record(
        "USD/RUB markup env parsing is safe",
        "def env_float(" in bot_text and 'USD_RUB_MARKUP_PERCENT = env_float("USD_RUB_MARKUP_PERCENT", 1.5' in bot_text,
    )
    record(
        "USD/RUB markup env is not parsed with bare float at import",
        'USD_RUB_MARKUP_PERCENT = float(os.environ.get("USD_RUB_MARKUP_PERCENT"' not in bot_text,
    )
    record(
        "admin USD/RUB screen exists",
        "💱 Курс USD/RUB" in bot_text and "usd_rub_admin_keyboard" in bot_text,
    )
    admin_panel_keyboard_text = function_block(bot_text, "admin_panel_keyboard")
    record(
        "admin main menu is grouped into business/payment/service sections",
        "📊 Бизнес-разделы" in admin_panel_keyboard_text
        and "💳 Оплата и курс" in admin_panel_keyboard_text
        and "🛠 Сервис" in admin_panel_keyboard_text,
    )
    record(
        "legacy admin section callbacks are still routed",
        all(
            token in bot_text
            for token in (
                '"admin_orders"',
                '"admin_analytics"',
                '"admin_clients"',
                '"admin_news"',
                '"admin_payments"',
                '"admin_usd_rub"',
                '"admin_notification_chats"',
                '"admin_healthcheck"',
                '"admin_backups"',
            )
        ),
    )
    record(
        "USD/RUB settings persist rate check and final rate",
        all(token in bot_text for token in ("rate_checked_at", "markup_percent", "final_usd_rub_rate")),
    )
    create_card_payment_lock_text = function_block(bot_text, "create_card_payment_lock")
    order_payment_details_text = function_block(bot_text, "order_payment_details_from_context")
    record(
        "card payment lock stores rate_checked_at",
        '"rate_checked_at": now_str()' in create_card_payment_lock_text,
    )
    record(
        "order payment_details keeps rate_checked_at",
        '"rate_checked_at": lock.get("rate_checked_at")' in order_payment_details_text,
    )
    handle_callback_text = function_block(bot_text, "handle_callback")
    record(
        "reset manual rate answers callback before external refresh",
        bool(re.search(
            r'elif\s+data\s*==\s*"usd_rub_reset_manual":\s*'
            r'await\s+query\.answer\(.*?\).*?'
            r'save_usd_rub_settings\(manual_rate=None\).*?'
            r'await\s+refresh_usd_rub_rate_check\(\)',
            handle_callback_text,
            re.DOTALL,
        )),
    )
    record(
        "reset markup answers callback before external refresh",
        bool(re.search(
            r'elif\s+data\s*==\s*"usd_rub_reset_markup":\s*'
            r'await\s+query\.answer\(.*?\).*?'
            r'save_usd_rub_settings\(markup_percent=USD_RUB_MARKUP_PERCENT\).*?'
            r'await\s+refresh_usd_rub_rate_check\(\)',
            handle_callback_text,
            re.DOTALL,
        )),
    )

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


def check_run_mvp_contract(run_mvp_text: str) -> None:
    run_mvp_track_action_text = function_block(run_mvp_text, "track_action")
    run_mvp_notify_admin_text = function_block(run_mvp_text, "notify_admin")
    record(
        "run_mvp notify_admin does not call bot.get_admin_chat_id",
        "bot.get_admin_chat_id(" not in run_mvp_notify_admin_text,
    )
    record(
        "run_mvp track_action does not call bot.get_admin_chat_id",
        "bot.get_admin_chat_id(" not in run_mvp_track_action_text,
    )
    record(
        "run_mvp notify_admin uses orders route helper",
        "bot.get_orders_chat_id(" in run_mvp_notify_admin_text
        or "bot.get_orders_chat_source(" in run_mvp_notify_admin_text,
    )
    record(
        "run_mvp track_action uses client activity route helper",
        "bot.get_client_activity_chat_id(" in run_mvp_track_action_text
        or "bot.get_client_activity_chat_source(" in run_mvp_track_action_text,
    )
    record(
        "run_mvp notify_admin includes route diagnostics",
        "Маршрут: orders" in run_mvp_notify_admin_text and "route_source" in run_mvp_notify_admin_text,
    )
    record(
        "run_mvp track_action includes route diagnostics",
        "Маршрут: client_activity" in run_mvp_track_action_text and "route_source" in run_mvp_track_action_text,
    )


def main() -> int:
    check_syntax("bot/bot.py")
    check_syntax("bot/run_mvp.py")
    check_syntax("bot/bot_healthcheck.py")

    bot_text = read_text("bot/bot.py")
    run_mvp_text = read_text("bot/run_mvp.py")
    readme_text = read_text("README.md")
    env_example_text = read_text(".env.example")
    config_example_text = read_text("bot/config.example.json")
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
    check_bot_contract(bot_text, env_example_text)
    check_run_mvp_contract(run_mvp_text)
    for needle in [
        'ORDERS_CHAT_ID',
        'CLIENT_ACTIVITY_CHAT_ID',
        'NEW_CLIENTS_CHAT_ID',
        'PAYMENTS_CHAT_ID',
        'TECH_ALERTS_CHAT_ID',
        'CASHBACK_ENABLED=false',
    ]:
        check_contains(env_example_text, needle, ".env.example notification routing")
    check_contains(config_example_text, '"notification_chats"', "bot/config.example.json")
    check_contains(config_example_text, '"new_clients"', "bot/config.example.json")
    check_contains(readme_text, "Разделение уведомлений по чатам", "README.md")
    check_contains(readme_text, "/notification_routes", "README.md")

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
