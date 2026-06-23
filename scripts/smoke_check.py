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
    pattern = rf"^(async\s+def|def)\s+{re.escape(name)}\s*\([^\n]*:\n.*?(?=^(?:async\s+def|def)\s+|^# ───|\Z)"
    match = re.search(pattern, text, re.DOTALL | re.MULTILINE)
    return match.group(0) if match else ""

def extract_smoke_callable(text: str, name: str, arg: str):
    block = function_block(text, name)
    if not block:
        return None
    ns = {"re": re}
    try:
        exec(block, ns)
        return ns[name](arg)
    except Exception:
        return None


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



def check_multiservice_crm(bot_text: str) -> None:
    admin_block = "\n".join([
        function_block(bot_text, "clients_dashboard_text"),
        function_block(bot_text, "clients_dashboard_keyboard"),
        function_block(bot_text, "client_list_text"),
        function_block(bot_text, "client_card_text"),
        function_block(bot_text, "client_card_keyboard"),
        function_block(bot_text, "build_order_card_text"),
        function_block(bot_text, "orders_dashboard_keyboard"),
        function_block(bot_text, "show_profile"),
        function_block(bot_text, "show_profile_invite"),
        function_block(bot_text, "show_profile_bonuses"),
    ])
    for phrase in ("Ваш статус повышен", "Новый статус", "Теперь вы получаете", "Текущий статус", "Статус клиента", "VIP / снять VIP"):
        record(f"client statuses disabled: no {phrase!r}", phrase not in bot_text)
    for legacy in ("Traveller", "Traveler", "Explorer", "Nomad", "Ambassador", "Путешественник", "Амбасадор"):
        record(f"admin/user UI hides legacy status {legacy}", legacy not in admin_block)
    record("legacy user status helper keeps compatibility", "def legacy_client_status" in bot_text and "traveler_status" in bot_text and "ambassador_status" in bot_text and "client_status" in bot_text)
    referral_block = function_block(bot_text, "referral_reward_for_profile")
    record("referral reward ignores profile status", "return FRIEND_REFERRAL_REWARD_USD" in referral_block and "status" not in referral_block.replace("statuses", ""))
    record("status upgrade notifier removed", "def notify_status_upgrade" not in bot_text)
    client_card_block = function_block(bot_text, "client_card_text")
    record("client card shows universal CRM metrics", all(x in client_card_block for x in ("Всего заказов", "Успешных заказов", "Сумма покупок", "Последний заказ", "Покупки по категориям", "Финансы", "Доступ", "Теги", "Комментарий менеджера")))
    record("client card has no marketing status", "Статус клиента" not in client_card_block and "CRM_STATUS_LABELS" not in client_card_block)
    record("client card keeps access flag", "ACCESS_LABELS" in bot_text and "Доступ" in client_card_block)
    callback_block = function_block(bot_text, "handle_callback")
    record("client CRM action callbacks are handled without VIP", all(x in callback_block for x in ("client_tags:", "client_comment:", "client_block:")) and "client_vip:" not in callback_block)
    record("client block toggles blocked", 'profile["blocked"] = not bool(profile.get("blocked", False))' in callback_block)
    record("client comment saves manager_comment", 'profile["manager_comment"] = msg.text.strip()' in function_block(bot_text, "handle_client_crm_input"))
    record("client tags save tags", 'profile["tags"] = tags' in function_block(bot_text, "handle_client_crm_input"))
    record("customer category filters are product/access based", all(x in bot_text for x in ("clients_cat:all", "clients_cat:buyers", "clients_cat:no_orders", "clients_cat:apple_id", "clients_cat:telegram_stars", "clients_cat:telegram_premium", "clients_cat:esim", "clients_cat:blocked")) and "clients_cat:vip" not in bot_text)
    record("broadcast categories are product/referral based", all(x in bot_text for x in ('"apple_id"', '"telegram_stars"', '"telegram_premium"', '"esim"', '"referrers"', '"inactive"')) and '"vip"' not in function_block(bot_text, "broadcast_recipients") and '"regular"' not in function_block(bot_text, "broadcast_recipients"))
    order_card_block = function_block(bot_text, "build_order_card_text")
    record("order card shows universal product and status fields", all(x in order_card_block for x in ("Категория", "Товар", "Статус:", "Статус выдачи", "Сумма", "Получатель", "Регион", "Пакет")))
    record("order category and status filters exist", all(x in bot_text for x in ("orders_list:apple_id", "orders_list:telegram_stars", "orders_list:telegram_premium", "orders_list:esim", "orders_list:pending_payment", "orders_list:paid", "orders_list:waiting_issue", "orders_list:issued", "orders_list:cancelled")))
    issued_block = function_block(bot_text, "order_issued_user_text")
    progress_block = function_block(bot_text, "order_in_progress_user_text")
    record("order_issued_user_text helper exists", "def order_issued_user_text" in bot_text)
    record("order_in_progress_user_text helper exists", "def order_in_progress_user_text" in bot_text and "взят в работу" in progress_block)
    issued_product_blocks = issued_block + function_block(bot_text, "order_product_user_lines")
    record("issued text is category-specific", all(x in issued_product_blocks for x in ("Telegram Stars", "Telegram Premium", "Apple ID", "Ваша eSIM")))
    record("issued notification uses helper", "order_issued_user_text(order)" in function_block(bot_text, "notify_client_order_status"))
    record("in-progress notification uses helper", "order_in_progress_user_text(order)" in function_block(bot_text, "notify_client_order_status"))
    order_amount_block = function_block(bot_text, "order_amount_rub")
    order_display_block = function_block(bot_text, "order_display_amount")
    record("order_display_amount exists and preserves USD price", "def order_display_amount" in bot_text and "return price" in order_display_block)
    record("$3 is not formatted as 3 RUB", "parse_price" not in order_amount_block and "return 0.0" in order_amount_block and "price_rub" in order_amount_block and "amount_rub" in order_amount_block and "rub_amount" in order_amount_block)
    record("CRM RUB totals use trusted RUB amounts only", "total_spent_rub = round(sum(order_amount_rub(order)" in function_block(bot_text, "collect_clients"))
    analytics_block = function_block(bot_text, "build_analytics_text")
    record("analytics helpers exist", all(x in bot_text for x in ("def analytics_revenue_rub", "def analytics_paid_orders", "def analytics_by_category", "def analytics_top_products")))
    record("analytics uses RUB revenue", "format_rub(today_revenue)" in analytics_block and "format_rub(week_revenue)" in analytics_block and "format_rub(average_order)" in analytics_block)
    record("general analytics has category and top products blocks", "Продажи по категориям" in analytics_block and "Топ товаров" in analytics_block)
    record("non-paid orders excluded from revenue", "explicit == \"paid\"" in function_block(bot_text, "is_revenue_order") and all(x in function_block(bot_text, "is_revenue_order") for x in ("pending_payment", "waiting_payment", "payment_failed", "cancelled", "refunded", "failed")))

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

    main_menu_block = function_block(bot_text, "main_menu_keyboard")
    record(
        "main menu contains Apple ID first Telegram Stars second eSIM third",
        bool(re.search(r"🍎 Пополнить Apple ID.*?⭐ Купить Telegram Stars.*?🌍 Купить eSIM.*?Личный кабинет.*?Поддержка", main_menu_block, re.DOTALL)),
    )
    record("main menu has no Telegram services label", "Telegram услуги" not in main_menu_block)
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
        "apple_id_products_by_region(region, enabled_only=True" in bot_text
        and "Сейчас товары этого региона временно недоступны" in bot_text
        and "apple_id_products_by_region(region, enabled_only=True" in function_block(bot_text, "apple_id_products_keyboard"),
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
        'RATE_CHAT_ID',
        '"rate": ""',
        '🔄 Синхронизация',
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


    record("notification_chats contains rate key", '"rate": ""' in bot_text)
    record("notification chat UI shows sync item", "🔄 Синхронизация" in bot_text and "💱 Курс" not in function_block(bot_text, "notification_chats_keyboard"))
    record("rate chat save uses common notification input", "set_notification_chat_id(kind, chat_id)" in function_block(bot_text, "handle_client_crm_input") and "rate" in bot_text)

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
        and "/giftcards/order" not in function_block(bot_text, "check_fazercards_connection")
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
        "auto fulfillment default config is safe and complete",
        '"auto_fulfillment": {' in bot_text
        and '"enabled": False' in function_block(bot_text, "runtime_default_value") + bot_text[bot_text.find('"auto_fulfillment": {'):bot_text.find('"fazercards": {')]
        and all(key in bot_text for key in ("apple_id_enabled", "telegram_stars_enabled", "telegram_premium_enabled", "esim_enabled", "max_retries", "retry_delay_seconds", "manual_fallback_enabled")),
    )
    record(
        "auto fulfillment helpers and idempotency guard exist",
        all(name in bot_text for name in ("async def auto_fulfill_order", "async def auto_fulfill_telegram_stars_order", "async def auto_fulfill_telegram_premium_order", "async def auto_fulfill_apple_id_order", "def order_already_fulfilled", "def mask_giftcard_code"))
        and "supplier_order_id" in function_block(bot_text, "order_already_fulfilled")
        and "auto_fulfilled_at" in function_block(bot_text, "order_already_fulfilled"),
    )
    record(
        "FazerCards POST endpoints are limited to fulfillment helpers",
        'FAZERCARDS_TELEGRAM_STARS_BUY_ENDPOINT = "/telegram/stars/buy"' in bot_text
        and 'FAZERCARDS_TELEGRAM_PREMIUM_BUY_ENDPOINT = "/telegram/premium/buy"' in bot_text
        and 'FAZERCARDS_GIFTCARDS_ORDER_ENDPOINT = "/giftcards/order"' in bot_text
        and "FAZERCARDS_TELEGRAM_STARS_BUY_ENDPOINT" in function_block(bot_text, "auto_fulfill_telegram_stars_order")
        and "FAZERCARDS_TELEGRAM_PREMIUM_BUY_ENDPOINT" in function_block(bot_text, "auto_fulfill_telegram_premium_order")
        and "FAZERCARDS_GIFTCARDS_ORDER_ENDPOINT" in function_block(bot_text, "auto_fulfill_apple_id_order")
        and "client.post" in function_block(bot_text, "fazercards_post_order")
        and "client.post" not in function_block(bot_text, "refresh_supplier_prices_readonly")
        and "client.post" not in function_block(bot_text, "check_fazercards_connection"),
    )
    record(
        "auto fulfillment starts only after paid order save and falls back manually",
        'await maybe_auto_fulfill_paid_order(context, order, reason="payment_paid")' in bot_text
        and "manual_required" in function_block(bot_text, "maybe_auto_fulfill_paid_order")
        and 'if order_payment_status(order) != "paid"' in function_block(bot_text, "maybe_auto_fulfill_paid_order")
        and "Заказ передан менеджеру на выдачу" in function_block(bot_text, "auto_fulfillment_client_text")
        and "Автовыдача не удалась" in function_block(bot_text, "auto_fulfillment_admin_text"),
    )
    record(
        "auto fulfillment customer texts are category-safe",
        "Telegram Stars" in function_block(bot_text, "order_product_user_lines")
        and "Telegram Premium" in function_block(bot_text, "order_product_user_lines")
        and "Apple ID" in function_block(bot_text, "order_product_user_lines")
        and "esim_auto_fulfillment_not_configured" in function_block(bot_text, "auto_fulfill_esim_order"),
    )
    apple_fulfill_block = function_block(bot_text, "auto_fulfill_apple_id_order")
    maybe_fulfill_block = function_block(bot_text, "maybe_auto_fulfill_paid_order")
    retry_branch_block = callback_branch_block(bot_text, 'elif data.startswith("order_auto_retry:")')
    order_card_text_block = function_block(bot_text, "build_order_card_text")
    client_delivery_block = function_block(bot_text, "auto_fulfillment_client_text")
    admin_delivery_block = function_block(bot_text, "auto_fulfillment_admin_text")
    record("Apple ID paid-only auto fulfillment is enforced", 'if order_payment_status(order) != "paid"' in maybe_fulfill_block and 'await maybe_auto_fulfill_paid_order(context, order, reason="payment_paid")' in bot_text and 'reason="manual_payment_confirmed"' in bot_text and "auto_fulfill_apple_id_order(" not in function_block(bot_text, "choose_payment") and "auto_fulfill_apple_id_order(" not in function_block(bot_text, "get_telegram"))
    stars_fulfill_block = function_block(bot_text, "auto_fulfill_telegram_stars_order")
    get_telegram_block = function_block(bot_text, "get_telegram")
    choose_payment_block = function_block(bot_text, "choose_payment")
    begin_telegram_block = function_block(bot_text, "begin_telegram_payment")
    notify_auto_block = function_block(bot_text, "notify_auto_fulfillment")
    record("Stars paid-only auto fulfillment is enforced", 'if order_payment_status(order) != "paid"' in maybe_fulfill_block and 'if order_payment_status(order) != "paid"' in stars_fulfill_block and 'await maybe_auto_fulfill_paid_order(context, order, reason="payment_paid")' in bot_text and 'reason="manual_payment_confirmed"' in bot_text and "auto_fulfill_telegram_stars_order(" not in choose_payment_block and "auto_fulfill_telegram_stars_order(" not in get_telegram_block)
    record("Stars supplier POST is isolated to fulfillment helper", "FAZERCARDS_TELEGRAM_STARS_BUY_ENDPOINT" in stars_fulfill_block and "fazercards_post_order(FAZERCARDS_TELEGRAM_STARS_BUY_ENDPOINT" in stars_fulfill_block and "client.post" not in choose_payment_block and "client.post" not in get_telegram_block and "client.post" not in begin_telegram_block and "client.post" not in function_block(bot_text, "sync_telegram_fazercards_bulk") and "client.post" not in function_block(bot_text, "refresh_supplier_prices_readonly") and "client.post" not in function_block(bot_text, "check_fazercards_connection"))
    record("Stars payload includes required telegram_username", "telegram_username" in stars_fulfill_block and "normalize_telegram_recipient_username" in stars_fulfill_block and stars_fulfill_block.find("normalize_telegram_recipient_username") < stars_fulfill_block.find("telegram_username"))
    record("Stars double issue protection and retry guard exist", "supplier_order_id" in function_block(bot_text, "order_already_fulfilled") and "auto_fulfilled_at" in function_block(bot_text, "order_already_fulfilled") and 'order_fulfillment_status(order) in {"issued", "auto_issued"}' in function_block(bot_text, "order_already_fulfilled") and "order_already_fulfilled(order)" in stars_fulfill_block and "order_already_fulfilled(order)" in retry_branch_block and 'order_payment_status(order) != "paid"' in retry_branch_block and 'supplier_order_id=""' not in retry_branch_block)
    record("Stars recipient is normalized and invalid recipient falls back", "def normalize_telegram_recipient_username" in bot_text and "return raw" in function_block(bot_text, "normalize_telegram_recipient_username") and "telegram_recipient_username" in get_telegram_block and "telegram_stars_recipient_invalid" in stars_fulfill_block and "manual_required" in maybe_fulfill_block)
    record("Stars supplier payload does not use tg_handle", "tg_handle" not in stars_fulfill_block)
    record("Stars client delivery and manual fallback texts exist", "Stars отправлены на указанный аккаунт" in client_delivery_block and "Мы скоро отправим Stars" in client_delivery_block and "✅ Заказ выдан" in client_delivery_block)
    record("Stars fulfillment statuses are saved", '"fulfillment_status": "issued"' in maybe_fulfill_block and '"status": "issued"' in maybe_fulfill_block and '("paid_waiting_manual_issue" if status == "manual_required" else status)' in maybe_fulfill_block and "stars_amount" in maybe_fulfill_block)
    record("Stars chat separation is enforced", "notify_payment_event_once" in choose_payment_block and "notify_auto_fulfillment" not in function_block(bot_text, "notify_payments_chat") and "📦 Автовыдача Telegram Stars запущена" in maybe_fulfill_block and "Telegram Stars отправлены" in admin_delivery_block and "FazerCards Telegram Stars fulfillment failed" in notify_auto_block)
    record("Apple ID supplier POST is isolated to fulfillment helper", "FAZERCARDS_GIFTCARDS_ORDER_ENDPOINT" in apple_fulfill_block and "fazercards_post_order(FAZERCARDS_GIFTCARDS_ORDER_ENDPOINT" in apple_fulfill_block and "/giftcards/order" not in function_block(bot_text, "sync_apple_id_fazercards_bulk") and "client.post" not in function_block(bot_text, "check_fazercards_connection") and "client.post" not in function_block(bot_text, "refresh_supplier_prices_readonly"))
    record("Apple ID double issue protection covers code supplier id and retry", "giftcard_code" in function_block(bot_text, "order_already_fulfilled") and "supplier_order_id" in function_block(bot_text, "order_already_fulfilled") and "auto_fulfilled_at" in function_block(bot_text, "order_already_fulfilled") and "apple_id_supplier_purchase_already_attempted" in bot_text and "supplier_purchase_attempted" in apple_fulfill_block and "order_already_fulfilled(order)" in retry_branch_block and 'supplier_order_id=""' not in retry_branch_block)
    record("Apple ID double purchase hard guard is enforced", "def apple_id_supplier_purchase_already_attempted" in bot_text and all(token in function_block(bot_text, "apple_id_supplier_purchase_already_attempted") for token in ("supplier_order_id", "supplier_purchase_attempted", "giftcard_code", "auto_fulfilled_at")) and "if order.get(\"supplier_purchase_attempted\")" in apple_fulfill_block and "existing_supplier_order_id" in apple_fulfill_block)
    record("Apple ID POST attempt is saved before fallback", "supplier_purchase_attempted=True" in apple_fulfill_block and "supplier_purchase_endpoint=FAZERCARDS_GIFTCARDS_ORDER_ENDPOINT" in apple_fulfill_block and apple_fulfill_block.find("update_order_fields(") < apple_fulfill_block.find("data = await fazercards_post_order") < apple_fulfill_block.find("supplier_order_id = supplier_order_id_from_response(data)") < apple_fulfill_block.find("giftcard_fields_from_response(data)"))
    record("Apple ID retry safety blocks repeated POST", "Повторная покупка Apple ID запрещена" in retry_branch_block and "Покупка у поставщика уже была запущена" in retry_branch_block and "retry_existing_supplier = apple_id_can_fetch_existing_supplier_order(order)" in retry_branch_block and "maybe_auto_fulfill_paid_order(context, fresh, reason=\"manual_retry\")" in retry_branch_block)
    stock_issue_block = function_block(bot_text, "issue_apple_id_order_from_stock")
    stock_input_block = callback_branch_block(bot_text, 'elif data == "admin_apple_id_stock_add"')
    quick_stock_input_block = function_block(bot_text, "handle_client_crm_input")
    stock_callback_block = callback_branch_block(bot_text, 'elif data.startswith("order_issue_stock:")')
    record("Apple ID stock file helpers exist", "APPLE_ID_STOCK_FILE" in bot_text and "def load_apple_id_stock()" in bot_text and "def save_apple_id_stock(items" in bot_text)
    record("Apple ID stock admin add flow exists", "🍎 Склад Apple ID" in bot_text and "APPLE_ID_STOCK_INPUT_ADD" in bot_text and "admin_apple_id_stock_add" in bot_text and "Заказ у поставщика | регион | номинал | валюта | код" in stock_input_block)
    record("Apple ID quick stock add flow exists", "➕ Быстро добавить коды" in bot_text and "admin_apple_id_stock_quick" in bot_text and "apple_id_stock_catalog_regions" in bot_text and "apple_id_stock_amount_keyboard" in bot_text and "APPLE_ID_STOCK_INPUT_QUICK_CODES" in quick_stock_input_block)
    record("Apple ID quick stock input supports bulk and optional supplier order", "parse_apple_id_quick_stock_line" in bot_text and "for raw_line in msg.text.splitlines()" in quick_stock_input_block and 'return "", line.strip()' in function_block(bot_text, "parse_apple_id_quick_stock_line") and 'supplier_order_id, code = line.split("|", 1)' in function_block(bot_text, "parse_apple_id_quick_stock_line"))
    record("Apple ID order-specific stock add exists", "➕ Добавить код под этот заказ" in bot_text and "order_add_stock_code:" in bot_text and "source_order_id" in quick_stock_input_block and "✅ Выдать сейчас" in quick_stock_input_block)
    record("Apple ID stock add checks access duplicate and available status", "apple_id_stock_duplicate_reason" in function_block(bot_text, "add_apple_id_stock_code") and '"status": "available"' in function_block(bot_text, "add_apple_id_stock_code"))
    record("Apple ID order issue from stock exists", ("📦 Выдать код со склада" in bot_text or "📦 Выдать со склада" in bot_text) and "order_issue_stock:" in bot_text and "find_available_apple_id_stock_code" in stock_issue_block and "giftcard_code=used.get" in stock_issue_block and 'fulfillment_status="issued"' in stock_issue_block and 'status="issued"' in stock_issue_block and "mark_apple_id_stock_code_used" in stock_issue_block and "used_order_id" in function_block(bot_text, "mark_stock_item_issued") and "auto_fulfillment_client_text(updated, True)" in stock_callback_block)
    record("Apple ID auto fulfillment checks stock before POST", "find_available_apple_id_stock_code" in apple_fulfill_block and "fazercards_post_order" in apple_fulfill_block and apple_fulfill_block.find("find_available_apple_id_stock_code") < apple_fulfill_block.find("fazercards_post_order") and "supplier_purchase_already_attempted_without_order_id" in bot_text)
    record("Apple ID stock privacy and duplicate safety exist", "stock_item_summary_text(item)" in function_block(bot_text, "apple_id_stock_list_text") and "mask_giftcard_code" in function_block(bot_text, "stock_item_summary_text") and "giftcard_code" not in function_block(bot_text, "format_payment_event_text") and "giftcard_code" not in function_block(bot_text, "notify_payments_chat") and "Apple ID stock issue failed" in stock_callback_block and "apple_id_stock_code_duplicate_order_id" in stock_issue_block)
    record("Apple ID quick stock result masks codes and checks stock orders used", "apple_id_stock_add_result_text" in bot_text and "mask_giftcard_code(item.get('giftcard_code'))" in function_block(bot_text, "apple_id_stock_add_result_text") and "apple_id_stock_duplicate_reason" in bot_text and "load_apple_id_stock()" in function_block(bot_text, "apple_id_stock_duplicate_reason") and "load_orders()" in function_block(bot_text, "apple_id_stock_duplicate_reason") and "used_stock" in function_block(bot_text, "apple_id_stock_duplicate_reason"))
    record("Apple ID manual code button is not exposed", "✍️ Внести Apple ID код вручную" not in bot_text)
    record("Apple ID gift card privacy is enforced in admin chats and CRM", "def mask_giftcard_code" in bot_text and "masked_giftcard_code" in order_card_text_block and "mask_giftcard_code" in admin_delivery_block and "giftcard_code" not in function_block(bot_text, "notify_payments_chat") and "giftcard_code" not in function_block(bot_text, "format_payment_event_text"))
    record("Apple ID client delivery and manual fallback texts exist", "✅ Заказ выдан" in client_delivery_block and "Ваш код" in client_delivery_block and "Redeem Gift Card or Code" in client_delivery_block and "Заказ передан менеджеру на выдачу" in client_delivery_block and "скоро отправим код" in client_delivery_block)
    record("Apple ID fulfillment statuses are saved", '"fulfillment_status": "issued"' in maybe_fulfill_block and '("paid_waiting_manual_issue" if status == "manual_required" else status)' in maybe_fulfill_block and "manual_required" in maybe_fulfill_block)
    record("Apple ID gift card parser supports nested and alternate fields", all(token in function_block(bot_text, "giftcard_fields_from_response") for token in ("giftcard_code", "activation_code", "redeem_code", "voucher_code", "claim_url", "giftcard_url")) and all(token in function_block(bot_text, "giftcard_fields_from_response") for token in ("dict", "list")))
    record("Apple ID supplier order parser supports nested and alternate ids", all(token in function_block(bot_text, "supplier_order_id_from_response") for token in ("supplier_order_id", "invoice_id", "transaction_id", "result", "data", "order", "items", "cards")))
    details_block = function_block(bot_text, "fetch_fazercards_order_details")
    parser_block = function_block(bot_text, "giftcard_fields_from_response")
    upsert_stock_block = function_block(bot_text, "upsert_apple_id_fazercards_stock_item")
    record("Apple ID details endpoint defaults to GET /orders/{orderId}", 'FAZERCARDS_ORDER_DETAILS_ENDPOINT = \"/orders/{orderId}\"' in bot_text and "FAZERCARDS_GIFTCARDS_ORDER_DETAILS_ENDPOINT" in bot_text and "client.get" in details_block and "client.post" not in details_block and "{orderId}" in details_block)
    record("Apple ID retry with supplier order uses only read-only details", "async def fetch_fazercards_order_details" in bot_text and "client.get" in details_block and "apple_id_can_fetch_existing_supplier_order" in retry_branch_block and "fazercards_post_order" not in details_block and "existing_supplier_order_id" in apple_fulfill_block and apple_fulfill_block.find("existing_supplier_order_id") < apple_fulfill_block.find("fetch_fazercards_order_details(existing_supplier_order_id)"))
    record("Apple ID gift card parser supports GET order card arrays", all(token in parser_block for token in ("giftcard_code", "activation_code", "redeem_code", "voucher_code", "serial", "download_url", "dict", "list")))
    record("Apple ID details stock upsert marks used or pending without duplicates", "def upsert_apple_id_fazercards_stock_item" in bot_text and "supplier_order_id" in upsert_stock_block and "normalize_stock_code" in upsert_stock_block and '"status": "used" if code else "pending"' in upsert_stock_block and "upsert_apple_id_fazercards_stock_item(order, existing_supplier_order_id" in apple_fulfill_block and "upsert_apple_id_fazercards_stock_item(order, supplier_order_id" in apple_fulfill_block)
    record("Apple ID missing-code diagnostics include safe response shape", "def supplier_response_shape" in bot_text and "root keys:" in function_block(bot_text, "supplier_response_shape") and "giftcard_code_missing: response_keys=" in apple_fulfill_block and "response_shape" in maybe_fulfill_block)
    record("Apple ID supplier check button exists", "🔎 Проверить у поставщика" in bot_text and "order_check_supplier:" in bot_text and "supplier_details_check" in bot_text and "Код уже выдан. Повторная отправка не выполняется." in bot_text)
    record("Apple ID tech chat shows response shape without full code", "Регион:" in notify_auto_block and "Валюта:" in notify_auto_block and "FazerCards Apple ID details fetched but code missing" in notify_auto_block and "Диагностика ответа поставщика" in notify_auto_block and "giftcard_code" not in notify_auto_block)
    record("Apple ID payload includes ids quantity amount region and currency", all(token in apple_fulfill_block for token in ("category_id", "card_id", "product_id", "quantity", "amount", "nominal", "region", "country", "currency")))
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
        "Apple ID FazerCards link and unlink callbacks are still routed",
        "admin_apple_id_fazer_link:" in bot_text
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
        and 'payload.get("result")' in cards_payload_text
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
        all(endpoint not in mapping_handlers_text for endpoint in (
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
    category_match_text = function_block(bot_text, "is_apple_fazercards_category")
    exact_match_text = function_block(bot_text, "apple_id_exact_fazercards_match")
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
        "RU sync requires Apple/iTunes/App Store/Apple ID branding",
        "has_apple_fazercards_branding" in bot_text
        and "return has_apple_fazercards_branding(name)" in category_match_text
        and "if not has_apple_fazercards_branding(names):" in exact_match_text,
    )
    record(
        "generic RU voucher and Steam voucher cannot match Apple category",
        "ru_voucher_named" not in bot_text
        and '"voucher" in text and fazercards_name_has_region(name, "RU")' not in bot_text
        and "return apple_named or ru_voucher_named" not in bot_text,
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

    revenue_block = function_block(bot_text, "is_revenue_order")
    record(
        "is_revenue_order excludes waiting_payment",
        "waiting_payment" in revenue_block and "cancelled" in revenue_block and "return explicit == \"paid\"" in revenue_block,
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

    record("USD/RUB auto refresh sends sync notification after success", "format_usd_rub_update_notification" in auto_loop_block and "await notify_rate_chat" in auto_loop_block and "notify_sync_chat" in bot_text)
    record("rate notification contains previous auto rate", "Авто-курс был" in function_block(bot_text, "format_usd_rub_update_notification"))
    record("rate notification contains new auto rate", "Авто-курс стал" in function_block(bot_text, "format_usd_rub_update_notification"))
    record("rate notification contains rub delta", "+.2f} ₽" in function_block(bot_text, "format_rate_delta"))
    record("rate notification contains percent delta", "+.2f}%" in function_block(bot_text, "format_rate_delta"))
    record("rate notification contains final calculation rate", "Финальный курс для расчётов" in function_block(bot_text, "format_usd_rub_update_notification"))
    record("rate notification accounts for manual priority", "manual_rate is not None" in auto_loop_block and "Ручной курс активен" in function_block(bot_text, "format_usd_rub_update_notification"))
    record("sync notification send failure does not crash bot", 'logger.warning("Sync notification failed' in function_block(bot_text, "notify_sync_chat"))

    record("USD/RUB auto refresh interval exists and defaults to 3600", 'USD_RUB_AUTO_REFRESH_INTERVAL_SECONDS = env_int("USD_RUB_AUTO_REFRESH_INTERVAL_SECONDS", 3600)' in bot_text)
    record("background USD/RUB refresh task exists", "def schedule_usd_rub_auto_refresh" in bot_text and "usd_rub_auto_refresh_loop" in bot_text and "schedule_usd_rub_auto_refresh(app)" in bot_text)
    record("supplier price refresh helpers exist", all(x in bot_text for x in ("async def refresh_supplier_prices_readonly", "async def refresh_supplier_prices_if_stale", "SUPPLIER_PRICE_REFRESH_TTL_SECONDS = 600", "SUPPLIER_SYNC_ERROR_NOTICE_COOLDOWN_SECONDS = 10800")))
    record("hourly job refreshes supplier prices and notifies sync chat", "refresh_supplier_prices_readonly(reason=\"hourly\")" in auto_loop_block and "notify_supplier_sync_report" in auto_loop_block)
    record("supplier refresh state persists last run and ok", "last_run_at" in function_block(bot_text, "refresh_supplier_prices_readonly") and "last_ok_at" in function_block(bot_text, "refresh_supplier_prices_readonly"))
    record("client catalogs refresh supplier prices if stale", "refresh_supplier_prices_if_stale(reason=\"client_catalog_apple_id\")" in bot_text and "refresh_supplier_prices_if_stale(reason=\"client_catalog_telegram\")" in bot_text and "showing saved prices" in bot_text)
    record("manual USD/RUB rate remains priority over auto rate", "manual_rate = get_manual_usd_rub_rate()" in get_rate_block and 'return round(manual_rate, 4), "manual"' in get_rate_block)
    record("auto refresh does not overwrite manual rate", "manual_rate=round" not in refresh_block and "market_usd_rub_rate" in refresh_block and "final_usd_rub_rate" in refresh_block)
    record("price_rub changes only after apply confirm", "set_apple_id_product" not in apply_block and '"price_rub": rec["recommended_price_rub"]' in confirm_block)
    record("manual price edit still works in RUB", "Введите новую цену продажи в RUB" in bot_text and '"pricing_currency": "RUB"' in bot_text)
    record("Apple ID user flow shows RUB", "format_apple_id_client_price(product)" in bot_text and "format_rub(price_rub)" in plan_block)
    record("apple_id_product_plan avoids direct product price_usd indexing", 'product["price_usd"]' not in plan_block and 'product.get("price_usd") or product.get("fazercards_price_usd")' in plan_block)
    record("RU default product without price_usd does not break checkout flow", "apple_ru_100" in bot_text and '"price_usd"' not in bot_text[bot_text.find('"apple_ru_100"'):bot_text.find('"apple_ru_250"')] and 'product.get("price_usd")' in plan_block)
    record("RU without price_rub/fazercards_price_usd does not create zero payment", "Товар временно недоступен" in function_block(bot_text, "start_apple_id_purchase") and "apple_id_payment_amount_rub(plan) <= 0" in function_block(bot_text, "start_apple_id_purchase"))
    record("Apple ID payment amount uses price_rub and not parse_price", 'plan.get("price_rub")' in payment_amount_block and "parse_price" not in payment_amount_block)
    record("Apple ID payment amount cannot be 0 if price_rub > 0", "if amount > 0:" in payment_amount_block and "return amount" in payment_amount_block)
    record("no client.post in FazerCards connection", "client.post" not in function_block(bot_text, "check_fazercards_connection"))
    record("FazerCards check uses Apple ID exact sync matching", "apple_id_exact_fazercards_match" in function_block(bot_text, "check_fazercards_connection") and "fetch_fazercards_giftcards_cards_readonly" in function_block(bot_text, "check_fazercards_connection"))
    record("admin supplier price refresh button exists", "🔄 Обновить цены поставщика" in bot_text and "admin_fazercards_refresh_prices" in bot_text)
    record("/giftcards/order only in auto fulfillment helper", 'FAZERCARDS_GIFTCARDS_ORDER_ENDPOINT = "/giftcards/order"' in bot_text and "FAZERCARDS_GIFTCARDS_ORDER_ENDPOINT" in function_block(bot_text, "auto_fulfill_apple_id_order") and "/giftcards/order" not in function_block(bot_text, "sync_apple_id_fazercards_bulk"))
    record("eSIM logic present", '"product_type": "esim"' in bot_text and "create_checkout_order" in bot_text and "await get_usd_rub_rate()" in bot_text)
    record("cashback disabled by default", 'CASHBACK_ENABLED", "false"' in bot_text)
    record("global apple_id_pricing exists", '"apple_id_pricing"' in bot_text and "DEFAULT_APPLE_ID_PRICING" in bot_text)
    record("default supplier_markup_percent = 40", '"supplier_markup_percent": 40' in bot_text)
    record("settings section active name is Настройки", "⚙️ Настройки" in bot_text and "💳 Оплата и курс" not in function_block(bot_text, "admin_panel_keyboard"))
    record("TMA/open app button hidden but TMA config remains", "def get_tma_url" in bot_text and "web_app=WebAppInfo" not in function_block(bot_text, "main_menu_keyboard"))
    record("Apple ID unified sync button exists", "🔄 Синхронизировать" in function_block(bot_text, "apple_id_catalog_keyboard") and "admin_apple_id_fazer_sync" in bot_text)
    record("bulk sync uses GET giftcards cards and not POST", "sync_apple_id_fazercards_bulk" in bot_text and "fetch_fazercards_products_readonly()  # GET /giftcards" in bot_text and "fetch_fazercards_giftcards_cards_readonly(category_id)  # GET /giftcards/cards" in bot_text and "client.post" not in function_block(bot_text, "sync_apple_id_fazercards_bulk"))
    stock_upsert_block = function_block(bot_text, "upsert_stock_item_from_fazercards_order")
    stock_sync_report_block = function_block(bot_text, "sync_fazercards_orders_to_stock")
    record("FazerCards stock used supplier_order_id never becomes available", 'current_status == "used"' in stock_upsert_block and 'new_status = current_status' in stock_upsert_block and 'new_status = "available"' in stock_upsert_block and stock_upsert_block.find('current_status == "used"') < stock_upsert_block.find('new_status = "available"'))
    record("FazerCards stock used supplier_order_id never becomes pending", 'current_status == "used"' in stock_upsert_block and 'new_status = current_status' in stock_upsert_block and 'new_status = "pending"' in stock_upsert_block and stock_upsert_block.find('current_status == "used"') < stock_upsert_block.find('new_status = "pending"'))
    record("FazerCards stock sync does not duplicate used supplier_order_id", 'str(item.get("supplier_order_id") or "").strip() == supplier_order_id' in stock_upsert_block and 'action = "already"' in stock_upsert_block and 'items.append(target)' in stock_upsert_block and stock_upsert_block.find('str(item.get("supplier_order_id") or "").strip() == supplier_order_id') < stock_upsert_block.find('items.append(target)'))
    record("FazerCards stock sync does not duplicate used normalized code", 'normalize_stock_code(item.get("delivery_code") or item.get("giftcard_code")) == code_key' in stock_upsert_block and 'existing = item' in stock_upsert_block and 'return None, "already"' not in stock_upsert_block)
    record("FazerCards stock report does not count used item as became_available", 'if item.get("status") == "available":' in stock_sync_report_block and 'elif item.get("status") == "used":' in stock_sync_report_block and stock_sync_report_block.find('if item.get("status") == "available":') < stock_sync_report_block.find('elif item.get("status") == "used":'))
    stock_category_text_block = function_block(bot_text, "stock_category_text")
    stock_category_keyboard_block = function_block(bot_text, "stock_category_keyboard")
    stock_list_keyboard_block = function_block(bot_text, "stock_list_keyboard")
    mark_issued_block = function_block(bot_text, "mark_stock_item_issued")
    record("stock_status_label exists and maps product labels", "def stock_status_label" in bot_text and "✅ В наличии" in bot_text and "⏳ Ожидает код" in bot_text and "⏳ Ожидают код" in bot_text and "📤 Выдана" in bot_text and "📤 Выданные" in bot_text and "⚠️ Проблема" in bot_text and "⚠️ Проблемные" in bot_text)
    record("manual stock issued button exists without technical used label", "📤 Отметить как выданную" in bot_text and "Пометить used" not in bot_text and "admin_stock_mark_issued:" in bot_text and "admin_stock_mark_issued_confirm:" in bot_text)
    record("fallback setting has product wording", "🛒 Покупать у поставщика, если склад пуст" in stock_category_text_block and "Покупать у поставщика, если склад пуст" in stock_category_keyboard_block)
    record("stock list uses product field labels", "ID позиции" in bot_text and "Заказ у поставщика" in bot_text and "Диагностика ответа поставщика" in bot_text and "response_shape:" not in function_block(bot_text, "stock_list_text"))
    record("sync report uses product wording", "✅ Стало в наличии" in function_block(bot_text, "fazercards_stock_sync_report_text") and "⏳ Всё ещё без кода" in function_block(bot_text, "fazercards_stock_sync_report_text") and "📤 Уже выданы" in function_block(bot_text, "fazercards_stock_sync_report_text") and "Осталось pending" not in function_block(bot_text, "fazercards_stock_sync_report_text") and "Стало used" not in function_block(bot_text, "fazercards_stock_sync_report_text"))
    record("mark_stock_item_issued preserves code and supplier order", "delivery_code" not in mark_issued_block and "giftcard_code" not in mark_issued_block and "delivery_pin" not in mark_issued_block and "supplier_order_id" not in mark_issued_block and 'item["status"] = "used"' in mark_issued_block and 'used_order_id or item.get("used_order_id") or "manual"' in mark_issued_block)
    record("available stock can be manually moved to issued", 'status_filter == "available"' in stock_list_keyboard_block and "admin_stock_mark_issued:" in stock_list_keyboard_block and 'stock_list_text(category, "used")' in bot_text)
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
    nominal_valid_block = function_block(bot_text, "is_valid_apple_id_nominal")
    sort_products_block = function_block(bot_text, "sort_apple_id_products")
    products_by_region_block = function_block(bot_text, "apple_id_products_by_region")
    save_products_block = function_block(bot_text, "save_apple_id_products")

    def access_before_call(branch: str, call: str) -> bool:
        access_index = branch.find("has_catalog_admin_access(query.from_user)")
        call_index = branch.find(call)
        return access_index >= 0 and call_index >= 0 and access_index < call_index

    record("admin_apple_id_fazer_sync branch contains has_catalog_admin_access", "has_catalog_admin_access(query.from_user)" in fazer_sync_branch)
    record("parse_apple_id_supplier_position exists", "def parse_apple_id_supplier_position" in bot_text and "return None" in parse_supplier_block)
    record("extract_exact_apple_nominal_from_text exists", "def extract_exact_apple_nominal_from_text" in bot_text and "return int(amount)" in extract_nominal_block)
    visible_product_block = function_block(bot_text, "is_visible_apple_id_product")
    user_keyboard_block = function_block(bot_text, "apple_id_products_keyboard")
    show_product_block = function_block(bot_text, "show_apple_id_product")
    start_apple_purchase_block = function_block(bot_text, "start_apple_id_purchase")
    admin_region_keyboard_block = function_block(bot_text, "apple_id_admin_region_keyboard")

    record("is_valid_apple_id_nominal helper exists", "def is_valid_apple_id_nominal" in bot_text)
    record("US/USD nominal range is 1..200", 'region == "US" and currency == "USD"' in nominal_valid_block and "1 <= nominal <= 200" in nominal_valid_block)
    record("TR/TRY nominal range is 100..2000", 'region == "TR" and currency == "TRY"' in nominal_valid_block and "100 <= nominal <= 2000" in nominal_valid_block)
    record("RU/RUB nominal range is 100..15000", 'region == "RU" and currency == "RUB"' in nominal_valid_block and "100 <= nominal <= 15000" in nominal_valid_block)
    record("APPLE_ID_REGION_TITLES contains RU / Russia", '"RU": "Russia"' in bot_text and '"RU": "🇷🇺"' in bot_text)
    record("user Apple ID menu contains Russia", "🇷🇺 Apple ID Russia" in bot_text and "apple_id_region:RU" in bot_text)
    record("admin Apple ID catalog contains Russia region", "APPLE_ID_REGION_FLAGS" in bot_text and "🇷🇺" in bot_text and "Russia" in bot_text)
    record("admin catalog has admin_apple_id_region RU", "🇷🇺 Russia" in function_block(bot_text, "apple_id_catalog_keyboard") and "admin_apple_id_region:RU" in function_block(bot_text, "apple_id_catalog_keyboard"))
    record("RUB format displays amount ruble sign", "RUB" in function_block(bot_text, "apple_id_product_nominal_label") and "{amount}₽" in function_block(bot_text, "apple_id_product_nominal_label") and "{amount_text}₽" in function_block(bot_text, "apple_nominal_text"))
    record("RU default products include stable edge ids", "apple_ru_100" in bot_text and "apple_ru_15000" in bot_text)
    record("nominal helper rejects non-positive and non-integer values", "nominal <= 0" in nominal_valid_block and "not isinstance(amount, int)" in nominal_valid_block and "return False" in nominal_valid_block)
    record("is_visible_apple_id_product helper exists", "def is_visible_apple_id_product" in bot_text and "is_valid_apple_id_nominal" in visible_product_block)
    record("apple_id_products_by_region has valid_only enabled by default", "def apple_id_products_by_region(region: str, enabled_only: bool = False, valid_only: bool = True)" in bot_text)
    record("apple_id_products_by_region filters visible products", "is_visible_apple_id_product(p, enabled_only=enabled_only)" in products_by_region_block)
    record("user Apple ID list uses enabled visible region products", "apple_id_products_by_region(region, enabled_only=True" in user_keyboard_block)
    record("show_apple_id_product checks visible enabled product", "is_visible_apple_id_product(product, enabled_only=True)" in show_product_block)
    record("start_apple_id_purchase checks visible enabled product", "is_visible_apple_id_product(product, enabled_only=True)" in start_apple_purchase_block)
    normalize_block = function_block(bot_text, "normalize_apple_id_product")
    admin_product_text_block = function_block(bot_text, "apple_id_admin_product_text")
    admin_product_keyboard_block = function_block(bot_text, "apple_id_admin_product_keyboard")
    supplier_disabled_text_block = function_block(bot_text, "apple_id_supplier_found_disabled_text")
    enable_branch = callback_branch_block(bot_text, 'elif data.startswith("admin_apple_id_enable:")')
    toggle_branch = callback_branch_block(bot_text, 'elif data.startswith("admin_apple_id_toggle:")')
    add_pending_block = function_block(bot_text, "add_apple_id_pending_supplier_positions")
    record("product normalization adds supplier availability fields", all(field in normalize_block for field in ("supplier_available", "supplier_status", "supplier_stock", "supplier_last_seen")))
    record("sync exact match does not change enabled", '"enabled"' not in bulk_sync_block.split('apple_id_exact_fazercards_match(product, category, card)', 1)[-1].split('seen_products.add', 1)[0])
    record("sync found sets supplier_available true", '"supplier_available": stock > 0' in bulk_sync_block and '"supplier_status": "found" if stock > 0 else "out_of_stock"' in bulk_sync_block)
    record("sync out_of_stock sets supplier_available false and status out_of_stock", '"supplier_available": stock > 0' in bulk_sync_block and '"out_of_stock"' in bulk_sync_block)
    record("sync not_found sets supplier_available false and status not_found", '"supplier_available": False' in bulk_sync_block and '"supplier_status": "not_found"' in bulk_sync_block)
    record("sync failure does not mark all products not_found", ordered_tokens(bulk_sync_block, ok_false_guard, "return report", '"supplier_status": "not_found"'))
    record("user catalog requires enabled true", 'not product.get("enabled", True)' in visible_product_block)
    record("user catalog requires supplier_available true", 'product.get("supplier_available") is not True' in visible_product_block)
    record("user catalog requires price_rub > 0", "apple_id_price_rub_value(product) <= 0" in visible_product_block)
    record("admin catalog shows products regardless supplier_available", "apple_id_products_by_region(region, valid_only=True)" in admin_region_keyboard_block)
    record("manual toggle changes only enabled", 'set_apple_id_product(product["id"], {"enabled": not product.get("enabled", True)})' in toggle_branch)
    record("admin product has found but disabled note", "Товар найден у поставщика, но выключен вручную" in admin_product_text_block)
    record("supplier found disabled filter button exists", "Найдены у поставщика, но выключены" in bot_text and "admin_apple_id_supplier_found_disabled" in bot_text)
    record("enable found disabled button changes only enabled", 'set_apple_id_product(product["id"], {"enabled": True})' in enable_branch)
    record("new supplier positions confirm creates supplier availability from stock", '"enabled": True' in add_pending_block and '"supplier_available": bool(item.get("supplier_available"))' in add_pending_block)
    record("admin Apple ID list uses visible region products", "apple_id_products_by_region(region" in admin_region_keyboard_block and "valid_only=True" in admin_region_keyboard_block)
    record("build_grid_keyboard helper exists", "def build_grid_keyboard" in bot_text and "buttons[i:i + columns]" in function_block(bot_text, "build_grid_keyboard"))
    record("user Apple ID keyboard uses grid", "build_grid_keyboard" in user_keyboard_block and "apple_id_grid_columns" in user_keyboard_block)
    record("admin Apple ID keyboard uses grid", "build_grid_keyboard" in admin_region_keyboard_block and "apple_id_grid_columns" in admin_region_keyboard_block)
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
        ("supports ₽100", r"₽\s*(\d+(?:[.,]\d+)?)"),
        ("supports 100₽", r"(\d+(?:[.,]\d+)?)\s*₽"),
        ("supports RUB 100", r"\bRUB\s*(\d+(?:[.,]\d+)?)\b"),
        ("supports 100 RUB", r"\b(\d+(?:[.,]\d+)?)\s*RUB\b"),
        ("supports RUR 100", r"\bRUR\s*(\d+(?:[.,]\d+)?)\b"),
        ("supports 100 RUR", r"\b(\d+(?:[.,]\d+)?)\s*RUR\b"),
        ("supports 100 руб", r"\b(\d+(?:[.,]\d+)?)\s*(?:руб|рублей)\b"),
        ("supports 100 р.", r"\b(\d+(?:[.,]\d+)?)\s*р\.?(?=\s|$)"),
    ):
        record(f"nominal extractor {label}", needle in extract_nominal_block)
    record("nominal extractor rejects from/ot and ranges", "from|от" in extract_nominal_block and r"\bto\b|\bдо\b" in extract_nominal_block and "-|–|—" in extract_nominal_block)
    record("new supplier positions are structured and saved", '"new_supplier_positions_list": []' in bulk_sync_block and "new_supplier_positions.append(parsed)" in bulk_sync_block and "save_apple_id_pending_supplier_positions" in bulk_sync_block)
    record("invalid supplier nominals do not enter pending", "parse_apple_id_supplier_position(category, card)" in bulk_sync_block and "not is_valid_apple_id_nominal" in parse_supplier_block and "new_supplier_positions.append(parsed)" in bulk_sync_block)
    record("invalid supplier nominals are reported as out of range", "вне допустимого диапазона" in bulk_sync_block)
    record("pending supplier list exists in config", '"apple_id_pending_supplier_positions"' in bot_text and "get_apple_id_pending_supplier_positions" in bot_text)
    record("add supplier positions callback exists", 'admin_apple_id_add_supplier_positions' in bot_text)
    record("add supplier positions confirm callback exists", 'admin_apple_id_add_supplier_positions_confirm' in bot_text)
    record("add supplier callbacks are protected by catalog admin access", "has_catalog_admin_access(query.from_user)" in add_supplier_branch and "has_catalog_admin_access(query.from_user)" in add_supplier_confirm_branch)
    record("new supplier products require confirmation before creation", "add_apple_id_pending_supplier_positions()" not in add_supplier_branch and "add_apple_id_pending_supplier_positions()" in add_supplier_confirm_branch)
    record("stable Apple ID supplier ids are generated", 'f"apple_{region.lower()}_{amount}"' in add_pending_block)
    record("stable Apple ID ids support edge ranges", 'f"apple_{region.lower()}_{amount}"' in add_pending_block and "1 <= nominal <= 200" in nominal_valid_block and "100 <= nominal <= 2000" in nominal_valid_block and "100 <= nominal <= 15000" in nominal_valid_block)
    record("invalid pending supplier nominals are skipped before product creation", "not is_valid_apple_id_nominal(region, currency, amount)" in add_pending_block and "continue" in add_pending_block and '"id": f"apple_{region.lower()}_{amount}"' in add_pending_block)
    record("supplier add avoids duplicate region amount currency", "apple_id_catalog_has_nominal" in add_pending_block and "continue" in add_pending_block)
    record("new supplier product price_rub is calculated immediately", 'calculate_apple_id_supplier_markup_price(product)' in add_pending_block and '"price_rub": rec["recommended_price_rub"]' in add_pending_block)
    record("new supplier add supports apple_us_2/apple_us_3/apple_us_4 stable ids", 'f"apple_{region.lower()}_{amount}"' in add_pending_block and '"US"' in parse_supplier_block and '"USD"' in parse_supplier_block)
    record("parse supplier supports RU/RUB", '"RU"' in parse_supplier_block and '"RUB"' in parse_supplier_block and "russia" in parse_supplier_block and "рублей" in parse_supplier_block)
    add_amount_input_block = bot_text.split('if input_mode == APPLE_ID_INPUT_ADD_AMOUNT:', 1)[1].split('if input_mode == APPLE_ID_INPUT_ADD_PRICE:', 1)[0]
    add_price_input_block = bot_text.split('if input_mode == APPLE_ID_INPUT_ADD_PRICE:', 1)[1].split('if input_mode == FAZERCARDS_INPUT_API_KEY:', 1)[0]
    record("RU invalid nominals do not enter pending or create products", "not is_valid_apple_id_nominal" in parse_supplier_block and "not is_valid_apple_id_nominal(region, currency, amount)" in add_pending_block and "100 <= nominal <= 15000" in nominal_valid_block)
    record("manual add amount prompt for RU asks RUB", 'if region == "RU"' in add_amount_input_block and "Введите цену продажи в RUB" in add_amount_input_block and "Пример: <code>1000</code>" in add_amount_input_block)
    record("manual add amount prompt for US/TR asks USD", 'else:' in add_amount_input_block and "Введите цену продажи в USD" in add_amount_input_block and "Пример: <code>9.5</code>" in add_amount_input_block)
    record("manual add price saves price_rub only for RU", 'if region == "RU"' in add_price_input_block and '"price_rub": int(round(price))' in add_price_input_block and '"pricing_currency": "RUB"' in add_price_input_block and '"pricing_mode": "supplier_markup"' in add_price_input_block)
    record("manual add price saves price_usd for US/TR", 'else:' in add_price_input_block and '"price_usd": round(price, 2)' in add_price_input_block)
    record("supplier sync uses only GET giftcards endpoints", "client.post" not in bulk_sync_block and "/giftcards/order" not in bulk_sync_block and "fetch_fazercards_products_readonly()  # GET /giftcards" in bulk_sync_block and "fetch_fazercards_giftcards_cards_readonly(category_id)  # GET /giftcards/cards" in bulk_sync_block)
    record("sort_apple_id_products sorts by amount then title/id", "def sort_apple_id_products" in bot_text and "apple_id_sort_key" in sort_products_block and "amount" in function_block(bot_text, "apple_id_sort_key") and "title_or_id" in function_block(bot_text, "apple_id_sort_key"))
    record("apple_id_products_by_region returns sorted products", "sort_apple_id_products" in products_by_region_block)
    record("new and saved Apple ID products are sorted", "sort_apple_id_products" in save_products_block and "save_apple_id_products(catalog)" in add_pending_block)
    record("calculate supplier markup fallback is 40", 'global_pricing.get("supplier_markup_percent", 40)' in calc_block and "markup_percent = 40.0" in calc_block)
    record("admin_apple_id_global_markup branch contains has_catalog_admin_access", "has_catalog_admin_access(query.from_user)" in global_markup_branch)
    record("admin_apple_id_recalc_all branch contains has_catalog_admin_access", "has_catalog_admin_access(query.from_user)" in recalc_branch)
    record("admin_apple_id_recalc_all_confirm branch contains has_catalog_admin_access", "has_catalog_admin_access(query.from_user)" in recalc_confirm_branch)
    record("sync_apple_id_fazercards_bulk is not called before access check", access_before_call(fazer_sync_branch, "sync_apple_id_fazercards_bulk()"))
    record("global markup input state is not set before access check", access_before_call(global_markup_branch, 'context.user_data["client_input"] = APPLE_ID_INPUT_MARKUP'))
    record("recalculate_all_apple_id_prices(apply=False) is not called before access check", access_before_call(recalc_branch, "recalculate_all_apple_id_prices(apply=False)"))
    record("recalculate_all_apple_id_prices(apply=True) is not called before access check", access_before_call(recalc_confirm_branch, "recalculate_all_apple_id_prices(apply=True)"))
    record("bulk recalc price_rub is protected by admin access", access_before_call(recalc_confirm_branch, "recalculate_all_apple_id_prices(apply=True)") and '"price_rub": rec["recommended_price_rub"]' in function_block(bot_text, "recalculate_all_apple_id_prices"))
    payment_helpers_block = bot_text[bot_text.find("def order_product_type_for_payment"):bot_text.find("async def notify_payments_chat")]
    formatter_block = function_block(bot_text, "format_payment_event_text")
    record("universal payment helper order_product_type_for_payment exists", "def order_product_type_for_payment" in bot_text and "other" in function_block(bot_text, "order_product_type_for_payment"))
    record("universal payment helper order_product_title_for_payment exists", "def order_product_title_for_payment" in bot_text and "Товар" in function_block(bot_text, "order_product_title_for_payment"))
    record("universal payment helper order_product_category_for_payment exists", "def order_product_category_for_payment" in bot_text and "Другое" in function_block(bot_text, "order_product_category_for_payment"))
    record("universal payment helper order_payment_amount_rub exists", "def order_payment_amount_rub" in bot_text and "apple_id_payment_amount_rub" in function_block(bot_text, "order_payment_amount_rub") and "telegram_payment_amount_rub" in function_block(bot_text, "order_payment_amount_rub"))
    record("universal payment helper order_payment_recipient_for_payment exists", "def order_payment_recipient_for_payment" in bot_text and all(x in function_block(bot_text, "order_payment_recipient_for_payment") for x in ("recipient", "telegram_recipient_username", "email", "login")))
    record("universal payment formatter exists", "def format_payment_event_text" in bot_text and all(x in formatter_block for x in ("payment_method_selected", "invoice_created", "invoice_paid", "invoice_expired", "invoice_mismatch", "payment_cancelled_before_paid", "payment_cancelled_after_paid", "manual_payment_confirmed", "refund_required")))
    record("future product payment categories have fallback coverage", all(x in payment_helpers_block for x in ("steam", "giftcard", "service_payment", "subscription", "other")))
    record("CryptoBot amount uses universal RUB payment helper", "order_payment_amount_rub(" in cryptobot_branch and "price_rub <= 0" in cryptobot_branch)
    round_crypto_block = function_block(bot_text, "round_crypto_amount_up")
    payments_chat_block = function_block(bot_text, "notify_payments_chat")
    cryptobot_created_notify_block = function_block(bot_text, "notify_cryptobot_invoice_created")
    cryptobot_paid_notify_block = function_block(bot_text, "notify_cryptobot_invoice_paid")
    record("CryptoBot round_crypto_amount_up helper exists", "def round_crypto_amount_up" in bot_text and "Decimal" in round_crypto_block)
    record("CryptoBot rounding uses Decimal ROUND_CEILING", "Decimal" in round_crypto_block and "ROUND_CEILING" in round_crypto_block)
    record("CryptoBot rounding no longer uses math.ceil", "math.ceil" not in round_crypto_block)
    record("payments chat safe helper exists", "def notify_payments_chat" in bot_text and "try:" in payments_chat_block and "except Exception as exc" in payments_chat_block)
    record("CryptoBot invoice created notification uses safe payments chat helper", "notify_payments_chat(context, text)" in cryptobot_created_notify_block)
    record("CryptoBot invoice paid notification uses safe payments chat helper", "notify_payments_chat(context, text)" in cryptobot_paid_notify_block and "context.bot.send_message" not in cryptobot_paid_notify_block)
    record("CryptoBot RUB to USDT helper uses shared USD/RUB rate", "def cryptobot_invoice_amount_from_rub" in bot_text and "await get_usd_rub_rate()" in function_block(bot_text, "cryptobot_invoice_amount_from_rub"))
    record("CryptoBot invoice amount is converted from RUB", "cryptobot_invoice_amount_from_rub(price_rub" in cryptobot_branch and "crypto_create_invoice(token, cryptobot_amount" in cryptobot_branch and "price_rub=price_rub" in cryptobot_branch)
    record("CryptoBot createInvoice does not pass RUB price as amount", "crypto_create_invoice(token, price_rub" not in cryptobot_branch and "crypto_create_invoice(token, amount" not in cryptobot_branch)
    record("CryptoBot min invoice USDT exists", "CRYPTOBOT_MIN_INVOICE_USDT = 0.01" in bot_text and "max(crypto_amount, CRYPTOBOT_MIN_INVOICE_USDT)" in function_block(bot_text, "cryptobot_invoice_amount_from_rub"))
    record("CryptoBot payment_details stores universal invoice calculation", all(x in function_block(bot_text, "cryptobot_payment_details") for x in ("payment_amount_rub", "payment_asset", "payment_asset_amount", "usd_rub_rate_used", "usd_rub_rate_source", "cryptobot_amount", "cryptobot_asset", "price_rub")))
    record("CryptoBot client text shows RUB USDT and rate", all(x in function_block(bot_text, "cryptobot_client_payment_text") for x in ("Сумма заказа", "К оплате", "Курс расчёта", "format_rub", "format_crypto_amount")))
    record("CryptoBot unsafe RUB-as-USDT guard exists", "Unsafe CryptoBot invoice amount: RUB amount passed as USDT" in function_block(bot_text, "crypto_create_invoice") and "amount) >= float(price_rub) / 2" in function_block(bot_text, "crypto_create_invoice"))
    check_payment_block = callback_branch_block(bot_text, 'elif data.startswith("check_payment_")')
    cancel_order_block = function_block(bot_text, "cancel_order_conv")
    admin_action_block = function_block(bot_text, "handle_admin_action")
    record("payment chat gets method selected invoice created and paid events", "notify_payment_event_once(context, \"payment_method_selected\"" in bot_text and "notify_payment_event_once(context, \"invoice_created\"" in cryptobot_branch and "notify_payment_event_once(context, \"invoice_paid\"" in check_payment_block)
    record("payment chat gets expired and mismatch events", "notify_payment_event_once(context, \"invoice_expired\"" in check_payment_block and "notify_payment_event_once(context, \"invoice_mismatch\"" in check_payment_block)
    record("payment chat gets before and after paid cancellation events", "payment_cancelled_before_paid" in cancel_order_block and "payment_cancelled_after_paid" in cancel_order_block and "refund_required" in admin_action_block)
    record("payment chat gets manual confirmation events", "manual_payment_confirmed" in admin_action_block and "manual_confirm" in admin_action_block)
    record("payment notice duplicate helpers exist", "def payment_notice_already_sent" in bot_text and "def mark_payment_notice_sent" in bot_text and "payment_notifications" in bot_text)
    record("CryptoBot paid check verifies invoice asset and crypto amount", all(x in callback_branch_block(bot_text, 'elif data.startswith("check_payment_")') for x in ("crypto_get_invoice", "invoice_asset == expected_asset", "abs(invoice_amount - expected_amount)")))
    record("card payment amount uses Apple ID RUB helper", "apple_id_payment_amount_rub(plan)" in card_lock_block)
    record("auto refresh logs and keeps last successful rate on failure", "logger.warning" in auto_loop_block and "keeping last successful rate" in auto_loop_block)

    telegram_sync_block = function_block(bot_text, "sync_telegram_fazercards_bulk")
    cards_payload_text = function_block(bot_text, "fazercards_cards_from_payload")
    telegram_keyboard_block = function_block(bot_text, "admin_telegram_services_keyboard")
    telegram_report_block = function_block(bot_text, "telegram_fazercards_sync_report_text")
    telegram_diag_block = function_block(bot_text, "telegram_fazercards_sync_diagnostics_text")
    telegram_main_text_block = function_block(bot_text, "admin_telegram_services_text")
    telegram_card_block = function_block(bot_text, "telegram_admin_product_card_text")
    telegram_card_keyboard_block = function_block(bot_text, "telegram_admin_product_card_keyboard")
    telegram_admin_recalc_product_block = function_block(bot_text, "telegram_admin_recalculate_product")
    telegram_apply_match_block = function_block(bot_text, "telegram_apply_supplier_match")
    crm_input_block = function_block(bot_text, "handle_client_crm_input")
    telegram_recalc_block = function_block(bot_text, "recalculate_all_telegram_prices")
    telegram_category_block = function_block(bot_text, "is_telegram_fazercards_category")
    stars_parser_block = function_block(bot_text, "extract_telegram_stars_nominal_from_text")
    premium_parser_block = function_block(bot_text, "extract_telegram_premium_duration_from_text")
    telegram_add_pending_block = function_block(bot_text, "add_telegram_pending_supplier_positions")

    apple_catalog_text_block = function_block(bot_text, "apple_id_catalog_text")
    apple_catalog_keyboard_block = function_block(bot_text, "apple_id_catalog_keyboard")
    apple_card_block = function_block(bot_text, "apple_id_admin_product_text")
    apple_card_keyboard_block = function_block(bot_text, "apple_id_admin_product_keyboard")
    apple_sync_report_block = function_block(bot_text, "fazercards_bulk_sync_report_text")
    record("Admin catalog buttons use unified Apple ID and Telegram names", "🍎 Apple ID каталог" in bot_text and "⭐ Telegram каталог" in bot_text and '"⭐ Telegram Stars", callback_data="admin_telegram_services"' not in bot_text and "Telegram услуги" not in bot_text)
    record("Apple ID main screen has unified blocks", all(x in apple_catalog_text_block for x in ("<b>Статус</b>", "Последняя синхронизация", "Курс USD/RUB", "Наценка", "Каталог", "Ожидают добавления")))
    record("Telegram main screen has unified blocks", all(x in telegram_main_text_block for x in ("<b>Статус</b>", "Последняя синхронизация", "Курс USD/RUB", "Наценка", "Каталог", "Ожидают добавления")))
    record("Apple ID catalog actions are unified", all(x in apple_catalog_keyboard_block for x in ("🔄 Синхронизировать", "➕ Добавить найденные товары", "✏️ Наценка", "🔄 Пересчитать цены", "◀️ Назад")) and ("🧪 Диагностика sync" in apple_catalog_keyboard_block or "🔎 Найдены у поставщика, но выключены" in apple_catalog_keyboard_block))
    record("Telegram catalog actions are unified", all(x in telegram_keyboard_block for x in ("⭐ Stars товары", "💎 Premium товары", "🔄 Синхронизировать", "➕ Добавить найденные товары", "✏️ Наценка", "🔄 Пересчитать цены", "🧪 Диагностика sync", "◀️ Назад")))
    record("Apple ID admin card has unified blocks and finance", all(x in apple_card_block for x in ("<b>Статусы</b>", "<b>Поставщик</b>", "<b>Финансы</b>", "<b>Служебное</b>", "Себестоимость", "Курс", "Наценка", "Цена продажи", "Маржа", "точное количество поставщик не передаёт")))
    record("Telegram admin card has unified supplier and finance", all(x in telegram_card_block for x in ("<b>Статусы</b>", "<b>Поставщик</b>", "<b>Финансы</b>", "<b>Служебное</b>", "Себестоимость", "Курс", "Наценка", "Цена продажи", "Маржа", "точное количество поставщик не передаёт")))
    record("Apple ID card action buttons are real callbacks", all(x in apple_card_keyboard_block for x in ("admin_apple_id_toggle:", "admin_apple_id_price:", "admin_apple_id_pricing_markup:", "admin_apple_id_pricing_apply_confirm:")) and 'callback_data="admin_apple_id_catalog"' not in apple_card_keyboard_block)
    record("Apple ID card keeps FazerCards link unlink and delete actions", all(x in apple_card_keyboard_block for x in ("admin_apple_id_fazer_link:", "admin_apple_id_fazer_unlink:", "admin_apple_id_delete:")))
    record("Apple ID supplier-found button is not mislabeled as diagnostics", ("🧪 Диагностика sync" not in apple_catalog_keyboard_block or "admin_apple_id_supplier_found_disabled" not in apple_catalog_keyboard_block) and ("admin_apple_id_supplier_found_disabled" not in apple_catalog_keyboard_block or "🔎 Найдены у поставщика, но выключены" in apple_catalog_keyboard_block))
    record("Apple ID pending uses unified found products label", "➕ Добавить найденные товары" in apple_catalog_keyboard_block and "admin_apple_id_add_supplier_positions" in bot_text)
    record("Apple ID short sync report hides raw technical fields", all(x not in apple_sync_report_block for x in ("raw sample", "raw keys", "HTTP status", "sample raw", "raw type")) and "Синхронизация Apple ID завершена" in apple_sync_report_block)

    record("Telegram Stars main button exists", "⭐ Купить Telegram Stars" in bot_text and "telegram_stars_start" in bot_text)
    record("Telegram section contains Stars and Premium choices", "⭐ Звёзды" in bot_text and "💎 Premium" in bot_text)
    record("Telegram product types exist", "telegram_stars" in bot_text and "telegram_premium" in bot_text)
    record("Telegram catalogs and pending lists exist", all(x in bot_text for x in ("telegram_stars_products", "telegram_premium_products", "telegram_stars_pending_supplier_positions", "telegram_premium_pending_supplier_positions")))
    record("Telegram read-only helpers and relative endpoint constants exist", "async def fetch_fazercards_telegram_stars_readonly" in bot_text and "async def fetch_fazercards_telegram_premium_readonly" in bot_text and 'FAZERCARDS_TELEGRAM_STARS_ENDPOINT = "/telegram/stars"' in bot_text and 'FAZERCARDS_TELEGRAM_PREMIUM_ENDPOINT = "/telegram/premium"' in bot_text)
    record("Telegram sync uses official endpoints as primary path", "fetch_fazercards_telegram_stars_readonly()" in telegram_sync_block and "fetch_fazercards_telegram_premium_readonly()" in telegram_sync_block and ordered_tokens(telegram_sync_block, "fetch_fazercards_telegram_stars_readonly()", "_sync_telegram_giftcards_fallback"))
    record("Telegram endpoint constants do not duplicate API prefix", "/api/v2/telegram/stars" not in bot_text and "/api/v2/telegram/premium" not in bot_text)
    record("Telegram sync avoids buy/order POST endpoints", all(x not in telegram_sync_block for x in ("/telegram/stars/buy", "/telegram/premium/buy", "/giftcards/order")) and "client.post" not in telegram_sync_block)
    record("Telegram giftcards fallback is not primary", "_sync_telegram_giftcards_fallback" in bot_text and 'report["fallback_used"] = True' in telegram_sync_block)
    record("Telegram admin main back returns to settings", 'callback_data="admin_payment_sections"' in telegram_keyboard_block and 'callback_data="admin_business"' not in telegram_keyboard_block)
    record("Telegram inner admin screens return to Telegram services", bot_text.count('callback_data="admin_telegram_services"') >= 2 and "admin_telegram_stars_catalog" in bot_text and "admin_telegram_premium_catalog" in bot_text)
    record("Telegram endpoint parser supports API items", "telegram_api_item_id" in bot_text and "telegram_api_item_price_usd" in bot_text and "telegram_api_item_stock" in bot_text and "telegram_api_item_text" in bot_text)
    record("FazerCards cards helper supports result containers", all(x in cards_payload_text for x in ('"offers"', '"items"', '"cards"', '"data"', '"products"', 'payload.get("result")')))
    record("Telegram category filter accepts Telegram звёзды и премиум", "is_telegram_fazercards_category" in bot_text and "телеграм" in telegram_category_block and "telegram" in telegram_category_block and r"\btg\b" in telegram_category_block)
    record("Stars branding requires telegram and stars groups", "def is_telegram_stars_branding" in bot_text and "has_telegram and has_stars" in function_block(bot_text, "is_telegram_stars_branding"))
    record("Premium branding requires telegram and premium groups", "def is_telegram_premium_branding" in bot_text and "has_telegram and has_premium" in function_block(bot_text, "is_telegram_premium_branding"))
    record("Stars nominal parser supports RU, emoji, XTR and Stars samples", all(x in stars_parser_block for x in ("звезд", "зв\\.", "⭐", "☆", "★", "xtr", "stars")) and "50 <= nominal <= 10000" in stars_parser_block)
    record("Stars branding supports FazerCards star and зв abbreviations", "☆" in function_block(bot_text, "is_telegram_stars_branding") and r"зв\." in function_block(bot_text, "is_telegram_stars_branding"))
    record("Telegram API item id aliases are supported", all(x in function_block(bot_text, "telegram_api_item_id") for x in ("product_id", "productId", "offer_id", "offerId", "package_id", "packageId")))
    record("Telegram API item stock supports boolean availability", "is_available" in function_block(bot_text, "telegram_api_item_stock") and "return 1 if value else 0" in function_block(bot_text, "telegram_api_item_stock"))
    record("Telegram admin status helpers exist", all(x in bot_text for x in ("def telegram_admin_product_status_badge", "def telegram_admin_supplier_status_badge", "def telegram_admin_price_status_badge", "def telegram_admin_sync_age_badge")))
    record("Telegram diagnostics button exists", "🧪 Диагностика sync" in telegram_keyboard_block and "admin_telegram_sync_diagnostics" in bot_text)
    record("Telegram quote username admin button exists", "👤 Username для проверки цен" in telegram_keyboard_block and "admin_telegram_quote_username" in bot_text)
    record("Telegram short sync report hides raw technical fields", all(x not in telegram_report_block for x in ("raw sample", "raw keys", "HTTP status", "sample raw", "raw type")))
    record("Telegram diagnostics contains raw/debug fields", all(x in telegram_diag_block for x in ("raw keys", "raw debug", "Samples Stars", "Samples Premium", "Stars endpoint path", "Premium endpoint path")))
    record("Telegram diagnostics is capped to safe Telegram message length", "len(text) > 3500" in telegram_diag_block and "text[:3470]" in telegram_diag_block)
    record("Telegram endpoint failure can report error without not_found", "report[\"error\"]" in telegram_sync_block and "supplier_read_ok_stars" in telegram_sync_block and "supplier_read_ok_premium" in telegram_sync_block)
    record("Stars parser handles FazerCards samples", extract_smoke_callable(bot_text, "extract_telegram_stars_nominal_from_text", "50 ☆") == 50 and extract_smoke_callable(bot_text, "extract_telegram_stars_nominal_from_text", "50 зв.") == 50 and extract_smoke_callable(bot_text, "extract_telegram_stars_nominal_from_text", "☆ 100") == 100 and extract_smoke_callable(bot_text, "extract_telegram_stars_nominal_from_text", "100★") == 100)
    record("Premium duration parser supports months and m samples", all(x in premium_parser_block for x in ("месяц", "months", "m\\b")) and "TELEGRAM_PREMIUM_SUPPORTED_DURATIONS = {1, 3, 6, 12}" in bot_text)
    record("Telegram main admin screen shows clean summary", all(x in telegram_main_text_block for x in ("<b>Статус</b>", "Последняя синхронизация", "Курс USD/RUB", "Наценка", "Каталог", "Ожидают добавления", "telegram_sync_status_label", "stars_markup_percent", "premium_markup_percent")))
    record("Telegram admin cards show finance and sync fields", all(x in telegram_card_block for x in ("supplier_price_usd", "supplier_cost_rub", "supplier_markup_percent", "price_rub", "estimated_margin_rub", "supplier_last_seen")))
    record("Telegram admin card action buttons are real callbacks", all(x in telegram_card_keyboard_block for x in ("admin_telegram_{kind}_toggle:", "admin_telegram_{kind}_price:", "admin_telegram_{kind}_markup:", "admin_telegram_{kind}_recalc:")) and 'callback_data="admin_telegram_services"' not in telegram_card_keyboard_block)
    record("Telegram admin toggle callbacks exist for Stars and Premium", all(x in bot_text for x in ("admin_telegram_stars_toggle:", "admin_telegram_premium_toggle:")) and 'product["enabled"] = not bool(product.get("enabled"))' in bot_text and "telegram_admin_save_products_by_kind(kind, products)" in bot_text)
    record("Telegram manual price input updates manual price and margin", "TELEGRAM_PRODUCT_PRICE_INPUT" in bot_text and "telegram_product_price_input" in bot_text and 'product["price_rub"] = new_price' in crm_input_block and 'product["pricing_mode"] = "manual"' in crm_input_block and 'product["estimated_margin_rub"]' in crm_input_block)
    record("Telegram individual markup input recalculates supplier markup price", "TELEGRAM_PRODUCT_MARKUP_INPUT" in bot_text and "telegram_product_markup_input" in bot_text and 'product["supplier_markup_percent"] = round(markup, 4)' in crm_input_block and 'product["pricing_mode"] = "supplier_markup"' in crm_input_block and "telegram_admin_recalculate_product(product, kind)" in crm_input_block)
    record("Telegram single product recalc handles manual and supplier markup", all(x in bot_text for x in ("admin_telegram_stars_recalc:", "admin_telegram_premium_recalc:")) and 'product.get("pricing_mode") == "manual"' in telegram_admin_recalc_product_block and 'product.update({"supplier_cost_rub"' in telegram_admin_recalc_product_block and '"price_rub": rec["recommended_price_rub"]' in telegram_admin_recalc_product_block or '"price_rub"' in telegram_admin_recalc_product_block and 'rec["recommended_price_rub"]' in telegram_admin_recalc_product_block)
    record("Telegram sync preserves manual price", "telegram_apply_supplier_match" in bot_text and 'manual_price = existing.get("price_rub")' in telegram_apply_match_block and 'existing["price_rub"] = manual_price' in telegram_apply_match_block and 'existing["pricing_mode"] = "manual"' in telegram_apply_match_block)
    record("Telegram list parser supports alternate containers", all(x in function_block(bot_text, "telegram_items_from_payload") for x in ('"data"', '"result"', '"payload"', '"quotes"', '"plans"', '"packages"', '"tariffs"', '"products"', '"rows"', '"list"')))
    record("Telegram Stars default packages are defined", "TELEGRAM_STARS_DEFAULT_PACKAGES = (50, 100, 200, 250, 500, 750, 1000, 1500, 2000, 2500, 5000, 10000)" in bot_text)
    record("Telegram Stars price_per_star sync generates packages", "telegram_stars_price_per_star_payload" in bot_text and "telegram_stars_price_per_star_supplier_positions" in bot_text and "price_per_star" in telegram_sync_block and "stars_packages_generated" in telegram_sync_block and "stars_candidates_found" in telegram_sync_block and "pending_stars_count" in telegram_sync_block)
    record("Telegram Stars supplier price uses amount times price_per_star", "supplier_price_usd = round(amount * price_per_star, 6)" in bot_text)
    record("Telegram Stars price_per_star diagnostic fields exist", all(x in telegram_diag_block for x in ("Stars price per star", "Stars min amount", "Stars max amount", "Stars packages generated")))
    record("Telegram Stars price_per_star sync does not require username", 'report["stars_requires_params"] = "no"' in telegram_sync_block and "Для Telegram Stars quote нужен test username" in telegram_sync_block)
    record("Telegram quote mode fallback supports standard Stars packages", "TELEGRAM_STARS_STANDARD_PACKAGES = TELEGRAM_STARS_DEFAULT_PACKAGES" in bot_text and "stars_quotes_requested" in telegram_sync_block and "_telegram_quote_supplier_position" in telegram_sync_block)
    record("Telegram quote mode supports Premium durations", "TELEGRAM_PREMIUM_STANDARD_DURATIONS = (1, 3, 6, 12)" in bot_text and "premium_quotes_requested" in telegram_sync_block and "_telegram_quote_supplier_position" in telegram_sync_block)
    record("Telegram quote username setting exists for quote fallback", "quote_test_username" in bot_text and "TELEGRAM_QUOTE_USERNAME_INPUT" in bot_text and "Для Telegram Stars quote нужен test username" in telegram_sync_block)
    record("Telegram sync does not use client.post", "client.post" not in telegram_sync_block and "client.post" not in function_block(bot_text, "fetch_fazercards_telegram_endpoint_readonly"))
    record("Telegram pending Stars and Premium are saved by sync", '"telegram_stars_pending_supplier_positions"] = pending[:100]' in telegram_sync_block and '"telegram_premium_pending_supplier_positions"] = pending[:100]' in telegram_sync_block)
    record("Telegram add pending Stars and Premium appends catalog and clears pending", "normalize_telegram_stars_product(item)" in telegram_add_pending_block and "normalize_telegram_premium_product(item)" in telegram_add_pending_block and '"telegram_stars_pending_supplier_positions"] = []' in telegram_add_pending_block and '"telegram_premium_pending_supplier_positions"] = []' in telegram_add_pending_block)
    record("Telegram unified pending buttons exist", all(x in bot_text for x in ("➕ Добавить найденные товары", "⭐ Добавить Stars", "💎 Добавить Premium", "✅ Добавить всё")))
    record("Telegram markup screen and recalculation exist", "✏️ <b>Наценка Telegram</b>" in bot_text and "def recalculate_all_telegram_prices" in bot_text and all(x in telegram_recalc_block for x in ("supplier_cost_rub", "supplier_markup_percent", "price_rub", "estimated_margin_rub")))
    record("Telegram global markup buttons open input instead of placeholders", "admin_telegram_stars_global_markup" in bot_text and "admin_telegram_premium_global_markup" in bot_text and "TELEGRAM_GLOBAL_MARKUP_INPUT" in bot_text and 'context.user_data["telegram_global_markup_kind"] = kind' in bot_text and "save_telegram_services_pricing_settings({key: round(markup, 4)})" in bot_text)
    record("Telegram sync failure does not mass mark not_found", "elif supplier_read_ok_stars:" in telegram_sync_block and "elif supplier_read_ok_premium:" in telegram_sync_block and "not_found" in telegram_sync_block)
    record("Telegram price formula uses supplier USD final USD/RUB markup", "calculate_telegram_supplier_markup_price" in bot_text and "supplier_price * rate" in bot_text and "1 + markup / 100" in bot_text and "get_final_usd_rub_rate()" in bot_text)
    record("manual USD/RUB priority preserved", "def get_final_usd_rub_rate" in bot_text and "get_manual_usd_rub_rate()" in function_block(bot_text, "get_final_usd_rub_rate"))
    record("Telegram no zero payments", "telegram_payment_amount_rub(plan) <= 0" in bot_text and "Оплата не создана" in bot_text)
    telegram_stars_button_block = function_block(bot_text, "telegram_stars_client_button_label")
    telegram_premium_button_block = function_block(bot_text, "telegram_premium_client_button_label")
    telegram_stars_catalog_keyboard_block = function_block(bot_text, "telegram_stars_catalog_keyboard")
    telegram_premium_catalog_keyboard_block = function_block(bot_text, "telegram_premium_catalog_keyboard")
    record("Telegram Stars client button label helper exists", "def telegram_stars_client_button_label" in bot_text)
    record("Telegram Premium client button label helper exists", "def telegram_premium_client_button_label" in bot_text)
    record("Telegram Stars client button label shows amount and RUB price", all(x in telegram_stars_button_block for x in ("amount", "⭐", "telegram_payment_amount_rub(product)", "format_rub(price)", "₽")))
    record("Telegram Premium client button label shows duration and RUB price", all(x in telegram_premium_button_block for x in ("duration_months", "month_word(months)", "telegram_payment_amount_rub(product)", "format_rub(price)", "₽")))
    record("Telegram client catalog uses price labels and keeps callbacks", "telegram_stars_client_button_label(p)" in telegram_stars_catalog_keyboard_block and "telegram_premium_client_button_label(p)" in telegram_premium_catalog_keyboard_block and "telegram_stars_product:{p['id']}" in telegram_stars_catalog_keyboard_block and "telegram_premium_product:{p['id']}" in telegram_premium_catalog_keyboard_block)
    record("Telegram client catalog hides internal supplier fields", all(x not in telegram_stars_catalog_keyboard_block + telegram_premium_catalog_keyboard_block for x in ("supplier_price_usd", "fazercards", "supplier_cost_rub", "estimated_margin_rub", "Маржа", "Себестоимость")))
    record("Telegram user catalog requires enabled supplier_available price", "product.get(\"enabled\") is not True" in bot_text and "product.get(\"supplier_available\") is not True" in bot_text and "telegram_payment_amount_rub(product) <= 0" in bot_text)
    record("Telegram recipient username collected and saved", "normalize_telegram_recipient_username" in bot_text and "telegram_recipient_username" in bot_text and "👤 Получатель — мой аккаунт" in bot_text)
    record("CRM supports Telegram Stars and Premium", "Заказ Telegram Stars" in bot_text and "Заказ Telegram Premium" in bot_text)
    record("notifications include Telegram Stars and Premium", "Новый заказ Telegram Stars" in bot_text and "Новый заказ Telegram Premium" in bot_text)
    user_order_block = function_block(bot_text, "build_user_order_card_text")
    notify_block = function_block(bot_text, "notify_admin")
    notify_telegram_block = notify_block.split('if order.get("product_type") in {"telegram_stars", "telegram_premium"}:', 1)[1].split('elif order.get("product_type") == "apple_id":', 1)[0] if 'if order.get("product_type") in {"telegram_stars", "telegram_premium"}:' in notify_block else ""
    begin_tg_block = function_block(bot_text, "begin_telegram_payment")
    get_telegram_block = function_block(bot_text, "get_telegram")
    build_order_card_block = function_block(bot_text, "build_order_card_text")
    record("build_user_order_card_text Telegram payment_method is defined", "payment_method =" in user_order_block and "order.get(\"payment_method\")" in user_order_block and "Оплата:" in user_order_block)
    record("notify_admin Telegram branch does not return formatted string", "return (" not in notify_telegram_block and "return" not in notify_telegram_block)
    record("notify_admin forms text for telegram_stars", "Новый заказ Telegram Stars" in notify_telegram_block and "text =" in notify_telegram_block and "Закуп:" in notify_telegram_block and "Маржа:" in notify_telegram_block and "card_id" in notify_telegram_block)
    record("notify_admin reaches send_admin_order_message", "await send_admin_order_message(context, admin_id, text, order_id)" in notify_block)
    record("notify_admin forms text for telegram_premium", "Новый заказ Telegram Premium" in notify_telegram_block and "text =" in notify_telegram_block and "Закуп:" in notify_telegram_block and "Маржа:" in notify_telegram_block and "card_id" in notify_telegram_block)
    record("Telegram order is initially created once in begin payment", begin_tg_block.count("create_telegram_checkout_order") == 1 and function_block(bot_text, "create_telegram_checkout_order").count("append_order") == 1)
    record("checkout_order_id update prevents Telegram duplicate order", "checkout_order_id" in get_telegram_block and "update_checkout_order(checkout_order_id" in get_telegram_block and "or append_order(order_payload)" in get_telegram_block)
    record("CRM card supports Telegram Stars without crashing", "telegram_stars" in build_order_card_block and "Заказ Telegram Stars" in build_order_card_block and "payment_method" in build_order_card_block)
    record("CRM card supports Telegram Premium without crashing", "telegram_premium" in build_order_card_block and "Заказ Telegram Premium" in build_order_card_block and "payment_method" in build_order_card_block)
    record("personal account order card supports Telegram Stars", "telegram_stars" in user_order_block and "Заказ Telegram Stars" in user_order_block)
    record("personal account order card supports Telegram Premium", "telegram_premium" in user_order_block and "Заказ Telegram Premium" in user_order_block)


def check_telegram_premium_auto_fulfillment(bot_text: str) -> None:
    premium_helper = function_block(bot_text, "auto_fulfill_telegram_premium_order")
    maybe_block = function_block(bot_text, "maybe_auto_fulfill_paid_order")
    stars_helper = function_block(bot_text, "auto_fulfill_telegram_stars_order")
    get_telegram_block = function_block(bot_text, "get_telegram")
    choose_payment_block = function_block(bot_text, "choose_payment")
    invoice_block = function_block(bot_text, "create_cryptobot_invoice")
    sync_block = function_block(bot_text, "sync_telegram_fazercards_bulk")
    diagnostics_block = function_block(bot_text, "fetch_fazercards_telegram_endpoint_readonly") + function_block(bot_text, "fetch_fazercards_products_readonly") + function_block(bot_text, "fetch_fazercards_giftcards_cards_readonly")
    client_text_block = function_block(bot_text, "auto_fulfillment_client_text")
    notify_block = function_block(bot_text, "notify_auto_fulfillment")
    admin_text_block = function_block(bot_text, "auto_fulfillment_admin_text")
    order_card_block = function_block(bot_text, "build_order_card_text")
    retry_keyboard_block = function_block(bot_text, "order_card_keyboard")
    already_block = function_block(bot_text, "order_already_fulfilled")

    record("Premium helper exists", "async def auto_fulfill_telegram_premium_order(order: dict) -> dict" in bot_text)
    record("Premium helper requires telegram_premium product_type/category", "telegram_premium" in premium_helper and "not_telegram_premium_order" in premium_helper)
    record("Premium helper requires paid payment", 'order_payment_status(order) != "paid"' in premium_helper and "payment_not_paid" in premium_helper)
    record("maybe_auto_fulfill_paid_order checks payment_status paid before helper", 'order_payment_status(order) != "paid"' in maybe_block and maybe_block.find('order_payment_status(order) != "paid"') < maybe_block.find("helpers = {"))
    record("get_telegram does not call supplier POST directly", "fazercards_post_order" not in get_telegram_block and ".post(" not in get_telegram_block)
    record("choose_payment does not call supplier POST directly", "fazercards_post_order" not in choose_payment_block and "FAZERCARDS_TELEGRAM_PREMIUM_BUY_ENDPOINT" not in choose_payment_block)
    record("invoice creation does not call supplier POST", "fazercards_post_order" not in invoice_block and "FAZERCARDS_TELEGRAM_PREMIUM_BUY_ENDPOINT" not in invoice_block)
    record("FazerCards Premium POST is only in Premium helper via shared post helper", "FAZERCARDS_TELEGRAM_PREMIUM_BUY_ENDPOINT" in premium_helper and bot_text.count("FAZERCARDS_TELEGRAM_PREMIUM_BUY_ENDPOINT") <= 3)
    record("Telegram sync/diagnostics/catalog use readonly GET not purchase POST", "client.post" not in sync_block + diagnostics_block and "fazercards_post_order" not in sync_block + diagnostics_block)
    record("order_already_fulfilled blocks duplicate supplier_order_id/auto_fulfilled_at/issued", all(x in already_block for x in ('"supplier_order_id"', '"auto_fulfilled_at"', '"issued"', '"auto_issued"')))
    record("Premium helper checks duplicate fulfillment before POST", "order_already_fulfilled(order)" in premium_helper and premium_helper.find("order_already_fulfilled(order)") < premium_helper.find("fazercards_post_order"))
    record("retry only available for paid failed/manual_required without fulfilled markers", 'order_payment_status(order) == "paid"' in retry_keyboard_block and "manual_required" in retry_keyboard_block and "failed" in retry_keyboard_block and "not order_already_fulfilled(order)" in retry_keyboard_block)
    record("Premium recipient uses telegram_recipient_username and normalization", "telegram_recipient_username" in premium_helper and "normalize_telegram_recipient_username" in premium_helper and "telegram_premium_recipient_invalid" in premium_helper)
    record("Premium supplier recipient does not use tg_handle", "tg_handle" not in premium_helper)
    record("Premium success saved telegram_recipient_username does not use tg_handle", 'fields["telegram_recipient_username"] = normalize_telegram_recipient_username(order.get("telegram_recipient_username") or order.get("recipient") or "")' in maybe_block and 'order.get("telegram_recipient_username") or order.get("recipient") or order.get("tg_handle")' not in maybe_block)
    record("Premium invalid recipient falls back to manual_required", "telegram_premium_recipient_invalid" in premium_helper and "manual_fallback" in premium_helper and "manual_required" in maybe_block)
    record("Stars supplier recipient does not use tg_handle", "tg_handle" not in stars_helper)
    record("Telegram recipient normalizer supports @ and t.me forms", all(x in function_block(bot_text, "normalize_telegram_recipient_username") for x in ("https?://t\\.me/", "t\\.me/", "lstrip(\"@\")", "[A-Za-z0-9_]{5,32}")))
    record("Premium duration uses duration_months fallback and validates missing", "duration_months" in premium_helper and "months" in premium_helper and "quantity" in premium_helper and "telegram_premium_duration_missing" in premium_helper)
    record("Premium supplier payload includes product/card id duration and telegram_username", all(x in premium_helper for x in ("telegram_username", "product_id", "card_id", "duration_months", "months")))
    record("Premium success client text says Premium sent", "Premium отправлен на указанный аккаунт" in client_text_block)
    record("Premium failure client text uses manual fallback", "Мы скоро оформим Premium" in client_text_block)
    record("Premium success persists issued status", 'fulfillment_status": "issued"' in maybe_block and 'status": "issued"' in maybe_block)
    record("Premium failure persists manual_required paid_waiting_manual_issue", "manual_required" in maybe_block and "paid_waiting_manual_issue" in maybe_block)
    record("Premium success saves normalized recipient and duration", "telegram_recipient_username" in maybe_block and "duration_months" in maybe_block and "normalize_telegram_recipient_username" in maybe_block)
    record("Orders chat receives Premium start/success/failure", "📦 Автовыдача Telegram Premium запущена" in maybe_block and "✅ <b>Telegram Premium оформлен</b>" in admin_text_block and "⚠️ <b>Автовыдача Telegram Premium не удалась" in admin_text_block)
    record("Premium supplier payload does not use tg_handle", "tg_handle" not in premium_helper)
    record("Supplier validation error reports missing telegram_username safely", "supplier_validation_error: missing telegram_username" in function_block(bot_text, "fazercards_api_error") and "api_key" not in function_block(bot_text, "fazercards_api_error") and "token" not in function_block(bot_text, "fazercards_api_error"))
    record("Tech chat receives Premium errors without tokens", "FazerCards Telegram Premium fulfillment failed" in notify_block and "api_key" not in notify_block and "token" not in notify_block)
    record("Payment chat is not used for auto fulfillment result", "get_payments_chat_id" not in notify_block and "PAYMENTS_CHAT_ID" not in notify_block)
    record("CRM card shows Premium supplier and fulfillment fields", all(x in order_card_block for x in ("Категория", "Товар", "Получатель", "Статус выдачи", "Поставщик", "Заказ у поставщика")))
    record("Stars helper still uses same recipient normalization baseline", "normalize_telegram_recipient_username" in stars_helper)



def check_unified_stock(bot_text: str, config_example_text: str) -> None:
    apple_helper = function_block(bot_text, "auto_fulfill_apple_id_order")
    order_keyboard = function_block(bot_text, "order_card_keyboard")
    stock_list = function_block(bot_text, "stock_list_text")
    record("Unified stock file helpers exist", "STOCK_FILE" in bot_text and "def load_stock()" in bot_text and "def save_stock(items" in bot_text and '"category"' in function_block(bot_text, "normalize_stock_item"))
    record("Stock settings exist", '"stock"' in config_example_text and '"categories"' in config_example_text and '"fallback_to_supplier"' in config_example_text)
    record("Stock category toggles callbacks exist", "admin_stock_toggle_enabled:" in bot_text and "admin_stock_toggle_fallback:" in bot_text and "save_stock_category_settings" in bot_text)
    record("Stock disabled prevents stock lookup in auto fulfillment", 'if apple_stock_settings.get("enabled") else None' in apple_helper and "stock_empty_supplier_disabled" in apple_helper)
    stock_issue_block = function_block(bot_text, "issue_apple_id_order_from_stock")
    stock_callback_block = callback_branch_block(bot_text, 'elif data.startswith("order_issue_stock:")')
    record("Stock disabled hides order issue button", "is_stock_enabled_for_category" in order_keyboard and "📦 Выдать со склада" in order_keyboard)
    record("Apple ID stock issue has no undefined apple_stock_settings", "apple_stock_settings" not in stock_issue_block and ('stock_category_settings("apple_id")' in stock_issue_block or 'is_stock_enabled_for_category("apple_id")' in stock_issue_block))
    record("Apple ID stock disabled callback is handled without tech error", 'error == "stock_disabled"' in stock_callback_block and "Склад Apple ID выключен" in stock_callback_block and stock_callback_block.find('error == "stock_disabled"') < stock_callback_block.find("Apple ID stock issue failed"))
    record("Stock enabled checks stock before supplier POST", apple_helper.find("find_available_apple_id_stock_code") != -1 and apple_helper.find("fazercards_post_order") != -1 and apple_helper.find("find_available_apple_id_stock_code") < apple_helper.find("fazercards_post_order"))
    record("Stock fallback controls supplier calls", "fallback_to_supplier" in apple_helper and "stock_empty_supplier_disabled" in apple_helper)
    record("Apple ID migration to unified stock exists", "migrate_apple_id_stock_to_unified" in bot_text and "migrate_apple_id_stock_item" in bot_text and "APPLE_ID_STOCK_FILE" in bot_text and "STOCK_FILE" in bot_text)
    record("Unified stock admin category sections exist", all(x in bot_text for x in ("Apple ID", "Telegram Stars", "Telegram Premium", "eSIM")) and "admin_stock_category:" in bot_text)
    record("Stock privacy masks codes outside delivery", "mask_giftcard_code" in function_block(bot_text, "stock_item_summary_text") and "👁 Показать код" in bot_text and "mask_giftcard_code" in bot_text)


def check_fazercards_stock_sync(bot_text: str, config_example_text: str) -> None:
    apple_helper = function_block(bot_text, "auto_fulfill_apple_id_order")
    fetch_block = function_block(bot_text, "fetch_fazercards_orders")
    sync_block = function_block(bot_text, "sync_fazercards_orders_to_stock")
    parser_block = function_block(bot_text, "parse_fazercards_orders_response")
    upsert_block = function_block(bot_text, "upsert_stock_item_from_fazercards_order")
    report_block = function_block(bot_text, "fazercards_stock_sync_report_text")
    callback_block = callback_branch_block(bot_text, 'elif data == "admin_stock_sync_fazercards"')
    record("FazerCards orders sync uses read-only GET", "async def fetch_fazercards_orders" in bot_text and "client.get" in fetch_block and "client.post" not in fetch_block)
    record("FazerCards stock sync avoids purchase helpers", "fazercards_post_order" not in sync_block and "/giftcards/order" not in sync_block and "client.post" not in sync_block)
    record("FazerCards orders parser supports common containers", all(x in parser_block for x in ('("data",)', '("data", "items")', '("data", "orders")', '("result",)', '("result", "items")', '("result", "orders")', '("orders",)', '("items",)')))
    record("FazerCards order upsert exists and preserves used/invalid", "def upsert_stock_item_from_fazercards_order" in bot_text and "supplier_order_id" in upsert_block and 'current_status == "used"' in upsert_block and 'current_status == "invalid"' in upsert_block)
    record("FazerCards upsert pending can become available", 'new_status = "available"' in upsert_block and 'new_status = "pending"' in upsert_block and "code_key" in upsert_block)
    record("FazerCards sync admin UI exists with admin/owner guard", "🔄 Обновить склад из FazerCards" in bot_text and "admin_stock_sync_fazercards" in bot_text and "has_admin_access(query.from_user) or has_owner_access(query.from_user)" in callback_block)
    details_block = function_block(bot_text, "fetch_fazercards_order_details")
    refresh_block = function_block(bot_text, "refresh_fazercards_pending_stock_item")
    stock_list_block = function_block(bot_text, "stock_list_text")
    stock_keyboard_block = function_block(bot_text, "stock_list_keyboard")
    pending_check_block = callback_branch_block(bot_text, 'elif data.startswith("admin_stock_check_pending:")')
    record("FazerCards sync fetches details for pending supplier orders", "refresh_fazercards_pending_stock_item" in bot_text and 'await refresh_fazercards_pending_stock_item(str(item.get("supplier_order_id")))' in sync_block)
    record("FazerCards details lookup uses only GET", "client.get" in details_block and "client.post" not in details_block and "fazercards_post_order" not in details_block)
    record("FazerCards details upsert keeps supplier_order_id for same stock item", 'details.setdefault("supplier_order_id", supplier_order_id)' in refresh_block and "supplier_order_id" in upsert_block)
    record("FazerCards pending becomes available when details contain code", 'new_status = "available"' in upsert_block and '"delivery_code"' in bot_text and '"activation_code"' in bot_text and '"redeem_code"' in bot_text and '"voucher_code"' in bot_text)
    record("FazerCards details lookup does not create duplicate stock item", 'if str(item.get("supplier_order_id") or "").strip() == supplier_order_id' in upsert_block and "existing = item; break" in upsert_block)
    record("FazerCards sync report shows counters", all(x in report_block for x in ("checked", "added", "updated", "already", "skipped", "errors", "became_available", "still_pending", "became_used", "missing_code")))
    record("FazerCards pending response_shape stores only keys", "supplier_response_shape(order_data)" in upsert_block and "last_response_shape" in upsert_block and "stock_field_label('response_shape')" in stock_list_block)
    record("FazerCards pending supplier check button exists", "🔎 Проверить у поставщика" in stock_keyboard_block and "fetch_fazercards_order_details" in bot_text and "refresh_fazercards_pending_stock_item(supplier_order_id)" in pending_check_block)
    record("FazerCards sync report masks gift card codes", "mask_giftcard_code" in report_block and "delivery_code" in report_block)
    record("FazerCards stock_sync config exists disabled by default", '"stock_sync"' in config_example_text and '"fazercards_enabled": false' in config_example_text and all(x in config_example_text for x in ('"last_run_at"', '"last_ok_at"', '"last_error"')))
    post_block = function_block(bot_text, "fazercards_post_order")
    shape_block = function_block(bot_text, "supplier_response_shape")
    giftcard_block = function_block(bot_text, "giftcard_fields_from_response")
    record("FazerCards POST accepts idempotency_key", "idempotency_key: str | None = None" in post_block and 'headers["idempotency-key"]' in post_block)
    record("Apple ID supplier POST passes idempotency_key", "idempotency_key=idempotency_key" in apple_helper and "slik-mobile:apple_id" in apple_helper)
    record("Apple ID supplier idempotency key is saved before POST", "supplier_idempotency_key=idempotency_key" in apple_helper and apple_helper.find("supplier_idempotency_key=idempotency_key") < apple_helper.find("fazercards_post_order(FAZERCARDS_GIFTCARDS_ORDER_ENDPOINT"))
    record("Apple ID retry reuses supplier_idempotency_key", 'order.get("supplier_idempotency_key") or f"slik-mobile:apple_id:' in apple_helper)
    record("FazerCards response shape expands cards/items safely", all(x in shape_block for x in ('("order", "cards")', '("data", "cards")', '("result", "cards")', '("order", "items")', '("data", "items")', '("result", "items")', ': empty list', '[0] keys')))
    record("FazerCards gift card parser supports order.cards alternates", all(x in giftcard_block for x in ("delivery_code", "activation_code", "card_code", "redeem_code", "voucher_code", "serial", "value", "number", "key", "secret", "token", "security_code", "cards", "items", "codes", "keys", "vouchers")) and "dict" in giftcard_block and "list" in giftcard_block)
    looks_like_block = function_block(bot_text, "looks_like_giftcard_code")
    sanitized_block = function_block(bot_text, "sanitized_supplier_response")
    record("FazerCards parser has soft string-code helper", "def looks_like_giftcard_code" in bot_text and all(x in looks_like_block for x in ("len(text) < 6", "isalnum", "plain_text_markers")))
    record("FazerCards parser reads order.cards[0] string", '"cards"' in giftcard_block and "looks_like_giftcard_code(value)" in giftcard_block and "fields[\"giftcard_code\"] = value.strip()" in giftcard_block)
    record("FazerCards parser reads data.cards[0] string", '"data"' in shape_block and '"cards"' in giftcard_block and "parent_key in string_code_container_keys" in giftcard_block)
    record("FazerCards parser reads result.cards[0] string", '"result"' in shape_block and '"cards"' in giftcard_block and "parent_key in string_code_container_keys" in giftcard_block)
    record("FazerCards parser does not use title/status/category_name as string code", '"title"' not in giftcard_block and '"status"' not in giftcard_block and '"category_name"' not in giftcard_block and "string_code_container_keys" in giftcard_block)
    record("FazerCards response_shape shows string type and list length only", '"{label} length: {len(current)}"' in shape_block and '"{label}[0] type: {type(current[0]).__name__}"' in shape_block and "str(current[0])" not in shape_block)
    record("FazerCards sync updates pending by supplier_order_id without duplicates", 'if str(item.get("supplier_order_id") or "").strip() == supplier_order_id' in upsert_block and "existing = item; break" in upsert_block and 'existing or {"id":' in upsert_block)
    record("FazerCards pending becomes available after cards[0] string", "looks_like_giftcard_code" in giftcard_block and 'elif code_key and category != "unknown":' in upsert_block and 'new_status = "available"' in upsert_block)
    record("FazerCards full codes are masked in chats/reports", "mask_giftcard_code" in sanitized_block and "sensitive_container_keys" in sanitized_block and "mask_giftcard_code" in report_block and "stock_field_label('response_shape')" in stock_list_block and "str(current[0])" not in shape_block)
    record("FazerCards stock item stores supplier_status", '"supplier_status": supplier_status' in upsert_block and "supplier_success_statuses" in upsert_block)
    record("FazerCards failed statuses invalidate pending only", "supplier_failed_statuses" in upsert_block and 'new_status = "invalid"' in upsert_block and 'current_status == "used"' in upsert_block and upsert_block.find('current_status == "used"') < upsert_block.find('new_status = "invalid"'))
    record("FazerCards sync never POSTs", "client.post" not in sync_block and "fazercards_post_order" not in sync_block)
    record("FazerCards response shape does not include code values", "safe_keys" in shape_block and "str(child)" not in shape_block and "mask_giftcard_code" not in shape_block)
    record("FazerCards periodic stock sync is disabled by config gate", "stock_sync_fazercards_periodic_job" in bot_text and 'settings.get("fazercards_enabled", False)' in bot_text)

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
    check_multiservice_crm(bot_text)
    check_apple_id_rub_market_pricing(bot_text)
    check_telegram_premium_auto_fulfillment(bot_text)
    check_unified_stock(bot_text, config_example_text)
    check_fazercards_stock_sync(bot_text, config_example_text)
    check_run_mvp_contract(run_mvp_text)
    for needle in [
        'ORDERS_CHAT_ID',
        'CLIENT_ACTIVITY_CHAT_ID',
        'NEW_CLIENTS_CHAT_ID',
        'PAYMENTS_CHAT_ID',
        'TECH_ALERTS_CHAT_ID',
        'RATE_CHAT_ID',
        'CASHBACK_ENABLED=false',
    ]:
        check_contains(env_example_text, needle, ".env.example notification routing")
    check_contains(config_example_text, '"notification_chats"', "bot/config.example.json")
    check_contains(config_example_text, '"rate"', "bot/config.example.json")
    check_contains(config_example_text, '"supplier_price_refresh"', "bot/config.example.json")
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
