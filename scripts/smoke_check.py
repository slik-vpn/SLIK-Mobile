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
        "buy_apple_id",
        "apple_id_region:",
        "apple_id_product:",
        "buy_apple_id_product:",
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
        "async def show_apple_id_start(",
        "async def show_apple_id_region(",
        "async def show_apple_id_product(",
        "async def start_apple_id_purchase(",
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

    record(
        "main menu contains Apple ID topup button after eSIM",
        bool(re.search(r"Купить eSIM.*?🍎 Пополнить Apple ID.*?Личный кабинет.*?Поддержка", function_block(bot_text, "main_menu_keyboard"), re.DOTALL)),
    )
    record(
        "Apple ID catalog has USA and Turkey regions",
        "APPLE_ID_PRODUCTS" in bot_text and '"US"' in bot_text and '"TR"' in bot_text
        and "Apple Gift Card USA" in bot_text and "Apple Gift Card Turkey" in bot_text,
    )
    record(
        "Apple ID catalog has USA and Turkey nominal values",
        all(token in bot_text for token in ("apple_us_5", "apple_us_10", "apple_us_100", "apple_tr_100", "apple_tr_1000")),
    )
    record(
        "Apple ID order is created separately from eSIM",
        '"product_type": "apple_id"' in bot_text and '"product_type": "esim"' in bot_text
        and "create_apple_id_checkout_order" in bot_text and "create_checkout_order" in bot_text,
    )
    record(
        "eSIM purchase logic remains present",
        "PLAN_MAP" in bot_text and "start_purchase_for_plan" in bot_text and 'CallbackQueryHandler(start_purchase, pattern=r"^buy_plan_")' in bot_text,
    )
    record(
        "Apple ID runtime catalog helpers exist",
        all(token in bot_text for token in (
            "def get_apple_id_products()",
            "def save_apple_id_products(products",
            "def apple_id_products_by_region",
            "def apple_id_product_by_id(product_id",
        )),
    )
    record(
        "Apple ID user flow uses runtime catalog and hides disabled products",
        "apple_id_products_by_region(region, enabled_only=True)" in bot_text
        and "Сейчас товары этого региона временно недоступны" in bot_text
        and "for product in apple_id_products_by_region(region, enabled_only=True)" in bot_text,
    )
    record(
        "Apple ID admin catalog handlers can edit toggle add and delete",
        all(token in bot_text for token in (
            "admin_apple_id_catalog",
            "admin_apple_id_price:",
            "admin_apple_id_toggle:",
            "admin_apple_id_add:",
            "admin_apple_id_delete_confirm:",
            "APPLE_ID_INPUT_PRICE",
            "APPLE_ID_INPUT_ADD_AMOUNT",
            "APPLE_ID_INPUT_ADD_PRICE",
        )),
    )
    record(
        "Apple ID catalog admin access excludes managers",
        "def has_catalog_admin_access" in bot_text
        and "{ROLE_OWNER, ROLE_ADMIN}" in function_block(bot_text, "has_catalog_admin_access")
        and "Недостаточно прав" in bot_text,
    )
    record(
        "Apple ID payments reuse existing payment flow",
        "start_apple_id_purchase" in bot_text and "enabled_payment_methods()" in function_block(bot_text, "start_apple_id_purchase")
        and ("create_card_payment_lock(plan)" in function_block(bot_text, "start_apple_id_purchase") or "create_card_payment_lock_or_notify(query, plan)" in function_block(bot_text, "start_apple_id_purchase"))
        and "payment_keyboard(product_id)" in function_block(bot_text, "start_apple_id_purchase"),
    )
    record(
        "card payment lock still uses USD/RUB flow",
        "await get_usd_rub_rate()" in function_block(bot_text, "create_card_payment_lock")
        and "CARD_RATE_LOCK_SECONDS" in function_block(bot_text, "create_card_payment_lock"),
    )
    record(
        "cashback remains disabled by default",
        'CASHBACK_ENABLED", "0"' in bot_text or 'CASHBACK_ENABLED", "false"' in bot_text,
    )

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
        "manual_rate = get_manual_usd_rub_rate()" in function_block(bot_text, "get_final_usd_rub_rate")
        and 'return round(manual_rate, 4), "manual"' in function_block(bot_text, "get_final_usd_rub_rate")
        and get_rate_text.strip() == "async def get_usd_rub_rate() -> tuple[float, str]:\n    return get_final_usd_rub_rate()",
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
        and "⚙️ Настройки" in admin_panel_keyboard_text
        and "🛠 Сервис" in admin_panel_keyboard_text,
    )
    service_keyboard_text = function_block(bot_text, "admin_service_sections_keyboard")
    service_text_block = function_block(bot_text, "admin_service_sections_text")
    admin_management_text = function_block(bot_text, "admin_management_text")
    record(
        "service section contains owner-only administrators button",
        "👤 Администраторы" in service_keyboard_text
        and "admin_admins" in service_keyboard_text
        and "has_owner_access(user)" in service_keyboard_text,
    )
    record(
        "administrators screen callback and handlers exist",
        all(token in bot_text for token in (
            "admin_admins_add",
            "admin_admins_change_role",
            "admin_admins_remove",
            "show_admin_admins",
            "ADMIN_MANAGEMENT_INPUT_TELEGRAM_ID",
        )),
    )
    record(
        "administrators management is restricted to OWNER",
        "def has_owner_access(user)" in bot_text
        and 'get_user_role(user) == ROLE_OWNER' in bot_text
        and 'data.startswith(owner_callbacks) and not has_owner_access(query.from_user)' in bot_text
        and "if not has_owner_access(query.from_user)" in function_block(bot_text, "show_admin_admins"),
    )
    record(
        "legacy username admin entries are represented in administrators UI",
        "legacy_username|admins|" in bot_text
        and "legacy_username|managers|" in bot_text
        and "legacy username" in bot_text
        and "remove_admin_access(user_id)" in bot_text,
    )
    record(
        "legacy username role changes show Telegram ID limitation",
        "Для изменения роли legacy username-пользователя" in bot_text
        and 'user_id.startswith("legacy_username|")' in bot_text,
    )
    record(
        "admin management cancel clears pending input",
        "admin_admins_cancel" in bot_text
        and "def clear_admin_management_state(" in bot_text
        and "context.user_data.pop(\"client_input\", None)" in function_block(bot_text, "clear_admin_management_state")
        and "admin_management_" in function_block(bot_text, "clear_admin_management_state"),
    )
    record(
        "role constants keep USER/MANAGER/ADMIN/OWNER names",
        all(token in bot_text for token in (
            'ROLE_USER = "USER"',
            'ROLE_MANAGER = "MANAGER"',
            'ROLE_ADMIN = "ADMIN"',
            'ROLE_OWNER = "OWNER"',
        )),
    )
    record(
        "administrators screen lists MANAGER/ADMIN/OWNER roles",
        all(role in admin_management_text for role in ("OWNER —", "ADMIN —", "MANAGER —"))
        and "list_admin_users()" in admin_management_text,
    )
    record(
        "last OWNER is protected from demotion and removal",
        "count_owner_roles(exclude_user_id=user_id) < 1" in bot_text
        and "Нельзя снять роль с последнего OWNER" in bot_text
        and "Нельзя удалить последнего OWNER" in bot_text,
    )
    record(
        "service text mentions administrators only for owners",
        "👤 Администраторы" in service_text_block and "has_owner_access(user)" in service_text_block,
    )
    record(
        "FazerCards owner-only API settings UI and handlers exist",
        "🔑 FazerCards API" in service_keyboard_text
        and "admin_fazercards_api" in bot_text
        and "FAZERCARDS_INPUT_API_KEY" in bot_text
        and "has_owner_access(query.from_user)" in bot_text,
    )
    record(
        "FazerCards key is masked and full key is not shown by settings screen",
        "def mask_secret" in bot_text
        and "••••••" in function_block(bot_text, "mask_secret")
        and "mask_secret(settings.get('api_key'))" in function_block(bot_text, "fazercards_api_text"),
    )
    record(
        "FazerCards runtime save clear helpers keep auto issue disabled",
        all(token in bot_text for token in (
            "def get_fazercards_settings()",
            "def save_fazercards_api_key(api_key",
            "def clear_fazercards_api_key()",
            '"auto_issue_enabled": False',
        )),
    )
    record(
        "FazerCards connection check callback and helper exist",
        "🔍 Проверить подключение" in bot_text
        and "admin_fazercards_check" in bot_text
        and "async def check_fazercards_connection()" in bot_text
        and "async def fetch_fazercards_balance" in bot_text
        and "async def fetch_fazercards_products" in bot_text,
    )
    record(
        "FazerCards connection check uses timeout and safe error handling",
        "FAZERCARDS_TIMEOUT_SECONDS" in bot_text
        and "timeout=FAZERCARDS_TIMEOUT_SECONDS" in bot_text
        and "except Exception as exc" in function_block(bot_text, "check_fazercards_connection")
        and 'logger.warning("FazerCards API check failed: %s", safe_error)' in bot_text,
    )
    record(
        "FazerCards API key stays masked in diagnostics UI",
        "masked_api_key" in bot_text
        and "mask_secret(api_key)" in function_block(bot_text, "check_fazercards_connection")
        and "API key: <code>{html_escape(str(result.get('masked_api_key')" in bot_text
        and "api_key}" not in function_block(bot_text, "fazercards_connection_result_text"),
    )
    record(
        "FazerCards diagnostics keeps auto issue disabled",
        'current["auto_issue_enabled"] = False' in bot_text
        and "Автовыдача: выключена" in bot_text,
    )
    record(
        "FazerCards connection check does not call purchase/order/create endpoints",
        "client.post" not in function_block(bot_text, "check_fazercards_connection")
        and "/giftcards/order" not in bot_text
        and "/topups/order" not in bot_text
        and "/gamekeys/order" not in bot_text
        and "/steam-gifts/order" not in bot_text
        and "/steam-topup/order" not in bot_text
        and "/manual-services/order" not in bot_text
        and "/payments/create" not in bot_text,
    )
    record(
        "FazerCards diagnostics has no automatic code issuance",
        'auto_issue_enabled"] = True' not in bot_text
        and 'auto_issue_enabled": True' not in bot_text,
    )
    record(
        "Apple ID products support FazerCards mapping fields",
        all(field in function_block(bot_text, "normalize_apple_id_product") for field in (
            "fazercards_product_id",
            "fazercards_product_name",
            "fazercards_last_seen",
            "fazercards_available",
        )),
    )
    record(
        "Apple ID admin has FazerCards link and unlink callbacks",
        "🔗 Привязать FazerCards товар" in bot_text
        and "admin_apple_id_fazer_link:" in bot_text
        and "❌ Отвязать FazerCards товар" in bot_text
        and "admin_apple_id_fazer_unlink:" in bot_text,
    )
    readonly_fetch_text = function_block(bot_text, "fetch_fazercards_products_readonly")
    readonly_cards_text = function_block(bot_text, "fetch_fazercards_giftcards_cards_readonly")
    cards_fetch_text = function_block(bot_text, "fetch_fazercards_giftcards_cards")
    cards_payload_text = function_block(bot_text, "fazercards_cards_from_payload")
    handle_callback_text = function_block(bot_text, "handle_callback")
    cards_flow_text = handle_callback_text.split("payload = await fetch_fazercards_giftcards_cards_readonly(category_id)", 1)[1].split("context.user_data[f\"fazercards_category:{product_id}\"]", 1)[0]
    mapping_handlers_text = "\n".join(
        function_block(bot_text, name)
        for name in (
            "fetch_fazercards_products_readonly",
            "fetch_fazercards_giftcards_cards_readonly",
            "fetch_fazercards_giftcards_cards",
            "fazercards_cards_from_payload",
            "fazercards_select_keyboard",
            "fazercards_cards_keyboard",
            "apple_giftcard_candidates",
            "handle_callback",
        )
    )
    record(
        "FazerCards category mapping starts with GET /giftcards",
        "payload = await fetch_fazercards_products_readonly()" in handle_callback_text
        and "admin_apple_id_fazer_link:" in handle_callback_text
        and "await fetch_fazercards_giftcards_cards_readonly(category_id)" in handle_callback_text,
    )
    record(
        "FazerCards mapping has read-only cards fetch with category_id",
        "async def fetch_fazercards_giftcards_cards_readonly" in bot_text
        and "client.get(FAZERCARDS_GIFTCARDS_CARDS_ENDPOINT" in cards_fetch_text
        and 'params = {"category_id": str(category_id or "")}' in cards_fetch_text
        and "await fetch_fazercards_giftcards_cards(client, api_key, category_id)" in readonly_cards_text,
    )
    record(
        "FazerCards cards payload helper supports offers and nested data",
        "def fazercards_cards_from_payload" in bot_text
        and '("offers", "items", "cards", "data", "products")' in cards_payload_text
        and '("offers", "items", "cards", "products")' in cards_payload_text
        and 'payload.get("data")' in cards_payload_text,
    )
    record(
        "FazerCards cards flow does not read only payload items",
        "fetched_cards = fazercards_cards_from_payload(payload)" in cards_flow_text
        and 'payload.get("items")' not in cards_flow_text,
    )
    record(
        "FazerCards mapping uses only GET/read-only product list",
        "await fetch_fazercards_products(client, api_key)" in readonly_fetch_text
        and "client.get(FAZERCARDS_PRODUCTS_ENDPOINT" in function_block(bot_text, "fetch_fazercards_products")
        and "client.post" not in mapping_handlers_text,
    )
    record(
        "FazerCards card selection callback and temporary storage exist",
        "admin_apple_id_fazer_card_pick:" in bot_text
        and "fazercards_category:{product_id}" in bot_text
        and "fazercards_cards:{product_id}" in bot_text,
    )
    record(
        "FazerCards mapping saves category_id and card_id",
        '"fazercards_category_id": fazercards_category_id_value(category)' in handle_callback_text
        and '"fazercards_card_id": card_id' in handle_callback_text
        and '"fazercards_product_id": card_id' in handle_callback_text
        and 'if not card_id:' in handle_callback_text,
    )
    record(
        "FazerCards mapping avoids purchase/order/create endpoints",
        all(endpoint not in bot_text for endpoint in (
            "/giftcards/order",
            "/topups/order",
            "/gamekeys/order",
            "/steam-gifts/order",
            "/steam-topup/order",
            "/manual-services/order",
            "/payments/create",
        )),
    )
    apple_candidates_text = function_block(bot_text, "apple_giftcard_candidates")
    apple_name_text = function_block(bot_text, "is_apple_itunes_fazercards_name")
    record(
        "App Store & iTunes (US) is recognized as Apple/iTunes candidate for US",
        "app\\s*store" in bot_text
        and "itunes" in bot_text.lower()
        and "\\(\\s*us\\s*\\)" in bot_text
        and "fazercards_name_has_region(name, region)" in apple_candidates_text,
    )
    record(
        "App Store & iTunes (TR) is recognized as Apple/iTunes candidate for TR",
        "app\\s*store" in bot_text
        and "itunes" in bot_text.lower()
        and "\\(\\s*tr\\s*\\)" in bot_text
        and "türkiye" in bot_text.lower()
        and "fazercards_name_has_region(name, region)" in apple_candidates_text,
    )
    record(
        "FazerCards Apple/iTunes candidates are not rejected when amount is missing",
        "if not fazercards_name_has_amount" not in apple_candidates_text
        and "has_amount = fazercards_name_has_amount(name, amount)" in apple_candidates_text
        and "if has_amount:" in apple_candidates_text,
    )
    record(
        "FazerCards Apple/iTunes candidates no longer require gift/card terms",
        '("gift" not in text and "card" not in text)' not in apple_candidates_text
        and '("gift" not in text or "card" not in text)' not in apple_candidates_text
        and "if not is_apple_itunes_fazercards_name(name):" in apple_candidates_text,
    )
    record(
        "FazerCards Apple/iTunes mapping has no client.post",
        "client.post" not in mapping_handlers_text,
    )
    record(
        "FazerCards Apple/iTunes mapping has no purchase/order/create endpoints",
        all(token not in mapping_handlers_text.lower() for token in ("/purchase", "/order", "/create")),
    )
    record(
        "FazerCards card confirmation shows category/card diagnostics",
        "Category ID:" in bot_text
        and "Card ID:" in bot_text
        and "Цена поставщика:" in bot_text
        and "Stock:" in bot_text,
    )
    record(
        "Apple ID user purchase remains manual with FazerCards status only",
        "create_apple_id_checkout_order" in bot_text
        and "ручная выдача" in function_block(bot_text, "apple_id_product_plan")
        and "После подтверждения оплаты отправьте клиенту код вручную" in bot_text
        and "FazerCards: <b>{fazercards_status}</b>" in bot_text,
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


def callback_branch_block(text: str, marker: str) -> str:
    start = text.find(marker)
    if start < 0:
        return ""
    nxt = text.find("\n    elif ", start + len(marker))
    return text[start:] if nxt < 0 else text[start:nxt]


def check_apple_id_rub_market_pricing(bot_text: str) -> None:
    normalize_block = function_block(bot_text, "normalize_apple_id_product")
    plan_block = function_block(bot_text, "apple_id_product_plan")
    calc_block = function_block(bot_text, "calculate_apple_id_supplier_markup_price")
    pricing_ui = function_block(bot_text, "apple_id_pricing_text") + function_block(bot_text, "apple_id_pricing_keyboard")
    confirm_block = callback_branch_block(bot_text, 'elif data.startswith("admin_apple_id_pricing_apply_confirm:")')
    apply_block = callback_branch_block(bot_text, 'elif data.startswith("admin_apple_id_pricing_apply:")')
    payment_amount_block = function_block(bot_text, "apple_id_payment_amount_rub")
    card_lock_block = function_block(bot_text, "create_card_payment_lock")
    cryptobot_branch = callback_branch_block(bot_text, 'if data == "pay_cryptobot":')
    get_rate_block = function_block(bot_text, "get_final_usd_rub_rate")
    auto_loop_block = function_block(bot_text, "usd_rub_auto_refresh_loop")
    refresh_block = function_block(bot_text, "refresh_usd_rub_rate_check")

    record("Apple ID supports price_rub", '"price_rub"' in normalize_block)
    record("Apple ID pricing_currency = RUB", '"pricing_currency", "RUB"' in normalize_block or '"pricing_currency": "RUB"' in bot_text)
    record("Apple ID pricing_mode = supplier_markup", '"pricing_mode", "supplier_markup"' in normalize_block and '"pricing_mode": "supplier_markup"' in plan_block)
    record("Apple ID has supplier_markup_percent", "supplier_markup_percent" in normalize_block and "supplier_markup_percent" in plan_block)
    record("calculate_apple_id_supplier_markup_price exists", "def calculate_apple_id_supplier_markup_price" in bot_text)
    record("no Ozon/Multitransfer in active Apple ID pricing UI", "Ozon" not in pricing_ui and "Multitransfer" not in pricing_ui)
    record("no Plati/GGSEL in active Apple ID pricing UI", "Plati" not in pricing_ui and "GGSEL" not in pricing_ui)
    record("no market_corridor in active pricing calculation", "market_corridor" not in calc_block)
    record("no market diagnostics buttons", "Диагностика" not in pricing_ui and "admin_apple_id_pricing_debug" not in pricing_ui)
    record("no source refresh buttons", "Обновить Ozon" not in pricing_ui and "admin_apple_id_pricing_refresh" not in pricing_ui)
    record("USD/RUB auto refresh interval exists and defaults to 3600", 'USD_RUB_AUTO_REFRESH_INTERVAL_SECONDS = env_int("USD_RUB_AUTO_REFRESH_INTERVAL_SECONDS", 3600)' in bot_text)
    record("background USD/RUB refresh task exists", "def schedule_usd_rub_auto_refresh" in bot_text and "usd_rub_auto_refresh_loop" in bot_text and "schedule_usd_rub_auto_refresh(app)" in bot_text)
    record("manual USD/RUB rate remains priority over auto rate", "manual_rate = get_manual_usd_rub_rate()" in get_rate_block and 'return round(manual_rate, 4), "manual"' in get_rate_block)
    record("auto refresh does not overwrite manual rate", "manual_rate=round" not in refresh_block and "market_usd_rub_rate" in refresh_block and "final_usd_rub_rate" in refresh_block)
    record("price_rub changes only after apply confirm", "set_apple_id_product" not in apply_block and '"price_rub": rec["recommended_price_rub"]' in confirm_block)
    record("manual price edit still works in RUB", "Введите новую цену продажи в RUB" in bot_text and '"pricing_currency": "RUB"' in bot_text)
    record("Apple ID user flow shows RUB", "format_apple_id_client_price(product)" in bot_text and "format_rub(price_rub)" in plan_block)
    record("Apple ID payment amount uses price_rub and not parse_price", 'plan.get("price_rub")' in payment_amount_block and "parse_price" not in payment_amount_block)
    record("Apple ID payment amount cannot be 0 if price_rub > 0", "if amount > 0:" in payment_amount_block and "return amount" in payment_amount_block)
    record("no client.post in FazerCards connection", "client.post" not in function_block(bot_text, "check_fazercards_connection"))
    record("no /giftcards/order", "/giftcards/order" not in bot_text)
    record("eSIM logic present", '"product_type": "esim"' in bot_text and "create_checkout_order" in bot_text and "await get_usd_rub_rate()" in bot_text)
    record("cashback disabled by default", 'CASHBACK_ENABLED", "false"' in bot_text)
    record("global apple_id_pricing exists", '"apple_id_pricing"' in bot_text and "DEFAULT_APPLE_ID_PRICING" in bot_text)
    record("default supplier_markup_percent = 40", '"supplier_markup_percent": 40' in bot_text)
    record("settings section active name is Настройки", "⚙️ Настройки" in bot_text and "💳 Оплата и курс" not in function_block(bot_text, "admin_panel_keyboard"))
    record("TMA/open app button hidden but TMA config remains", "def get_tma_url" in bot_text and "web_app=WebAppInfo" not in function_block(bot_text, "main_menu_keyboard"))
    record("FazerCards bulk sync button exists", "🔗 Синхронизировать FazerCards" in bot_text and "admin_apple_id_fazer_sync" in bot_text)
    record("bulk sync uses GET giftcards cards and not POST", "sync_apple_id_fazercards_bulk" in bot_text and "fetch_fazercards_products_readonly()  # GET /giftcards" in bot_text and "fetch_fazercards_giftcards_cards_readonly(category_id)  # GET /giftcards/cards" in bot_text and "client.post" not in function_block(bot_text, "sync_apple_id_fazercards_bulk"))
    bulk_sync_block = function_block(bot_text, "sync_apple_id_fazercards_bulk")

    def ordered_tokens(block: str, *tokens: str) -> bool:
        cursor = -1
        for token in tokens:
            cursor = block.find(token, cursor + 1)
            if cursor < 0:
                return False
        return True

    ok_false_guard = 'if not products_payload.get("ok"):'
    categories_empty_guard = "if not categories:"
    supplier_empty_guard = 'if report["supplier_items"] <= 0:'
    record("sync bulk checks products_payload ok before processing", ordered_tokens(bulk_sync_block, "products_payload = await fetch_fazercards_products_readonly()", ok_false_guard, "return report", "categories ="))
    record("products_payload ok=false returns before catalog save", ordered_tokens(bulk_sync_block, ok_false_guard, "return report", "save_apple_id_products(catalog)"))
    record("empty Apple categories do not mark all catalog unavailable", ordered_tokens(bulk_sync_block, categories_empty_guard, "return report", 'fazercards_sync_status": "not_found"'))
    record("failed cards endpoint does not mark products unavailable before continuing", ordered_tokens(bulk_sync_block, 'if not payload.get("ok"):', "continue", 'fazercards_sync_status": "not_found"'))
    record("not_found marking happens only after successful supplier data retrieval", ordered_tokens(bulk_sync_block, 'report["supplier_items"] += len(cards)', supplier_empty_guard, "return report", 'fazercards_sync_status": "not_found"'))
    record("exact matching prevents region and nominal mismatch", "apple_id_exact_fazercards_match" in bot_text and "fazercards_name_has_region" in function_block(bot_text, "apple_id_exact_fazercards_match") and "fazercards_name_has_amount" in function_block(bot_text, "apple_id_exact_fazercards_match"))
    record("global recalc all prices uses global markup and confirmation", "admin_apple_id_recalc_all" in bot_text and "admin_apple_id_recalc_all_confirm" in bot_text and "recalculate_all_apple_id_prices(apply=False)" in bot_text)
    record("personal account orders show paginated 5-button list", "APPLE_ID_ORDER_PAGE_SIZE = 5" in bot_text and "profile_orders:{page + 1}" in bot_text and "profile_orders:{page - 1}" in bot_text)
    fazer_sync_branch = callback_branch_block(bot_text, 'elif data == "admin_apple_id_fazer_sync":')
    add_supplier_branch = callback_branch_block(bot_text, 'elif data == "admin_apple_id_add_supplier_positions":')
    add_supplier_confirm_branch = callback_branch_block(bot_text, 'elif data == "admin_apple_id_add_supplier_positions_confirm":')
    global_markup_branch = callback_branch_block(bot_text, 'elif data == "admin_apple_id_global_markup":')
    recalc_branch = callback_branch_block(bot_text, 'elif data == "admin_apple_id_recalc_all":')
    recalc_confirm_branch = callback_branch_block(bot_text, 'elif data == "admin_apple_id_recalc_all_confirm":')
    parse_supplier_block = function_block(bot_text, "parse_apple_id_supplier_position")
    extract_nominal_block = function_block(bot_text, "extract_exact_apple_nominal_from_text")
    add_pending_block = function_block(bot_text, "add_apple_id_pending_supplier_positions")

    def access_before_call(branch: str, call: str) -> bool:
        access_index = branch.find("has_catalog_admin_access(query.from_user)")
        call_index = branch.find(call)
        return access_index >= 0 and call_index >= 0 and access_index < call_index

    record("admin_apple_id_fazer_sync branch contains has_catalog_admin_access", "has_catalog_admin_access(query.from_user)" in fazer_sync_branch)
    record("parse_apple_id_supplier_position exists", "def parse_apple_id_supplier_position" in bot_text and "return None" in parse_supplier_block)
    record("extract_exact_apple_nominal_from_text exists", "def extract_exact_apple_nominal_from_text" in bot_text and "return int(amount)" in extract_nominal_block)
    for label, needle in (
        ("supports $2", r"\$\s*(\d+(?:[.,]\d+)?)"),
        ("supports 4$", r"(\d+(?:[.,]\d+)?)\s*\$"),
        ("supports USD 2", r"\bUSD\s*(\d+(?:[.,]\d+)?)\b"),
        ("supports 2 USD", r"\b(\d+(?:[.,]\d+)?)\s*USD\b"),
        ("supports ₺100", r"₺\s*(\d+(?:[.,]\d+)?)"),
        ("supports 100₺", r"(\d+(?:[.,]\d+)?)\s*₺"),
        ("supports TRY 100", r"\bTRY\s*(\d+(?:[.,]\d+)?)\b"),
        ("supports 100 TRY", r"\b(\d+(?:[.,]\d+)?)\s*TRY\b"),
        ("supports TL 100", r"\bTL\s*(\d+(?:[.,]\d+)?)\b"),
        ("supports 100 TL", r"\b(\d+(?:[.,]\d+)?)\s*TL\b"),
    ):
        record(f"nominal extractor {label}", needle in extract_nominal_block)
    record("nominal extractor rejects from/ot and ranges", "from|от" in extract_nominal_block and r"\bto\b|\bдо\b" in extract_nominal_block and "-|–|—" in extract_nominal_block)
    record("new supplier positions are structured and saved", '"new_supplier_positions_list": []' in bulk_sync_block and "new_supplier_positions.append(parsed)" in bulk_sync_block and "save_apple_id_pending_supplier_positions" in bulk_sync_block)
    record("pending supplier list exists in config", '"apple_id_pending_supplier_positions"' in bot_text and "get_apple_id_pending_supplier_positions" in bot_text)
    record("add supplier positions callback exists", 'admin_apple_id_add_supplier_positions' in bot_text)
    record("add supplier positions confirm callback exists", 'admin_apple_id_add_supplier_positions_confirm' in bot_text)
    record("add supplier callbacks are protected by catalog admin access", "has_catalog_admin_access(query.from_user)" in add_supplier_branch and "has_catalog_admin_access(query.from_user)" in add_supplier_confirm_branch)
    record("new supplier products require confirmation before creation", "add_apple_id_pending_supplier_positions()" not in add_supplier_branch and "add_apple_id_pending_supplier_positions()" in add_supplier_confirm_branch)
    record("stable Apple ID supplier ids are generated", 'f"apple_{region.lower()}_{amount}"' in add_pending_block)
    record("supplier add avoids duplicate region amount currency", "apple_id_catalog_has_nominal" in add_pending_block and "continue" in add_pending_block)
    record("new supplier product price_rub is calculated immediately", 'calculate_apple_id_supplier_markup_price(product)' in add_pending_block and '"price_rub": rec["recommended_price_rub"]' in add_pending_block)
    record("new supplier add supports apple_us_2/apple_us_3/apple_us_4 stable ids", 'f"apple_{region.lower()}_{amount}"' in add_pending_block and '"US"' in parse_supplier_block and '"USD"' in parse_supplier_block)
    record("supplier sync uses only GET giftcards endpoints", "client.post" not in bulk_sync_block and "/giftcards/order" not in bot_text and "fetch_fazercards_products_readonly()  # GET /giftcards" in bulk_sync_block and "fetch_fazercards_giftcards_cards_readonly(category_id)  # GET /giftcards/cards" in bulk_sync_block)
    record("calculate supplier markup fallback is 40", 'global_pricing.get("supplier_markup_percent", 40)' in calc_block and "markup_percent = 40.0" in calc_block)
    record("admin_apple_id_global_markup branch contains has_catalog_admin_access", "has_catalog_admin_access(query.from_user)" in global_markup_branch)
    record("admin_apple_id_recalc_all branch contains has_catalog_admin_access", "has_catalog_admin_access(query.from_user)" in recalc_branch)
    record("admin_apple_id_recalc_all_confirm branch contains has_catalog_admin_access", "has_catalog_admin_access(query.from_user)" in recalc_confirm_branch)
    record("sync_apple_id_fazercards_bulk is not called before access check", access_before_call(fazer_sync_branch, "sync_apple_id_fazercards_bulk()"))
    record("global markup input state is not set before access check", access_before_call(global_markup_branch, 'context.user_data["client_input"] = APPLE_ID_INPUT_MARKUP'))
    record("recalculate_all_apple_id_prices(apply=False) is not called before access check", access_before_call(recalc_branch, "recalculate_all_apple_id_prices(apply=False)"))
    record("recalculate_all_apple_id_prices(apply=True) is not called before access check", access_before_call(recalc_confirm_branch, "recalculate_all_apple_id_prices(apply=True)"))
    record("bulk recalc price_rub is protected by admin access", access_before_call(recalc_confirm_branch, "recalculate_all_apple_id_prices(apply=True)") and '"price_rub": rec["recommended_price_rub"]' in function_block(bot_text, "recalculate_all_apple_id_prices"))
    record("CryptoBot Apple ID amount uses price_rub helper", "apple_id_payment_amount_rub(plan)" in cryptobot_branch and "amount <= 0" in cryptobot_branch)
    record("card payment amount uses Apple ID RUB helper", 'plan.get("product_type") == "apple_id"' in card_lock_block and "apple_id_payment_amount_rub(plan)" in card_lock_block)
    record("auto refresh logs and keeps last successful rate on failure", "logger.warning" in auto_loop_block and "keeping last successful rate" in auto_loop_block)


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
    check_apple_id_rub_market_pricing(bot_text)
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
    check_contains(config_example_text, '"supplier_markup_percent": 40', "bot/config.example.json")
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
