"""
SLIK Mobile Telegram Bot — Расширенная коммерческая версия
"""

import os
import json
import logging
import datetime
import asyncio
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from telegram import (
    BotCommand,
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from telegram.error import NetworkError, TimedOut

# ─── Логирование ──────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Конфиг ───────────────────────────────────────────────────────────────────

SUPPORT_URL      = "https://t.me/big_zzz"
DEVICE_CHECK_URL = "https://esimaccess.com/esim-compatibility-check/"
OWNER_USERNAME   = "big_zzz"          # главный владелец (без @), нельзя удалить

TZ = ZoneInfo("Asia/Yekaterinburg")  # UTC+5

IMAGES_DIR   = Path(__file__).parent / "images"
BANNER_IMAGE = IMAGES_DIR / "banner.jpg"   # запасной файл для /start
RUSSIA_IMAGE = IMAGES_DIR / "russia.jpg"   # запасной файл для России

CONFIG_FILE    = Path(__file__).parent / "config.json"
ORDERS_FILE    = Path(__file__).parent / "orders.json"
USERS_FILE     = Path(__file__).parent / "users.json"
CRYPTOBOT_API  = "https://pay.crypt.bot/api"

# Экраны с баннерами
BANNER_SCREENS = {
    "start":       "Главное меню",
    "countries":   "Выбор страны",
    "russia":      "Тарифы России",
    "tariff":      "Карточка тарифа",
    "success":     "Заявка принята",
    "instruction": "Инструкция",
    "check":       "Проверка устройства",
    "support":     "Поддержка",
}

# ─── Тарифы ───────────────────────────────────────────────────────────────────

RUSSIA_PLANS = [
    ("1 GB",   "30 дней", "$3",    "plan_1gb"),
    ("3 GB",   "30 дней", "$5",    "plan_3gb"),
    ("5 GB",   "30 дней", "$7",    "plan_5gb"),
    ("10 GB",  "30 дней", "$12.5", "plan_10gb"),
    ("20 GB",  "30 дней", "$21",   "plan_20gb"),
    ("50 GB",  "30 дней", "$51.5", "plan_50gb"),
    ("100 GB", "30 дней", "$82.5", "plan_100gb"),
]
PLAN_MAP = {p[3]: {"gb": p[0], "days": p[1], "price": p[2]} for p in RUSSIA_PLANS}

REFERRAL_REWARD_USD = 1.0
STATUS_LEVELS = [
    (100.0, "VIP"),
    (50.0, "Pro"),
    (10.0, "Explorer"),
    (0.0, "Traveller"),
]

# ─── Состояния диалога ────────────────────────────────────────────────────────

WAITING_PAYMENT, WAITING_NAME, WAITING_TELEGRAM = range(1, 4)
WAITING_BANNER = 10

# ─── Время ────────────────────────────────────────────────────────────────────

def now_str() -> str:
    return datetime.datetime.now(tz=TZ).strftime("%d.%m.%Y %H:%M")

def now_time() -> str:
    return datetime.datetime.now(tz=TZ).strftime("%H:%M")

def local_date() -> datetime.date:
    return datetime.datetime.now(tz=TZ).date()

def parse_price(s: str) -> float:
    try:
        return float(s.replace("$", "").strip())
    except Exception:
        return 0.0

# ─── config.json ──────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "banners":  {},
    "admins":   [],
    "relay":    {},
    "payment":  {"card": "", "cryptobot_token": ""},
}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            for k, v in DEFAULT_CONFIG.items():
                data.setdefault(k, v)
            return data
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ─── orders.json ──────────────────────────────────────────────────────────────

def load_orders() -> list:
    if ORDERS_FILE.exists():
        try:
            return json.loads(ORDERS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save_orders(orders: list) -> None:
    ORDERS_FILE.write_text(
        json.dumps(orders, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ─── users.json ───────────────────────────────────────────────────────────────

def ensure_users_file() -> None:
    if not USERS_FILE.exists():
        save_users({})


def load_users() -> dict:
    ensure_users_file()
    try:
        data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_users(users: dict) -> None:
    USERS_FILE.write_text(
        json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def default_user_profile(user) -> dict:
    return {
        "telegram_id": user.id,
        "username": user.username or "",
        "full_name": user.full_name or "",
        "created_at": now_str(),
        "orders_count": 0,
        "total_spent": 0,
        "bonus_balance": 0,
        "slik_balance": 0,
        "referrals": [],
        "referrer": None,
        "referral_bonus_awarded": False,
        "status": "Traveller",
    }


def format_usd(value) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    return f"${amount:g}"


def calculate_user_status(total_spent: float) -> str:
    for threshold, status in STATUS_LEVELS:
        if total_spent >= threshold:
            return status
    return "Traveller"


def referral_entry_user_id(entry) -> str | None:
    if isinstance(entry, dict):
        user_id = entry.get("user_id")
    else:
        user_id = entry
    return str(user_id) if user_id is not None else None


def ensure_referral_entry(referrer_profile: dict, referred_user) -> None:
    referrals = referrer_profile.setdefault("referrals", [])
    referred_key = str(referred_user.id)
    for entry in referrals:
        if referral_entry_user_id(entry) == referred_key:
            if isinstance(entry, dict):
                entry["username"] = referred_user.username or entry.get("username", "")
                entry["full_name"] = referred_user.full_name or entry.get("full_name", "")
            return
    referrals.append({
        "user_id": referred_user.id,
        "username": referred_user.username or "",
        "full_name": referred_user.full_name or "",
        "joined_at": now_str(),
        "bonus_awarded": False,
    })


def credit_slik_balance(profile: dict, amount: float) -> None:
    balance = round(float(profile.get("slik_balance", profile.get("bonus_balance", 0)) or 0) + amount, 2)
    profile["slik_balance"] = balance
    profile["bonus_balance"] = balance


def register_start_referral(user, referrer_id: int | None) -> None:
    if referrer_id is None or str(referrer_id) == str(user.id):
        return
    users = load_users()
    user_key = str(user.id)
    referrer_key = str(referrer_id)
    profile = users.get(user_key) if isinstance(users.get(user_key), dict) else default_user_profile(user)
    if profile.get("referrer"):
        return
    referrer_profile = users.get(referrer_key)
    if not isinstance(referrer_profile, dict):
        return

    profile["referrer"] = referrer_id
    profile.setdefault("referral_bonus_awarded", False)
    profile["username"] = user.username or ""
    profile["full_name"] = user.full_name or ""
    ensure_referral_entry(referrer_profile, user)
    users[user_key] = profile
    users[referrer_key] = referrer_profile
    save_users(users)


def extract_referrer_id(context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if not context.args:
        return None
    payload = context.args[0].strip()
    if not payload.startswith("ref_"):
        return None
    raw_id = payload.removeprefix("ref_").strip()
    return int(raw_id) if raw_id.isdigit() else None


def award_referral_bonus_if_needed(users: dict, profile: dict, user, order: dict) -> bool:
    if profile.get("referral_bonus_awarded"):
        return False
    referrer_id = profile.get("referrer")
    if not referrer_id or str(referrer_id) == str(user.id):
        return False

    referrer_key = str(referrer_id)
    referrer_profile = users.get(referrer_key)
    if not isinstance(referrer_profile, dict):
        return False

    credit_slik_balance(profile, REFERRAL_REWARD_USD)
    credit_slik_balance(referrer_profile, REFERRAL_REWARD_USD)
    profile["referral_bonus_awarded"] = True
    profile["referral_bonus_order"] = order.get("number")
    profile["referral_bonus_awarded_at"] = now_str()

    ensure_referral_entry(referrer_profile, user)
    for entry in referrer_profile.get("referrals", []):
        if isinstance(entry, dict) and referral_entry_user_id(entry) == str(user.id):
            entry["bonus_awarded"] = True
            entry["first_order_number"] = order.get("number")
            entry["bonus_awarded_at"] = profile["referral_bonus_awarded_at"]
            break

    users[referrer_key] = referrer_profile
    return True


def update_profile_stats_from_orders(user_id: int, profile: dict, orders: list | None = None) -> dict:
    user_orders = orders if orders is not None else get_user_orders(user_id)
    active_orders = [order for order in user_orders if order.get("status") != "cancelled"]
    profile["orders_count"] = len(active_orders)
    profile["total_spent"] = round(sum(parse_price(order.get("price", "0")) for order in active_orders), 2)
    profile["status"] = calculate_user_status(float(profile.get("total_spent") or 0))
    profile.setdefault("slik_balance", profile.get("bonus_balance", 0))
    profile["bonus_balance"] = profile.get("slik_balance", 0)
    return profile


def ensure_user_profile(user) -> dict:
    users = load_users()
    key = str(user.id)
    profile = users.get(key)
    if not isinstance(profile, dict):
        profile = default_user_profile(user)
    else:
        profile.setdefault("telegram_id", user.id)
        profile.setdefault("created_at", now_str())
        profile.setdefault("orders_count", 0)
        profile.setdefault("total_spent", 0)
        profile.setdefault("bonus_balance", 0)
        profile.setdefault("slik_balance", profile.get("bonus_balance", 0))
        profile.setdefault("referrals", [])
        profile.setdefault("referrer", None)
        profile.setdefault("referral_bonus_awarded", False)
        profile["status"] = calculate_user_status(float(profile.get("total_spent") or 0))
        profile["username"] = user.username or ""
        profile["full_name"] = user.full_name or ""
    users[key] = profile
    save_users(users)
    return profile


def record_user_order(user, order: dict) -> None:
    users = load_users()
    key = str(user.id)
    profile = users.get(key) if isinstance(users.get(key), dict) else default_user_profile(user)
    profile["username"] = user.username or ""
    profile["full_name"] = user.full_name or ""
    profile.setdefault("bonus_balance", 0)
    profile.setdefault("slik_balance", profile.get("bonus_balance", 0))
    profile.setdefault("referrals", [])
    profile.setdefault("referrer", None)
    profile.setdefault("referral_bonus_awarded", False)
    profile = update_profile_stats_from_orders(user.id, profile)
    award_referral_bonus_if_needed(users, profile, user, order)
    users[key] = profile
    save_users(users)


def get_user_orders(user_id: int) -> list:
    return [order for order in load_orders() if str(order.get("user_id")) == str(user_id)]


def sync_user_order_stats(user, profile: dict) -> dict:
    profile = update_profile_stats_from_orders(user.id, profile, get_user_orders(user.id))
    users = load_users()
    users[str(user.id)] = profile
    save_users(users)
    return profile


def sync_order_user_stats(user_id: int) -> None:
    users = load_users()
    key = str(user_id)
    profile = users.get(key)
    if not isinstance(profile, dict):
        return
    profile = update_profile_stats_from_orders(user_id, profile, get_user_orders(user_id))
    users[key] = profile
    save_users(users)


def append_order(order: dict) -> dict:
    orders = load_orders()
    order_id = len(orders) + 1
    order["id"]           = order_id
    order["number"]       = f"#{order_id:04d}"
    order["status"]       = "new"
    order["created_at"]   = now_str()
    order["created_date"] = local_date().isoformat()
    orders.append(order)
    save_orders(orders)
    logger.info("Новый заказ: %s", order)
    return order


def update_order_status(order_id: int, status: str) -> dict | None:
    orders = load_orders()
    for o in orders:
        if o["id"] == order_id:
            o["status"]     = status
            o["updated_at"] = now_str()
            save_orders(orders)
            if o.get("user_id") is not None:
                sync_order_user_stats(o["user_id"])
            return o
    return None


# ─── Проверка прав ────────────────────────────────────────────────────────────

def is_owner(user) -> bool:
    if user.username and user.username.lower() == OWNER_USERNAME.lower():
        return True
    admin_env = os.environ.get("ADMIN_CHAT_ID", "").strip()
    if admin_env and str(user.id) == admin_env:
        return True
    return False


def is_admin(user) -> bool:
    if is_owner(user):
        return True
    cfg = load_config()
    for entry in cfg.get("admins", []):
        entry_str = str(entry).lstrip("@").lower()
        if entry_str.isdigit():
            if str(user.id) == entry_str:
                return True
        else:
            if user.username and user.username.lower() == entry_str:
                return True
    return False


def get_admin_chat_id() -> int | None:
    val = os.environ.get("ADMIN_CHAT_ID", "").strip()
    try:
        return int(val) if val else None
    except ValueError:
        return None


# ─── CryptoBot API ────────────────────────────────────────────────────────────

async def crypto_get_me(token: str) -> dict | None:
    """Проверяет токен через /getMe. Возвращает данные приложения или None."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{CRYPTOBOT_API}/getMe",
                headers={"Crypto-Pay-API-Token": token},
            )
            data = r.json()
            return data.get("result") if data.get("ok") else None
    except Exception as e:
        logger.error("CryptoBot getMe error: %s", e)
        return None


async def crypto_create_invoice(token: str, amount: float, description: str, payload: str) -> dict | None:
    """Создаёт инвойс. Возвращает result-объект или None при ошибке."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{CRYPTOBOT_API}/createInvoice",
                headers={"Crypto-Pay-API-Token": token},
                json={
                    "asset":           "USDT",
                    "amount":          str(amount),
                    "description":     description,
                    "payload":         payload,
                    "allow_comments":  False,
                    "allow_anonymous": True,
                },
            )
            data = r.json()
            if data.get("ok"):
                return data["result"]
            logger.error("CryptoBot createInvoice: %s", data)
            return None
    except Exception as e:
        logger.error("CryptoBot createInvoice error: %s", e)
        return None


async def crypto_check_invoice(token: str, invoice_id: int) -> str | None:
    """Возвращает статус инвойса: 'active' | 'paid' | 'expired' | None."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{CRYPTOBOT_API}/getInvoices",
                headers={"Crypto-Pay-API-Token": token},
                params={"invoice_ids": str(invoice_id)},
            )
            data = r.json()
            items = data.get("result", {}).get("items", []) if data.get("ok") else []
            return items[0]["status"] if items else None
    except Exception as e:
        logger.error("CryptoBot getInvoices error: %s", e)
        return None


# ─── Баннеры ──────────────────────────────────────────────────────────────────

def get_banner(screen: str) -> str | None:
    return load_config().get("banners", {}).get(screen)


async def send_screen(
    message,
    screen: str,
    text: str,
    reply_markup,
    local_file: Path | None = None,
    parse_mode: str = "HTML",
):
    """Отправляет экран с баннером (из config) или локальным файлом, иначе текст."""
    file_id = get_banner(screen)
    if file_id:
        try:
            await message.reply_photo(
                photo=file_id, caption=text,
                reply_markup=reply_markup, parse_mode=parse_mode,
            )
            return
        except Exception:
            pass
    if local_file and local_file.exists():
        try:
            await message.reply_photo(
                photo=open(local_file, "rb"), caption=text,
                reply_markup=reply_markup, parse_mode=parse_mode,
            )
            return
        except Exception:
            pass
    await message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)


async def edit_or_send(query, context, text: str, reply_markup, parse_mode="HTML"):
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        await context.bot.send_message(
            chat_id=query.message.chat_id, text=text,
            reply_markup=reply_markup, parse_mode=parse_mode,
        )


# ─── Вспомогательные функции ──────────────────────────────────────────────────

def html_escape(value) -> str:
    return escape(str(value), quote=True)


def user_tag(user) -> str:
    return f"@{user.username}" if user.username else "—"


def user_tag_html(user) -> str:
    return html_escape(user_tag(user))


async def track_action(context, user, action: str, extra: str = "") -> None:
    """Отправляет уведомление в админ-чат о действии клиента."""
    admin_id = get_admin_chat_id()
    if not admin_id:
        return
    text = f"👣 <b>Действие клиента</b>\n\nДействие: {html_escape(action)}"
    if extra:
        text += f"\n{html_escape(extra)}"
    text += (
        f"\n\n👤 Имя: {html_escape(user.full_name)}\n"
        f"📨 Username: {user_tag_html(user)}\n"
        f"🆔 Telegram ID: <code>{user.id}</code>\n"
        f"🕒 Время: {now_str()}"
    )
    try:
        await context.bot.send_message(chat_id=admin_id, text=text, parse_mode="HTML")
    except Exception as e:
        logger.error("track_action error: %s", e)


def format_order_list(orders: list, title: str) -> list[str]:
    STATUS_ICON = {"new": "🆕", "done": "✅", "cancelled": "❌"}
    chunks, current = [], ""
    header = f"{title} (<b>{len(orders)}</b>):\n\n"
    for o in orders:
        icon = STATUS_ICON.get(o.get("status"), "🆕")
        line = (
            f"{icon} <b>{o['number']}</b> · {o.get('created_at', '—')}\n"
            f"   📶 {o.get('gb', '—')} — {o.get('price', '—')}\n"
            f"   👤 {o.get('name', '—')} · {o.get('tg_handle', '—')}\n\n"
        )
        if len(current) + len(line) > 3800:
            chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)
    if not chunks:
        return [f"{title}\n\nПока пусто."]
    chunks[0] = header + chunks[0]
    return chunks


async def send_order_list(message, orders: list, title: str):
    for chunk in format_order_list(orders, title):
        await message.reply_text(chunk, parse_mode="HTML")


# ─── Клавиатуры ───────────────────────────────────────────────────────────────

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 Купить eSIM",          callback_data="buy_esim")],
        [InlineKeyboardButton("👤 Личный кабинет",       callback_data="profile")],
        [InlineKeyboardButton("📱 Проверить устройство", url=DEVICE_CHECK_URL)],
        [InlineKeyboardButton("📖 Инструкция",           callback_data="instructions")],
        [InlineKeyboardButton("👨‍💻 Поддержка",            callback_data="support_screen")],
    ])


def buy_esim_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇷🇺 Россия",              callback_data="region_russia")],
        [InlineKeyboardButton("🌎 Весь мир",             callback_data="region_worldwide")],
        [InlineKeyboardButton("📱 Проверить устройство", url=DEVICE_CHECK_URL)],
        [InlineKeyboardButton("📖 Инструкция",           callback_data="instructions")],
        [InlineKeyboardButton("👨‍💻 Поддержка",            url=SUPPORT_URL)],
        [InlineKeyboardButton("🏠 Главное меню",         callback_data="back_main")],
    ])


def russia_plans_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"📶 {p[0]}  •  {p[2]}", callback_data=p[3])]
        for p in RUSSIA_PLANS
    ]
    rows.append([
        InlineKeyboardButton("⬅️ Назад",       callback_data="buy_esim"),
        InlineKeyboardButton("🏠 Главное меню", callback_data="back_main"),
    ])
    return InlineKeyboardMarkup(rows)


def plan_card_keyboard(plan_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Купить", callback_data=f"buy_{plan_key}")],
        [
            InlineKeyboardButton("⬅️ Назад",       callback_data="region_russia"),
            InlineKeyboardButton("🏠 Главное меню", callback_data="back_main"),
        ],
    ])


def payment_keyboard(plan_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 CryptoBot",        callback_data="pay_crypto")],
        [InlineKeyboardButton("💳 Переводом на карту", callback_data="pay_card")],
        [
            InlineKeyboardButton("⬅️ Назад",       callback_data=f"back_to_plan_{plan_key}"),
            InlineKeyboardButton("🏠 Главное меню", callback_data="back_main"),
        ],
    ])


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отменить заявку", callback_data="cancel_order")],
    ])


def admin_order_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Выдано",   callback_data=f"done_{order_id}"),
        InlineKeyboardButton("❌ Отменено", callback_data=f"cancelled_{order_id}"),
    ]])


def profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Мои заказы",       callback_data="profile_orders")],
        [InlineKeyboardButton("👥 Пригласить друга", callback_data="profile_invite")],
        [InlineKeyboardButton("💰 SLIK Balance",     callback_data="profile_bonuses")],
        [InlineKeyboardButton("⬅️ Назад",            callback_data="back_main")],
    ])


def profile_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data="profile")],
    ])


# ─── Главное меню ─────────────────────────────────────────────────────────────

MAIN_MENU_TEXT = (
    "📶 <b>SLIK Mobile</b>\n\n"
    "Интернет через eSIM за 2 минуты.\n\n"
    "Выберите действие:"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user:
        ensure_user_profile(user)
        register_start_referral(user, extract_referrer_id(context))
    if update.message:
        try:
            await update.message.reply_text("...", reply_markup=ReplyKeyboardRemove())
        except Exception:
            pass

        try:
            await send_screen(
                update.message, "start", MAIN_MENU_TEXT,
                main_menu_keyboard(), local_file=BANNER_IMAGE,
            )
        except Exception:
            await update.message.reply_text(
                MAIN_MENU_TEXT,
                reply_markup=main_menu_keyboard(),
                parse_mode="HTML",
            )
        if not is_admin(user):
            await track_action(context, user, "открыл главное меню")
    elif update.callback_query:
        await edit_or_send(update.callback_query, context, MAIN_MENU_TEXT, main_menu_keyboard())


# ─── Навигационные экраны ─────────────────────────────────────────────────────

async def show_buy_esim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    await edit_or_send(query, context, "🌍 <b>Выберите страну:</b>", buy_esim_keyboard())
    if not is_admin(user):
        await track_action(context, user, "нажал «Купить eSIM»")


async def show_region_russia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    text = "🇷🇺 <b>Россия — тарифы eSIM</b>\n\nВыберите подходящий объём трафика:"
    file_id = get_banner("russia")
    if file_id:
        try:
            await query.message.reply_photo(
                photo=file_id, caption=text,
                reply_markup=russia_plans_keyboard(), parse_mode="HTML",
            )
        except Exception:
            await edit_or_send(query, context, text, russia_plans_keyboard())
    elif RUSSIA_IMAGE.exists():
        try:
            await query.message.reply_photo(
                photo=open(RUSSIA_IMAGE, "rb"), caption=text,
                reply_markup=russia_plans_keyboard(), parse_mode="HTML",
            )
        except Exception:
            await edit_or_send(query, context, text, russia_plans_keyboard())
    else:
        await edit_or_send(query, context, text, russia_plans_keyboard())
    if not is_admin(user):
        await track_action(context, user, "выбрал страну", "Страна: Россия")


async def show_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    plan_key = query.data
    plan = PLAN_MAP[plan_key]
    text = (
        "🇷🇺 <b>Россия</b>\n\n"
        f"📶 Трафик: <b>{plan['gb']}</b>\n"
        f"📅 Срок действия: <b>{plan['days']}</b>\n"
        f"💵 Цена: <b>{plan['price']}</b>\n\n"
        "⚡ Активация за 2 минуты\n"
        "🌍 Работает по всей России\n"
        "📱 Поддержка iPhone и Android с eSIM"
    )
    await edit_or_send(query, context, text, plan_card_keyboard(plan_key))
    if not is_admin(query.from_user):
        await track_action(context, query.from_user, "выбрал тариф",
                           f"Тариф: {plan['gb']} / {plan['days']}\nЦена: {plan['price']}")


async def show_region_worldwide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await edit_or_send(
        query, context,
        (
            "🌎 <b>Международные тарифы</b>\n\n"
            "Тарифы для путешествий по всему миру.\n"
            "Наш менеджер подберёт оптимальный вариант для вашего маршрута."
        ),
        InlineKeyboardMarkup([
            [InlineKeyboardButton("👨‍💻 Написать менеджеру", url=SUPPORT_URL)],
            [
                InlineKeyboardButton("⬅️ Назад",       callback_data="buy_esim"),
                InlineKeyboardButton("🏠 Главное меню", callback_data="back_main"),
            ],
        ]),
    )


async def show_instructions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await edit_or_send(
        query, context,
        (
            "📖 <b>Инструкция по установке eSIM</b>\n\n"
            "1. Перейдите в <b>Настройки → Сотовая связь → Добавить eSIM</b>\n"
            "2. Выберите <b>«Использовать QR-код»</b>\n"
            "3. Отсканируйте полученный QR-код\n"
            "4. Следуйте инструкциям на экране\n\n"
            "Если потребуется помощь — напишите в поддержку."
        ),
        InlineKeyboardMarkup([
            [InlineKeyboardButton("👨‍💻 Поддержка", url=SUPPORT_URL)],
            [
                InlineKeyboardButton("⬅️ Назад",       callback_data="buy_esim"),
                InlineKeyboardButton("🏠 Главное меню", callback_data="back_main"),
            ],
        ]),
    )
    if not is_admin(query.from_user):
        await track_action(context, query.from_user, "открыл инструкцию")


async def show_support_screen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await edit_or_send(
        query, context,
        "👨‍💻 <b>Поддержка</b>\n\nНапишите нашему менеджеру — он поможет с любым вопросом.",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("✉️ Написать менеджеру", url=SUPPORT_URL)],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")],
        ]),
    )
    if not is_admin(query.from_user):
        await track_action(context, query.from_user, "нажал «Поддержка»")


# ─── Личный кабинет ───────────────────────────────────────────────────────────

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    profile = sync_user_order_stats(user, ensure_user_profile(user))
    referrals = profile.get("referrals", [])
    referrals_count = len(referrals) if isinstance(referrals, list) else 0
    text = (
        "👤 <b>Личный кабинет</b>\n\n"
        f"Имя: <b>{html_escape(profile.get('full_name') or user.full_name or '—')}</b>\n"
        f"Telegram ID: <code>{user.id}</code>\n"
        f"Статус: <b>{html_escape(profile.get('status', 'Traveller'))}</b>\n"
        f"Количество заказов: <b>{int(profile.get('orders_count') or 0)}</b>\n"
        f"Сумма покупок: <b>{format_usd(profile.get('total_spent'))}</b>\n"
        f"SLIK Balance: <b>{format_usd(profile.get('slik_balance', profile.get('bonus_balance', 0)))}</b>\n"
        f"Приглашено друзей: <b>{referrals_count}</b>"
    )
    await edit_or_send(query, context, text, profile_keyboard())


def format_user_orders(orders: list) -> list[str]:
    chunks: list[str] = []
    current = "📦 <b>Мои заказы</b>\n\n"
    for order in orders:
        line = (
            f"<b>{html_escape(order.get('number', '—'))}</b> · {html_escape(order.get('created_at', '—'))}\n"
            f"Тариф: {html_escape(order.get('gb', '—'))} / {html_escape(order.get('days', '—'))}\n"
            f"Цена: <b>{html_escape(order.get('price', '—'))}</b>\n"
            f"Статус: {html_escape(order.get('status', 'new'))}\n\n"
        )
        if len(current) + len(line) > 3800:
            chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)
    return chunks


async def show_my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    orders = get_user_orders(query.from_user.id)
    if not orders:
        await edit_or_send(
            query, context,
            "📦 <b>Мои заказы</b>\n\nУ вас пока нет заказов.",
            profile_back_keyboard(),
        )
        return

    chunks = format_user_orders(orders)
    await edit_or_send(query, context, chunks[0], profile_back_keyboard())
    for chunk in chunks[1:]:
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=chunk,
            parse_mode="HTML",
            reply_markup=profile_back_keyboard(),
        )


async def get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    if getattr(context.bot, "username", None):
        return context.bot.username
    bot_info = await context.bot.get_me()
    return bot_info.username or ""


async def show_profile_invite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    username = await get_bot_username(context)
    referral_link = f"https://t.me/{username}?start=ref_{query.from_user.id}" if username else f"/start ref_{query.from_user.id}"
    text = (
        "👥 <b>Пригласить друга</b>\n\n"
        "Поделитесь ссылкой с другом. После его первой заявки вы оба получите "
        f"<b>{format_usd(REFERRAL_REWARD_USD)}</b> на SLIK Balance.\n\n"
        f"Ваша реферальная ссылка:\n<code>{html_escape(referral_link)}</code>"
    )
    await edit_or_send(query, context, text, profile_back_keyboard())


async def show_profile_bonuses(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    profile = sync_user_order_stats(query.from_user, ensure_user_profile(query.from_user))
    referrals = profile.get("referrals", [])
    referrals_count = len(referrals) if isinstance(referrals, list) else 0
    awarded_count = sum(
        1 for entry in referrals
        if isinstance(entry, dict) and entry.get("bonus_awarded")
    )
    text = (
        "🎁 <b>SLIK Balance</b>\n\n"
        f"Баланс: <b>{format_usd(profile.get('slik_balance', profile.get('bonus_balance', 0)))}</b>\n"
        f"Приглашено друзей: <b>{referrals_count}</b>\n"
        f"Бонус начислен за друзей: <b>{awarded_count}</b>\n\n"
        f"Бонус за первую заявку друга: <b>{format_usd(REFERRAL_REWARD_USD)}</b> вам и другу."
    )
    await edit_or_send(query, context, text, profile_back_keyboard())


# ─── Диалог покупки ───────────────────────────────────────────────────────────

async def start_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    plan_key = query.data.replace("buy_", "")
    plan = PLAN_MAP.get(plan_key)
    if not plan:
        return ConversationHandler.END
    context.user_data["plan_key"] = plan_key
    context.user_data["plan"]     = plan

    cfg = load_config()
    card    = cfg["payment"].get("card", "")
    cryptobot = cfg["payment"].get("cryptobot", "")
    text = (
        f"💳 <b>Выберите способ оплаты</b>\n\n"
        f"📶 Тариф: <b>{plan['gb']} / {plan['days']}</b>\n"
        f"💵 Цена: <b>{plan['price']}</b>"
    )
    await query.message.reply_text(
        text, parse_mode="HTML",
        reply_markup=payment_keyboard(plan_key),
    )
    if not is_admin(query.from_user):
        await track_action(context, query.from_user, "нажал «Купить»",
                           f"Тариф: {plan['gb']} / {plan['days']}\nЦена: {plan['price']}")
    return WAITING_PAYMENT


async def choose_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    plan = context.user_data.get("plan", {})

    if data == "pay_crypto":
        cfg = load_config()
        token = cfg["payment"].get("cryptobot_token", "").strip()
        context.user_data["payment_method"] = "CryptoBot"
        if not token:
            await query.message.reply_text(
                "🤖 <b>CryptoBot</b>\n\nОплата через CryptoBot ещё не настроена.\n\n"
                "Выберите другой способ или напишите менеджеру.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Переводом на карту",  callback_data="pay_card")],
                    [InlineKeyboardButton("👨‍💻 Написать менеджеру", url=SUPPORT_URL)],
                    [InlineKeyboardButton("❌ Отменить заявку",     callback_data="cancel_order")],
                ]),
            )
            return WAITING_PAYMENT

        amount      = parse_price(plan.get("price", "0"))
        description = f"eSIM {plan.get('gb')} / {plan.get('days')} — SLIK Mobile"
        payload     = f"user_{query.from_user.id}"

        await query.message.reply_text("⏳ Создаю счёт...")
        invoice = await crypto_create_invoice(token, amount, description, payload)

        if not invoice:
            await query.message.reply_text(
                "❌ Не удалось создать счёт через CryptoBot. Попробуйте позже или выберите другой способ оплаты.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Переводом на карту",  callback_data="pay_card")],
                    [InlineKeyboardButton("❌ Отменить заявку",     callback_data="cancel_order")],
                ]),
            )
            return WAITING_PAYMENT

        invoice_id  = invoice["invoice_id"]
        pay_url     = invoice["pay_url"]
        context.user_data["invoice_id"] = invoice_id

        await query.message.reply_text(
            f"🤖 <b>Оплата через CryptoBot</b>\n\n"
            f"📶 Тариф: <b>{plan.get('gb')} / {plan.get('days')}</b>\n"
            f"💵 Сумма: <b>{amount} USDT</b>\n\n"
            "Нажмите кнопку ниже для оплаты.\n"
            "После перевода нажмите «✅ Проверить оплату».",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"💸 Оплатить {amount} USDT", url=pay_url)],
                [InlineKeyboardButton("✅ Проверить оплату",
                                      callback_data=f"check_payment_{invoice_id}")],
                [InlineKeyboardButton("❌ Отменить заявку", callback_data="cancel_order")],
            ]),
        )
        return WAITING_PAYMENT

    elif data == "payment_done":
        await query.message.reply_text(
            "📝 <b>Оформление заявки</b>\n\nКак вас зовут?",
            parse_mode="HTML", reply_markup=cancel_keyboard(),
        )
        return WAITING_NAME

    elif data == "pay_card":
        cfg = load_config()
        card = cfg["payment"].get("card", "")
        context.user_data["payment_method"] = "Карта"
        card_text = f"<code>{card}</code>" if card else "Реквизиты карты уточните у менеджера"
        await query.message.reply_text(
            f"💳 <b>Перевод на карту</b>\n\n"
            f"Сумма: <b>{plan.get('price', '—')}</b>\n\n"
            f"Карта: {card_text}\n\n"
            "Переведите сумму и нажмите «Я оплатил».",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Я оплатил",       callback_data="payment_done")],
                [InlineKeyboardButton("❌ Отменить заявку", callback_data="cancel_order")],
            ]),
        )
        return WAITING_PAYMENT

    elif data.startswith("check_payment_"):
        invoice_id = int(data.replace("check_payment_", ""))
        cfg   = load_config()
        token = cfg["payment"].get("cryptobot_token", "").strip()
        await query.answer("⏳ Проверяю оплату...", show_alert=False)
        status = await crypto_check_invoice(token, invoice_id)
        if status == "paid":
            await query.message.reply_text(
                "✅ <b>Оплата подтверждена!</b>\n\nОформляем вашу заявку.\n\nКак вас зовут?",
                parse_mode="HTML",
                reply_markup=cancel_keyboard(),
            )
            return WAITING_NAME
        elif status == "expired":
            await query.message.reply_text(
                "⏱ Счёт истёк. Пожалуйста, начните оформление заново.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")],
                ]),
            )
            return ConversationHandler.END
        else:
            await query.message.reply_text(
                "⏳ <b>Оплата ещё не поступила.</b>\n\nПодождите несколько секунд и попробуйте снова.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Проверить снова",
                                          callback_data=f"check_payment_{invoice_id}")],
                    [InlineKeyboardButton("❌ Отменить заявку", callback_data="cancel_order")],
                ]),
            )
        return WAITING_PAYMENT

    elif data.startswith("back_to_plan_"):
        plan_key = data.replace("back_to_plan_", "")
        plan_data = PLAN_MAP.get(plan_key)
        if plan_data:
            text = (
                "🇷🇺 <b>Россия</b>\n\n"
                f"📶 Трафик: <b>{plan_data['gb']}</b>\n"
                f"📅 Срок действия: <b>{plan_data['days']}</b>\n"
                f"💵 Цена: <b>{plan_data['price']}</b>"
            )
            await edit_or_send(query, context, text, plan_card_keyboard(plan_key))
        return ConversationHandler.END

    return WAITING_PAYMENT


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Пожалуйста, введите ваше имя:", reply_markup=cancel_keyboard())
        return WAITING_NAME
    context.user_data["name"] = name
    await update.message.reply_text(
        f"Отлично, <b>{html_escape(name)}</b>! 👋\n\nУкажите ваш Telegram для связи\n(например, @username):",
        parse_mode="HTML", reply_markup=cancel_keyboard(),
    )
    return WAITING_TELEGRAM


async def get_telegram(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tg_handle = update.message.text.strip()
    if not tg_handle:
        await update.message.reply_text("Пожалуйста, укажите ваш Telegram:", reply_markup=cancel_keyboard())
        return WAITING_TELEGRAM

    user    = update.effective_user
    plan    = context.user_data["plan"]
    name    = context.user_data["name"]
    payment = context.user_data.get("payment_method", "—")

    order = append_order({
        "gb":             plan["gb"],
        "days":           plan["days"],
        "price":          plan["price"],
        "plan_key":       context.user_data["plan_key"],
        "payment_method": payment,
        "name":           name,
        "tg_handle":      tg_handle,
        "user_id":        user.id,
    })
    record_user_order(user, order)

    await update.message.reply_text(
        (
            "✅ <b>Заявка принята</b>\n\n"
            f"🧾 Номер заказа: <b>{order['number']}</b>\n\n"
            f"📶 Тариф: <b>{plan['gb']} / {plan['days']}</b>\n"
            f"💵 Цена: <b>{plan['price']}</b>\n\n"
            "Спасибо за заявку.\n\n"
            "Менеджер свяжется с вами в течение нескольких минут и отправит вашу eSIM.\n\n"
            "⚡ Среднее время обработки — до 5 минут."
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👨‍💻 Написать менеджеру", url=SUPPORT_URL)],
            [InlineKeyboardButton("🏠 Главное меню",        callback_data="back_main")],
        ]),
    )
    await notify_admin(context, order)
    if not is_admin(user):
        await track_action(context, user, "создал заявку",
                           f"Тариф: {plan['gb']} / {plan['days']}\nЦена: {plan['price']}\nОплата: {payment}")
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_order_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.message.reply_text(
        "Заявка отменена.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")],
        ]),
    )
    return ConversationHandler.END


# ─── Уведомления администратору ───────────────────────────────────────────────

async def send_admin_order_message(
    context: ContextTypes.DEFAULT_TYPE,
    admin_id: int,
    text: str,
    order_id: int,
    max_attempts: int = 3,
) -> bool:
    """Отправляет уведомление о заказе админу с retry при сетевых сбоях."""
    for attempt in range(1, max_attempts + 1):
        try:
            await context.bot.send_message(
                chat_id=admin_id, text=text, parse_mode="HTML",
                reply_markup=admin_order_keyboard(order_id),
            )
            logger.info(
                "Админ-уведомление по заказу %s успешно отправлено в чат %s с попытки %s",
                order_id, admin_id, attempt,
            )
            return True
        except (TimedOut, NetworkError) as e:
            logger.warning(
                "Админ-уведомление по заказу %s не отправлено в чат %s: попытка %s/%s, причина: %s",
                order_id, admin_id, attempt, max_attempts, e,
            )
            if attempt < max_attempts:
                await asyncio.sleep(attempt)
        except Exception as e:
            logger.error(
                "Админ-уведомление по заказу %s не отправлено в чат %s: причина: %s",
                order_id, admin_id, e,
            )
            return False

    logger.error(
        "Админ-уведомление по заказу %s не отправлено в чат %s после %s попыток",
        order_id, admin_id, max_attempts,
    )
    return False


async def notify_admin(context: ContextTypes.DEFAULT_TYPE, order: dict) -> None:
    admin_id = get_admin_chat_id()
    order_number = order.get("number", "—")
    order_id = order.get("id")
    if not admin_id:
        logger.warning(
            "Админ-уведомление по заказу %s не отправлено: ADMIN_CHAT_ID не задан",
            order_number,
        )
        return
    if order_id is None:
        logger.error(
            "Админ-уведомление по заказу %s не отправлено: в заказе нет id",
            order_number,
        )
        return

    payment_method = order.get("payment_method")
    payment_line = f"💳 Оплата: <b>{html_escape(payment_method)}</b>\n" if payment_method else ""
    text = (
        "🔥 <b>Новый заказ</b>\n\n"
        f"Номер заказа: <b>{html_escape(order_number)}</b>\n\n"
        f"📶 Тариф: <b>{html_escape(order.get('gb', '—'))} / {html_escape(order.get('days', '—'))}</b>\n"
        f"💵 Цена: <b>{html_escape(order.get('price', '—'))}</b>\n"
        f"{payment_line}\n"
        f"👤 Имя: <b>{html_escape(order.get('name', '—'))}</b>\n"
        f"📨 Telegram: <b>{html_escape(order.get('tg_handle', '—'))}</b>\n\n"
        f"🕒 {html_escape(order.get('created_at', '—'))}"
    )
    await send_admin_order_message(context, admin_id, text, order_id)


async def handle_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_admin(query.from_user):
        await query.answer("⛔ Нет доступа.", show_alert=True)
        return

    data     = query.data
    action   = "done" if data.startswith("done_") else "cancelled"
    order_id = int(data.split("_", 1)[1])

    order = update_order_status(order_id, action)
    if not order:
        await query.answer("Заявка не найдена.", show_alert=True)
        return

    time_now = now_time()

    if action == "done":
        await query.answer("✅ Выдано")
        await query.edit_message_text(
            f"✅ <b>Заказ {order['number']} выдан</b>\n\nДата выдачи: {time_now}",
            parse_mode="HTML",
        )
        client_text = "✅ <b>Ваш заказ обработан.</b>\n\nМенеджер скоро отправит данные eSIM.\n\nЕсли у вас возникли вопросы — напишите в поддержку."
    else:
        await query.answer("❌ Отменено")
        await query.edit_message_text(
            f"❌ <b>Заказ {order['number']} отменён</b>\n\nВремя: {time_now}",
            parse_mode="HTML",
        )
        client_text = "❌ <b>Заказ отменён.</b>\n\nДля уточнения свяжитесь с поддержкой."

    try:
        await context.bot.send_message(
            chat_id=order["user_id"], text=client_text, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👨‍💻 Поддержка",    url=SUPPORT_URL)],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")],
            ]),
        )
    except Exception as e:
        logger.error("Не удалось уведомить клиента: %s", e)


# ─── Ответ админа клиенту через reply ────────────────────────────────────────

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Если администратор отвечает reply на уведомление в админ-чате — пересылаем клиенту."""
    msg = update.message
    if not msg or not msg.reply_to_message:
        return

    admin_id = get_admin_chat_id()
    if not admin_id or msg.chat_id != admin_id:
        return

    if not is_admin(msg.from_user):
        return

    replied_id = str(msg.reply_to_message.message_id)
    cfg = load_config()
    user_id = cfg.get("relay", {}).get(replied_id)
    if not user_id:
        return

    reply_text = msg.text or msg.caption or ""
    if not reply_text.strip():
        return

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"👨‍💻 <b>Ответ менеджера:</b>\n\n{reply_text}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👨‍💻 Поддержка",    url=SUPPORT_URL)],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")],
            ]),
        )
        await msg.reply_text("✅ Ответ отправлен клиенту.")
    except Exception as e:
        await msg.reply_text(f"❌ Не удалось отправить: {e}")


# ─── Неизвестное сообщение от клиента → в админ-чат ──────────────────────────

async def handle_unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg or not msg.text:
        return

    user = update.effective_user
    admin_id = get_admin_chat_id()

    # Игнорировать сообщения из самого админ-чата
    if admin_id and msg.chat_id == admin_id:
        return

    # Игнорировать команды
    if msg.text.startswith("/"):
        return

    # Игнорировать самих администраторов
    if is_admin(user):
        return

    # Ответить клиенту
    await msg.reply_text(
        "🤖 Я не понял сообщение.\n\nЯ уже позвал менеджера — он скоро поможет.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👨‍💻 Поддержка",    url=SUPPORT_URL)],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")],
        ]),
    )

    # Уведомить в админ-чат
    if admin_id:
        notification = (
            "💬 <b>Новое сообщение от клиента</b>\n\n"
            f"👤 Имя: {user.full_name}\n"
            f"📨 Username: {user_tag(user)}\n"
            f"🆔 Telegram ID: <code>{user.id}</code>\n\n"
            f"Сообщение:\n<i>«{msg.text}»</i>\n\n"
            "Ответьте на это сообщение <b>reply / свайп</b>, чтобы отправить ответ клиенту."
        )
        try:
            sent = await context.bot.send_message(
                chat_id=admin_id, text=notification, parse_mode="HTML",
            )
            # Сохраняем маппинг message_id → user_id
            cfg = load_config()
            relay = cfg.setdefault("relay", {})
            relay[str(sent.message_id)] = user.id
            # Ограничиваем размер relay-карты
            if len(relay) > 2000:
                for k in list(relay.keys())[:1000]:
                    del relay[k]
            save_config(cfg)
        except Exception as e:
            logger.error("Ошибка relay-уведомления: %s", e)


# ─── Баннеры ──────────────────────────────────────────────────────────────────

async def cmd_banners(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    cfg = load_config()
    banners = cfg.get("banners", {})
    lines = []
    for key, label in BANNER_SCREENS.items():
        status = "✅" if banners.get(key) else "❌"
        lines.append(f"{status} <b>{label}</b> — <code>/setbanner {key}</code>")
    await update.message.reply_text(
        "🖼 <b>Баннеры</b>\n\n" + "\n".join(lines) +
        "\n\n✅ — установлен  |  ❌ — не задан\n\n"
        "Чтобы удалить: <code>/delbanner &lt;экран&gt;</code>",
        parse_mode="HTML",
    )


async def cmd_setbanner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return ConversationHandler.END
    args = context.args or []
    if not args or args[0] not in BANNER_SCREENS:
        screens = "\n".join(f"  /setbanner {k}" for k in BANNER_SCREENS)
        await update.message.reply_text(
            f"📸 Укажите экран:\n\n{screens}", parse_mode="HTML",
        )
        return ConversationHandler.END
    screen = args[0]
    context.user_data["banner_screen"] = screen
    await update.message.reply_text(
        f"📸 Отправьте изображение для экрана <b>{BANNER_SCREENS[screen]}</b>:",
        parse_mode="HTML",
    )
    return WAITING_BANNER


async def receive_banner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте изображение (фото).")
        return WAITING_BANNER
    screen = context.user_data.get("banner_screen")
    if not screen:
        return ConversationHandler.END
    file_id = update.message.photo[-1].file_id
    cfg = load_config()
    cfg.setdefault("banners", {})[screen] = file_id
    save_config(cfg)
    await update.message.reply_text(
        f"✅ Баннер для <b>{BANNER_SCREENS.get(screen, screen)}</b> сохранён.",
        parse_mode="HTML",
    )
    context.user_data.pop("banner_screen", None)
    return ConversationHandler.END


async def cmd_delbanner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    args = context.args or []
    if not args or args[0] not in BANNER_SCREENS:
        await update.message.reply_text(
            "Укажите экран: " + " | ".join(BANNER_SCREENS.keys())
        )
        return
    screen = args[0]
    cfg = load_config()
    cfg.setdefault("banners", {}).pop(screen, None)
    save_config(cfg)
    await update.message.reply_text(
        f"🗑 Баннер для <b>{BANNER_SCREENS[screen]}</b> удалён.", parse_mode="HTML",
    )


# ─── Управление администраторами ──────────────────────────────────────────────

async def cmd_admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    cfg = load_config()
    entries = cfg.get("admins", [])
    owner_line = f"👑 @{OWNER_USERNAME} (владелец)\n"
    if entries:
        lines = "\n".join(
            f"• @{e}" if not str(e).isdigit() else f"• ID: {e}"
            for e in entries
        )
        await update.message.reply_text(
            f"👥 <b>Администраторы</b>\n\n{owner_line}{lines}", parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            f"👥 <b>Администраторы</b>\n\n{owner_line}Дополнительных администраторов нет.\n\n"
            "Добавить: <code>/addadmin @username</code> или <code>/addadmin ID</code>",
            parse_mode="HTML",
        )


async def cmd_addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    args = context.args or []
    if not args:
        await update.message.reply_text("Использование: /addadmin @username или /addadmin ID")
        return
    entry = args[0].lstrip("@").strip()
    if not entry:
        await update.message.reply_text("Укажите @username или ID.")
        return
    cfg = load_config()
    admins = cfg.setdefault("admins", [])
    if entry in admins or entry.lower() in [str(a).lower() for a in admins]:
        await update.message.reply_text("Этот администратор уже добавлен.")
        return
    # Нельзя добавить владельца повторно
    if entry.lower() == OWNER_USERNAME.lower():
        await update.message.reply_text(f"@{OWNER_USERNAME} является владельцем и уже имеет все права.")
        return
    admins.append(entry)
    save_config(cfg)
    display = f"@{entry}" if not entry.isdigit() else f"ID {entry}"
    await update.message.reply_text(f"✅ {display} добавлен как администратор.")


async def cmd_deladmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    args = context.args or []
    if not args:
        await update.message.reply_text("Использование: /deladmin @username или /deladmin ID")
        return
    entry = args[0].lstrip("@").strip()
    if entry.lower() == OWNER_USERNAME.lower():
        await update.message.reply_text("❌ Нельзя удалить главного владельца.")
        return
    cfg = load_config()
    admins = cfg.setdefault("admins", [])
    new_admins = [a for a in admins if str(a).lower() != entry.lower()]
    if len(new_admins) == len(admins):
        await update.message.reply_text("Администратор не найден.")
        return
    cfg["admins"] = new_admins
    save_config(cfg)
    display = f"@{entry}" if not entry.isdigit() else f"ID {entry}"
    await update.message.reply_text(f"✅ {display} удалён из администраторов.")


# ─── Способы оплаты ───────────────────────────────────────────────────────────

async def cmd_payment_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    cfg   = load_config()
    card  = cfg["payment"].get("card", "") or "не задана"
    token = cfg["payment"].get("cryptobot_token", "").strip()
    if token:
        crypto_status = "✅ подключён (токен задан)"
    else:
        crypto_status = "❌ не подключён"
    await update.message.reply_text(
        "💳 <b>Реквизиты оплаты</b>\n\n"
        f"Карта: <code>{card}</code>\n"
        f"CryptoBot: {crypto_status}\n\n"
        "─────────────────\n"
        "<b>Как подключить CryptoBot:</b>\n"
        "1. Откройте @CryptoBot в Telegram\n"
        "2. Нажмите «My Apps» → «Create App»\n"
        "3. Скопируйте API-токен\n"
        "4. Введите команду:\n"
        "<code>/setpayment crypto ВАШ_ТОКЕН</code>\n\n"
        "<b>Изменить карту:</b>\n"
        "<code>/setpayment card 1234 5678 9012 3456 — Иванов И.И.</code>",
        parse_mode="HTML",
    )


async def cmd_setpayment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Использование:\n"
            "/setpayment card <i>номер карты</i>\n"
            "/setpayment crypto <i>ссылка</i>",
            parse_mode="HTML",
        )
        return
    kind = args[0].lower()
    value = " ".join(args[1:])
    cfg = load_config()
    if kind == "card":
        cfg["payment"]["card"] = value
        save_config(cfg)
        await update.message.reply_text(f"✅ Карта сохранена: <code>{value}</code>", parse_mode="HTML")
    elif kind in ("crypto", "cryptobot"):
        await update.message.reply_text("🔄 Проверяю токен через CryptoBot API...")
        info = await crypto_get_me(value)
        if not info:
            await update.message.reply_text(
                "❌ <b>Токен недействителен.</b>\n\n"
                "Убедитесь, что скопировали правильный API-токен из @CryptoBot → My Apps.\n"
                "Токен не сохранён.",
                parse_mode="HTML",
            )
            return
        cfg["payment"]["cryptobot_token"] = value
        save_config(cfg)
        app_name = info.get("name", "—")
        await update.message.reply_text(
            f"✅ <b>CryptoBot подключён!</b>\n\n"
            f"Приложение: <b>{app_name}</b>\n\n"
            "Теперь клиенты могут оплачивать заказы через CryptoBot (USDT).",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text("Укажите тип: <code>card</code> или <code>crypto</code>", parse_mode="HTML")


# ─── Команды статистики и заказов ─────────────────────────────────────────────

def orders_by_period(orders: list, since: datetime.date) -> list:
    return [
        o for o in orders
        if datetime.date.fromisoformat(o.get("created_date", "2000-01-01")) >= since
    ]


async def cmd_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user):
        return
    orders = load_orders()
    await send_order_list(update.message, orders[-50:][::-1], "📋 <b>Последние 50 заказов</b>")


async def cmd_orders_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user):
        return
    orders = orders_by_period(load_orders(), local_date())
    await send_order_list(update.message, orders[::-1], f"📅 <b>Заказы сегодня</b>")


async def cmd_orders_7d(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user):
        return
    since = local_date() - datetime.timedelta(days=7)
    orders = orders_by_period(load_orders(), since)
    await send_order_list(update.message, orders[::-1], "📅 <b>Заказы за 7 дней</b>")


async def cmd_orders_30d(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user):
        return
    since = local_date() - datetime.timedelta(days=30)
    orders = orders_by_period(load_orders(), since)
    await send_order_list(update.message, orders[::-1], "📅 <b>Заказы за 30 дней</b>")


async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user):
        return
    orders = [o for o in load_orders() if o.get("status") == "new"]
    await send_order_list(update.message, orders[::-1], "🆕 <b>Активные заявки</b>")


async def cmd_completed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user):
        return
    orders = [o for o in load_orders() if o.get("status") == "done"]
    await send_order_list(update.message, orders[::-1], "✅ <b>Выполненные заявки</b>")


async def cmd_cancelled(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user):
        return
    orders = [o for o in load_orders() if o.get("status") == "cancelled"]
    await send_order_list(update.message, orders[::-1], "❌ <b>Отменённые заявки</b>")


def calc_stats(orders: list, since: datetime.date) -> tuple[int, float]:
    active_statuses = {"new", "done", None}
    filtered = orders_by_period(orders, since)
    count = sum(1 for o in filtered if o.get("status") != "cancelled")
    total = sum(parse_price(o.get("price", "0")) for o in filtered if o.get("status") != "cancelled")
    return count, total


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user):
        return
    orders = load_orders()
    today  = local_date()
    week   = today - datetime.timedelta(days=7)
    month  = today - datetime.timedelta(days=30)

    def block(since: datetime.date, label: str) -> str:
        count, total = calc_stats(orders, since)
        return f"{label}:\nЗаказов: <b>{count}</b>\nСумма: <b>${total:g}</b>"

    cancelled_orders = [o for o in orders if o.get("status") == "cancelled"]
    cancelled_sum    = sum(parse_price(o.get("price", "0")) for o in cancelled_orders)

    all_count = sum(1 for o in orders if o.get("status") != "cancelled")
    all_sum   = sum(parse_price(o.get("price", "0")) for o in orders if o.get("status") != "cancelled")

    await update.message.reply_text(
        "📊 <b>Статистика продаж</b>\n\n"
        f"{block(today, 'Сегодня')}\n\n"
        f"{block(week,  '7 дней')}\n\n"
        f"{block(month, '30 дней')}\n\n"
        f"Всего:\nЗаказов: <b>{all_count}</b>\nСумма: <b>${all_sum:g}</b>\n\n"
        f"Отменено: <b>{len(cancelled_orders)}</b>\n"
        f"Сумма отменённых: <b>${cancelled_sum:g}</b>",
        parse_mode="HTML",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user):
        return
    await update.message.reply_text(
        "📖 <b>SLIK Mobile Admin</b>\n\n"
        "<b>Заявки:</b>\n"
        "/orders — последние 50 заказов\n"
        "/orders_today — за сегодня\n"
        "/orders_7d — за 7 дней\n"
        "/orders_30d — за 30 дней\n"
        "/pending — активные\n"
        "/completed — выполненные\n"
        "/cancelled — отменённые\n"
        "/stats — статистика\n\n"
        "<b>Баннеры:</b>\n"
        "/banners — список экранов\n"
        "/setbanner <i>экран</i> — загрузить баннер\n"
        "/delbanner <i>экран</i> — удалить баннер\n\n"
        "<b>Администраторы:</b>\n"
        "/admins — список\n"
        "/addadmin @username — добавить\n"
        "/deladmin @username — удалить\n\n"
        "<b>Оплата:</b>\n"
        "/payment_details — реквизиты\n"
        "/setpayment card <i>номер</i>\n"
        "/setpayment crypto <i>ссылка</i>\n\n"
        "/start — главное меню\n"
        "/help — эта справка\n\n"
        "─────────────────\n"
        "<b>Ответ клиенту:</b> reply на уведомление «💬 Новое сообщение» в этом чате\n\n"
        "<b>Подключение группового чата:</b>\n"
        "1. Создать группу «SLIK Mobile Admin»\n"
        "2. Добавить бота в группу\n"
        "3. Получить ID группы через @userinfobot\n"
        "4. Установить ADMIN_CHAT_ID = <i>-100XXXXXXXXX</i>",
        parse_mode="HTML",
    )


# ─── Роутер callback ──────────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data  = query.data

    if data == "buy_esim":
        await show_buy_esim(update, context)
    elif data == "region_russia":
        await show_region_russia(update, context)
    elif data == "region_worldwide":
        await show_region_worldwide(update, context)
    elif data == "instructions":
        await show_instructions(update, context)
    elif data == "support_screen":
        await show_support_screen(update, context)
    elif data == "profile":
        await show_profile(update, context)
    elif data == "profile_orders":
        await show_my_orders(update, context)
    elif data == "profile_invite":
        await show_profile_invite(update, context)
    elif data == "profile_bonuses":
        await show_profile_bonuses(update, context)
    elif data == "back_main":
        await query.answer()
        await start(update, context)
    elif data in PLAN_MAP:
        await show_plan(update, context)
    else:
        await query.answer("Неизвестная команда")


# ─── Регистрация команд Telegram ──────────────────────────────────────────────

async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("start",           "Главное меню"),
        BotCommand("orders",          "Последние 50 заказов"),
        BotCommand("orders_today",    "Заказы за сегодня"),
        BotCommand("orders_7d",       "Заказы за 7 дней"),
        BotCommand("orders_30d",      "Заказы за 30 дней"),
        BotCommand("stats",           "Статистика продаж"),
        BotCommand("pending",         "Активные заявки"),
        BotCommand("completed",       "Выполненные заявки"),
        BotCommand("cancelled",       "Отменённые заявки"),
        BotCommand("admins",          "Управление администраторами"),
        BotCommand("banners",         "Управление баннерами"),
        BotCommand("payment_details", "Реквизиты оплаты"),
        BotCommand("help",            "Справка администратора"),
    ])
    logger.info("Команды зарегистрированы в Telegram")


# ─── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Переменная окружения TELEGRAM_BOT_TOKEN не задана")

    app = Application.builder().token(token).connect_timeout(30).read_timeout(30).write_timeout(30).pool_timeout(30).post_init(post_init).build()

    # ── ConversationHandler: баннеры ─────────────────────────────────────────
    banner_conv = ConversationHandler(
        entry_points=[CommandHandler("setbanner", cmd_setbanner)],
        states={
            WAITING_BANNER: [MessageHandler(filters.PHOTO, receive_banner)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
        per_message=False,
    )

    # ── ConversationHandler: покупка ─────────────────────────────────────────
    purchase_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_purchase, pattern=r"^buy_plan_")],
        states={
            WAITING_PAYMENT: [
                CallbackQueryHandler(choose_payment,
                    pattern=r"^(pay_crypto|pay_card|payment_done|check_payment_\d+|back_to_plan_.+)$"),
            ],
            WAITING_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            WAITING_TELEGRAM: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_telegram)],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_order_conv, pattern="^cancel_order$"),
            CommandHandler("start", start),
        ],
        allow_reentry=True,
        per_message=False,
    )

    app.add_handler(banner_conv)
    app.add_handler(purchase_conv)

    # ── Кнопки ✅ / ❌ на уведомлениях ──────────────────────────────────────
    app.add_handler(CallbackQueryHandler(
        handle_admin_action, pattern=r"^(done|cancelled)_\d+$"
    ))

    # ── Команды ──────────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",           start))
    app.add_handler(CommandHandler("orders",          cmd_orders))
    app.add_handler(CommandHandler("orders_today",    cmd_orders_today))
    app.add_handler(CommandHandler("orders_7d",       cmd_orders_7d))
    app.add_handler(CommandHandler("orders_30d",      cmd_orders_30d))
    app.add_handler(CommandHandler("stats",           cmd_stats))
    app.add_handler(CommandHandler("pending",         cmd_pending))
    app.add_handler(CommandHandler("completed",       cmd_completed))
    app.add_handler(CommandHandler("cancelled",       cmd_cancelled))
    app.add_handler(CommandHandler("admins",          cmd_admins))
    app.add_handler(CommandHandler("addadmin",        cmd_addadmin))
    app.add_handler(CommandHandler("deladmin",        cmd_deladmin))
    app.add_handler(CommandHandler("banners",         cmd_banners))
    app.add_handler(CommandHandler("delbanner",       cmd_delbanner))
    app.add_handler(CommandHandler("payment_details", cmd_payment_details))
    app.add_handler(CommandHandler("setpayment",      cmd_setpayment))
    app.add_handler(CommandHandler("help",            cmd_help))

    # ── Навигационные callback'и ──────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(handle_callback))

    # ── Reply администратора → клиенту (в группе) ────────────────────────────
    app.add_handler(MessageHandler(
        filters.REPLY & filters.TEXT & ~filters.COMMAND,
        handle_admin_reply,
    ))

    # ── Неизвестные сообщения клиентов → в админ-чат ─────────────────────────
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_unknown_message,
    ))

    logger.info("Бот SLIK Mobile запущен...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
