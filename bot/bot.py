"""
SLIK Mobile Telegram Bot — Расширенная коммерческая версия
"""

import os
import json
import logging
import datetime
import asyncio
import zipfile
import math
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
CBR_DAILY_JSON_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
EXCHANGE_RATE_API_URL = "https://open.er-api.com/v6/latest/USD"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKUPS_DIR = PROJECT_ROOT / "backups"
BACKUP_INTERVAL_SECONDS = 5 * 60 * 60
BACKUP_FIRST_RUN_SECONDS = 60
BACKUP_KEEP_LIMIT = 50
BACKUP_FILES = [
    (USERS_FILE, "bot/users.json", "users.json"),
    (ORDERS_FILE, "bot/orders.json", "orders.json"),
    (CONFIG_FILE, "bot/config.json", "config.json"),
]

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

FRIEND_REFERRAL_REWARD_USD = 1.0
STATUS_LEVELS = [
    (1000.0, "Ambassador", "👑", 10.0, 7),
    (300.0, "Premium", "💎", 5.0, 5),
    (150.0, "Nomad", "🌎", 3.0, 3),
    (50.0, "Explorer", "✈️", 2.0, 2),
    (0.0, "Traveller", "🧳", 1.0, 1),
]
STATUS_META = {
    status: {
        "threshold": threshold,
        "icon": icon,
        "referral_reward": reward,
        "cashback_percent": cashback_percent,
    }
    for threshold, status, icon, reward, cashback_percent in STATUS_LEVELS
}
STATUS_ORDER = {
    status: index
    for index, (_, status, _, _, _) in enumerate(reversed(STATUS_LEVELS))
}
STATUS_LEVELS_ASC = list(reversed(STATUS_LEVELS))
ORDER_STATUS_LABELS = {
    "new": "Новый",
    "processing": "В работе",
    "in_progress": "В работе",
    "done": "Выдан",
    "completed": "Выдан",
    "cancelled": "Отменён",
    "canceled": "Отменён",
}

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


def format_usd_price(value: float | str) -> str:
    amount = parse_price(str(value))
    return f"${amount:.2f}" if amount else html_escape(str(value))


def read_float_env(name: str, default: float) -> float:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        return float(raw_value.replace(",", "."))
    except ValueError:
        logger.warning(
            "Некорректное значение %s=%r; используется значение по умолчанию %s",
            name,
            raw_value,
            default,
        )
        return default


def get_usd_rub_fallback_rate() -> float:
    return read_float_env("USD_RUB_FALLBACK_RATE", 90.0)


def get_usd_rub_markup_percent() -> float:
    return read_float_env("USD_RUB_MARKUP_PERCENT", 3.0)


def apply_usd_rub_markup(rate: float) -> float:
    return round(rate * (1 + get_usd_rub_markup_percent() / 100), 2)


def round_rub_payment(amount_usd: float, effective_rate: float) -> int:
    return int(math.ceil(amount_usd * effective_rate))


def format_rub_amount(amount: int | float | str) -> str:
    try:
        rubles = int(amount)
    except (TypeError, ValueError):
        return html_escape(str(amount))
    return f"{rubles:,}".replace(",", " ") + " ₽"


def format_rub_rate(rate: float | str) -> str:
    try:
        return f"{float(rate):.2f} ₽"
    except (TypeError, ValueError):
        return html_escape(str(rate))


def build_card_payment_details(amount_usd: float, effective_rate: float, source: str) -> dict:
    rub_amount = round_rub_payment(amount_usd, effective_rate)
    return {
        "card_payment_usd": format_usd_price(amount_usd),
        "card_payment_rub_amount": rub_amount,
        "card_payment_rub": format_rub_amount(rub_amount),
        "usd_rub_rate": round(float(effective_rate), 2),
        "usd_rub_rate_text": format_rub_rate(effective_rate),
        "usd_rub_source": source,
    }


async def fetch_usd_rub_rate_from_cbr(client: httpx.AsyncClient) -> float:
    response = await client.get(CBR_DAILY_JSON_URL)
    response.raise_for_status()
    data = response.json()
    return float(data["Valute"]["USD"]["Value"])


async def fetch_usd_rub_rate_from_exchange_api(client: httpx.AsyncClient) -> float:
    response = await client.get(EXCHANGE_RATE_API_URL)
    response.raise_for_status()
    data = response.json()
    return float(data["rates"]["RUB"])


async def get_usd_rub_rate() -> tuple[float, str]:
    sources = (
        ("CBR daily JSON", fetch_usd_rub_rate_from_cbr),
        ("open.er-api.com", fetch_usd_rub_rate_from_exchange_api),
    )
    async with httpx.AsyncClient(timeout=5.0) as client:
        for source_name, fetcher in sources:
            try:
                base_rate = await fetcher(client)
                if base_rate <= 0:
                    raise ValueError(f"rate must be positive, got {base_rate}")
                return apply_usd_rub_markup(base_rate), source_name
            except Exception as exc:
                logger.warning("Не удалось получить курс USD/RUB из %s: %s", source_name, exc)

    fallback_rate = get_usd_rub_fallback_rate()
    effective_rate = apply_usd_rub_markup(fallback_rate)
    logger.warning(
        "Не удалось получить курс USD/RUB из публичных источников; используется fallback USD_RUB_FALLBACK_RATE=%s с markup %s%%",
        fallback_rate,
        get_usd_rub_markup_percent(),
    )
    return effective_rate, "fallback"


async def get_card_payment_details(amount_usd: float) -> dict:
    effective_rate, source = await get_usd_rub_rate()
    return build_card_payment_details(amount_usd, effective_rate, source)


def card_payment_admin_lines(order: dict) -> str:
    if order.get("payment_method") != "Карта" or not order.get("card_payment_rub"):
        return ""
    return (
        f"К оплате по карте: <b>{html_escape(str(order.get('card_payment_rub')))}</b>\n"
        f"Курс: <b>{html_escape(format_rub_rate(order.get('usd_rub_rate', order.get('usd_rub_rate_text', '—'))))}</b>\n"
    )

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


def format_usd_cents(value) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    return f"${amount:.2f}"


def calculate_user_status(total_spent: float) -> str:
    for threshold, status, _icon, _reward, _cashback_percent in STATUS_LEVELS:
        if total_spent >= threshold:
            return status
    return "Traveller"


def status_icon(status: str) -> str:
    return STATUS_META.get(status, STATUS_META["Traveller"])["icon"]


def format_status(status: str) -> str:
    actual_status = status if status in STATUS_META else "Traveller"
    return f"{status_icon(actual_status)} {actual_status}"


def referral_reward_for_status(status: str) -> float:
    return STATUS_META.get(status, STATUS_META["Traveller"])["referral_reward"]


def referral_reward_for_profile(profile: dict) -> float:
    status = calculate_user_status(float(profile.get("total_spent") or 0))
    return referral_reward_for_status(status)


def cashback_percent_for_status(status: str) -> int:
    return int(STATUS_META.get(status, STATUS_META["Traveller"])["cashback_percent"])


def cashback_percent_for_profile(profile: dict) -> int:
    status = calculate_user_status(float(profile.get("total_spent") or 0))
    return cashback_percent_for_status(status)


def next_status_progress(total_spent: float) -> tuple[str, float] | None:
    for threshold, status, _icon, _reward, _cashback_percent in STATUS_LEVELS_ASC:
        if total_spent < threshold:
            return status, round(threshold - total_spent, 2)
    return None


def order_status_label(status: str) -> str:
    return ORDER_STATUS_LABELS.get(str(status or "new"), str(status or "new"))


def order_sort_key(order: dict) -> tuple[int, str]:
    try:
        order_id = int(order.get("id") or 0)
    except (TypeError, ValueError):
        order_id = 0
    return order_id, str(order.get("created_at") or "")


def status_rank(status: str) -> int:
    return STATUS_ORDER.get(status, STATUS_ORDER["Traveller"])


def referral_entry_user_id(entry) -> str | None:
    if isinstance(entry, dict):
        user_id = entry.get("user_id")
    else:
        user_id = entry
    return str(user_id) if user_id is not None else None


def ensure_referral_entry(referrer_profile: dict, referred_user) -> None:
    referrals = referrer_profile.setdefault("referrals", [])
    referred_key = str(referred_user.id)
    for index, entry in enumerate(referrals):
        if referral_entry_user_id(entry) == referred_key:
            if isinstance(entry, dict):
                entry["username"] = referred_user.username or entry.get("username", "")
                entry["full_name"] = referred_user.full_name or entry.get("full_name", "")
            else:
                referrals[index] = {
                    "user_id": referred_user.id,
                    "username": referred_user.username or "",
                    "full_name": referred_user.full_name or "",
                    "joined_at": now_str(),
                    "bonus_awarded": False,
                }
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

    referrer_profile = update_profile_stats_from_orders(int(referrer_id), referrer_profile)
    referrer_reward = referral_reward_for_profile(referrer_profile)
    credit_slik_balance(profile, FRIEND_REFERRAL_REWARD_USD)
    credit_slik_balance(referrer_profile, referrer_reward)
    profile["referral_bonus_awarded"] = True
    profile["referral_bonus_order"] = order.get("number")
    profile["referral_bonus_awarded_at"] = now_str()
    profile["referral_bonus_amount"] = FRIEND_REFERRAL_REWARD_USD
    profile["referrer_bonus_amount"] = referrer_reward

    ensure_referral_entry(referrer_profile, user)
    for entry in referrer_profile.get("referrals", []):
        if isinstance(entry, dict) and referral_entry_user_id(entry) == str(user.id):
            entry["bonus_awarded"] = True
            entry["first_order_number"] = order.get("number")
            entry["bonus_awarded_at"] = profile["referral_bonus_awarded_at"]
            entry["bonus_amount"] = referrer_reward
            entry["friend_bonus_amount"] = FRIEND_REFERRAL_REWARD_USD
            break

    users[referrer_key] = referrer_profile
    return True


def update_profile_stats_from_orders(user_id: int, profile: dict, orders: list | None = None) -> dict:
    user_orders = orders if orders is not None else get_user_orders(user_id)
    active_orders = [order for order in user_orders if order.get("status") not in {"cancelled", "canceled"}]
    profile["orders_count"] = len(active_orders)
    profile["total_spent"] = round(sum(parse_price(order.get("price", "0")) for order in active_orders), 2)
    profile["status"] = calculate_user_status(float(profile.get("total_spent") or 0))
    profile.setdefault("slik_balance", profile.get("bonus_balance", 0))
    profile["bonus_balance"] = profile.get("slik_balance", 0)
    return profile


def award_cashback_if_needed(profile: dict, order: dict) -> float:
    if order.get("cashback_awarded"):
        return 0.0
    if order.get("status") in {"cancelled", "canceled"}:
        return 0.0

    order_amount = parse_price(order.get("price", "0"))
    if order_amount <= 0:
        return 0.0

    status = profile.get("status") or calculate_user_status(float(profile.get("total_spent") or 0))
    cashback_percent = cashback_percent_for_status(status)
    cashback_amount = round(order_amount * cashback_percent / 100, 2)
    if cashback_amount <= 0:
        return 0.0

    credit_slik_balance(profile, cashback_amount)
    order["cashback_awarded"] = True
    order["cashback_amount"] = cashback_amount
    order["cashback_percent"] = cashback_percent
    order["cashback_awarded_at"] = now_str()
    return cashback_amount


def save_order_cashback_fields(order: dict) -> None:
    order_id = order.get("id")
    if order_id is None:
        return
    orders = load_orders()
    for saved_order in orders:
        if saved_order.get("id") == order_id:
            saved_order["cashback_awarded"] = order.get("cashback_awarded", False)
            if "cashback_amount" in order:
                saved_order["cashback_amount"] = order["cashback_amount"]
            if "cashback_percent" in order:
                saved_order["cashback_percent"] = order["cashback_percent"]
            if "cashback_awarded_at" in order:
                saved_order["cashback_awarded_at"] = order["cashback_awarded_at"]
            save_orders(orders)
            return


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


def record_user_order(user, order: dict) -> tuple[dict, str, str, float]:
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

    all_user_orders = get_user_orders(user.id)
    current_order_id = order.get("id")
    previous_orders = [
        user_order for user_order in all_user_orders
        if user_order.get("id") != current_order_id
    ]
    previous_total = round(
        sum(
            parse_price(user_order.get("price", "0"))
            for user_order in previous_orders
            if user_order.get("status") != "cancelled"
        ),
        2,
    )
    previous_status = calculate_user_status(previous_total)

    profile = update_profile_stats_from_orders(user.id, profile, all_user_orders)
    current_status = profile.get("status", "Traveller")
    cashback_amount = award_cashback_if_needed(profile, order)
    if cashback_amount > 0:
        save_order_cashback_fields(order)
    award_referral_bonus_if_needed(users, profile, user, order)
    users[key] = profile
    save_users(users)
    return profile, previous_status, current_status, cashback_amount


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
    order["id"]                 = order_id
    order["number"]             = f"#{order_id:04d}"
    order["status"]             = "new"
    order["created_at"]         = now_str()
    order["created_date"]       = local_date().isoformat()
    order["cashback_awarded"]   = False
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


# ─── Резервные копии runtime-данных ──────────────────────────────────────────

def list_backup_archives() -> list[Path]:
    if not BACKUPS_DIR.exists():
        return []
    return sorted(
        BACKUPS_DIR.glob("backup_*.zip"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )


def cleanup_old_backups(keep_limit: int = BACKUP_KEEP_LIMIT) -> list[Path]:
    archives = list_backup_archives()
    old_archives = archives[keep_limit:]
    deleted = []
    for archive in old_archives:
        try:
            archive.unlink()
            deleted.append(archive)
            logger.info("Удалён старый бэкап: %s", archive)
        except Exception:
            logger.exception("Не удалось удалить старый бэкап: %s", archive)
    return deleted


def create_backup_archive(created_at: datetime.datetime | None = None) -> dict:
    created_at = created_at or datetime.datetime.now(tz=TZ)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = BACKUPS_DIR / f"backup_{created_at.strftime('%Y-%m-%d_%H-%M')}.zip"
    included: list[str] = []
    skipped: list[str] = []

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for source_path, archive_name, display_name in BACKUP_FILES:
            if source_path.exists():
                zip_file.write(source_path, arcname=archive_name)
                included.append(display_name)
            else:
                skipped.append(display_name)
                logger.warning("Файл для бэкапа отсутствует и пропущен: %s", source_path)

    cleanup_old_backups()
    logger.info("Создан бэкап runtime-данных: %s", archive_path)
    return {
        "path": archive_path,
        "created_at": created_at,
        "included": included,
        "skipped": skipped,
    }


def format_backup_caption(backup_info: dict) -> str:
    created_at = backup_info["created_at"].strftime("%d.%m.%Y %H:%M")
    included = backup_info.get("included") or []
    skipped = backup_info.get("skipped") or []
    included_text = "\n".join(f"• {name}" for name in included) or "• —"
    text = (
        "💾 Автоматический бэкап SLIK Mobile\n\n"
        "Дата:\n"
        f"{created_at}\n\n"
        "В архиве:\n"
        f"{included_text}"
    )
    if skipped:
        skipped_text = "\n".join(f"• {name}" for name in skipped)
        text += f"\n\nПропущено:\n{skipped_text}"
    return text


async def send_backup_archive(bot, chat_id: int, backup_info: dict) -> None:
    with backup_info["path"].open("rb") as archive_file:
        await bot.send_document(
            chat_id=chat_id,
            document=archive_file,
            filename=backup_info["path"].name,
            caption=format_backup_caption(backup_info),
        )


async def automatic_backup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        backup_info = create_backup_archive()
        admin_id = get_admin_chat_id()
        if not admin_id:
            logger.warning("ADMIN_CHAT_ID не задан; автоматический бэкап сохранён локально: %s", backup_info["path"])
            return
        await send_backup_archive(context.bot, admin_id, backup_info)
    except Exception:
        logger.exception("Ошибка автоматического бэкапа SLIK Mobile")


async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    try:
        backup_info = create_backup_archive()
        await send_backup_archive(context.bot, update.effective_chat.id, backup_info)
        await update.message.reply_text("Бэкап создан и отправлен.")
    except Exception:
        logger.exception("Не удалось создать или отправить ручной бэкап")
        await update.message.reply_text("Не удалось создать бэкап. Ошибка записана в лог.")


async def cmd_backups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    archives = list_backup_archives()[:10]
    if not archives:
        await update.message.reply_text("💾 Последние бэкапы:\n\nПока нет архивов.")
        return
    lines = ["💾 Последние бэкапы:", ""]
    lines.extend(f"{index}. {archive.name}" for index, archive in enumerate(archives, start=1))
    await update.message.reply_text("\n".join(lines))


def schedule_automatic_backups(app: Application) -> None:
    if not app.job_queue:
        logger.warning("JobQueue недоступен; автоматические бэкапы не запущены")
        return
    app.job_queue.run_repeating(
        automatic_backup_job,
        interval=BACKUP_INTERVAL_SECONDS,
        first=BACKUP_FIRST_RUN_SECONDS,
        name="automatic_runtime_backup",
    )
    logger.info("Автоматические бэкапы запланированы: первый запуск через %s секунд, далее каждые %s секунд", BACKUP_FIRST_RUN_SECONDS, BACKUP_INTERVAL_SECONDS)


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
    total_spent = float(profile.get('total_spent') or 0)
    next_progress = next_status_progress(total_spent)
    progress_text = (
        f"До следующего статуса:\n<b>{html_escape(format_status(next_progress[0]))}</b> — осталось <b>{format_usd_cents(next_progress[1])}</b>"
        if next_progress
        else "Максимальный статус достигнут 👑"
    )
    text = (
        "👤 <b>Личный кабинет</b>\n\n"
        f"Имя: <b>{html_escape(profile.get('full_name') or user.full_name or '—')}</b>\n"
        f"Telegram ID: <code>{user.id}</code>\n\n"
        "Текущий статус:\n"
        f"<b>{html_escape(format_status(profile.get('status', 'Traveller')))}</b>\n\n"
        f"Потрачено: <b>{format_usd_cents(total_spent)}</b>\n\n"
        f"{progress_text}\n\n"
        f"Количество заказов: <b>{int(profile.get('orders_count') or 0)}</b>\n"
        f"SLIK Balance: <b>{format_usd_cents(profile.get('slik_balance', profile.get('bonus_balance', 0)))}</b>\n"
        f"Приглашено друзей: <b>{referrals_count}</b>"
    )
    await edit_or_send(query, context, text, profile_keyboard())


def format_order_date(order: dict) -> str:
    created_date = order.get("created_date")
    if created_date:
        try:
            return datetime.date.fromisoformat(str(created_date)).strftime("%d.%m.%Y")
        except ValueError:
            pass
    created_at = str(order.get("created_at") or "")
    return created_at[:10] if created_at else "—"


def format_user_orders(orders: list) -> str:
    total_orders = len(orders)
    total_spent = round(
        sum(
            parse_price(order.get("price", "0"))
            for order in orders
            if order.get("status") not in {"cancelled", "canceled"}
        ),
        2,
    )
    latest_orders = sorted(orders, key=order_sort_key, reverse=True)[:10]
    lines = [
        "📦 <b>Ваши заказы</b>",
        "",
        f"Всего заказов: <b>{total_orders}</b>",
        f"Потрачено: <b>{format_usd_cents(total_spent)}</b>",
        "",
    ]
    for index, order in enumerate(latest_orders):
        if index:
            lines.append("────────────")
        lines.extend([
            f"🌍 Страна: <b>{html_escape(order.get('country', 'Россия'))}</b>",
            f"📦 Тариф: <b>{html_escape(order.get('gb', '—'))}</b>",
            f"💵 Сумма: <b>{html_escape(order.get('price', '—'))}</b>",
            f"📅 Дата: <b>{html_escape(format_order_date(order))}</b>",
            f"🔖 Статус: <b>{html_escape(order_status_label(order.get('status', 'new')))}</b>",
        ])
    if total_orders > 10:
        lines.extend(["", "Показаны последние 10 заказов."])
    return "\n".join(lines)


async def show_my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    orders = get_user_orders(query.from_user.id)
    if not orders:
        await edit_or_send(
            query, context,
            "📦 <b>У вас пока нет заказов.</b>",
            profile_back_keyboard(),
        )
        return

    await edit_or_send(query, context, format_user_orders(orders), profile_back_keyboard())


async def get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    if getattr(context.bot, "username", None):
        return context.bot.username
    bot_info = await context.bot.get_me()
    return bot_info.username or ""


async def show_profile_invite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    profile = sync_user_order_stats(query.from_user, ensure_user_profile(query.from_user))
    status = profile.get("status", "Traveller")
    referral_reward = referral_reward_for_profile(profile)
    username = await get_bot_username(context)
    referral_link = f"https://t.me/{username}?start=ref_{query.from_user.id}" if username else f"/start ref_{query.from_user.id}"
    text = (
        "👥 <b>Пригласить друга</b>\n\n"
        f"Ваш статус: <b>{html_escape(format_status(status))}</b>\n\n"
        "За первую заявку друга:\n"
        f"Вы получите: <b>{format_usd(referral_reward)}</b>\n"
        f"Друг получит: <b>{format_usd(FRIEND_REFERRAL_REWARD_USD)}</b>\n\n"
        f"Ваша ссылка:\n<code>{html_escape(referral_link)}</code>"
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
    status = profile.get("status", "Traveller")
    referral_reward = referral_reward_for_profile(profile)
    text = (
        "💰 <b>SLIK Balance</b>\n\n"
        f"Баланс: <b>{format_usd_cents(profile.get('slik_balance', profile.get('bonus_balance', 0)))}</b>\n"
        f"Статус: <b>{html_escape(format_status(status))}</b>\n"
        f"Ваш кэшбэк: <b>{cashback_percent_for_status(status)}%</b>\n"
        f"Ваш бонус за друга: <b>{format_usd(referral_reward)}</b>\n\n"
        f"Приглашено друзей: <b>{referrals_count}</b>\n"
        f"Бонус начислен за друзей: <b>{awarded_count}</b>\n\n"
        f"Друг по вашей ссылке получает: <b>{format_usd(FRIEND_REFERRAL_REWARD_USD)}</b>."
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
        amount_usd = parse_price(plan.get("price", "0"))
        payment_details = await get_card_payment_details(amount_usd)
        context.user_data["card_payment_details"] = payment_details
        card_text = f"<code>{html_escape(card)}</code>" if card else "Реквизиты карты уточните у менеджера"
        await query.message.reply_text(
            f"💳 <b>Перевод на карту</b>\n\n"
            f"Сумма: <b>{payment_details['card_payment_usd']}</b>\n"
            f"К оплате: <b>{payment_details['card_payment_rub']}</b>\n\n"
            f"Карта: {card_text}\n\n"
            "Переведите сумму в рублях и нажмите «Я оплатил».",
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


async def notify_cashback_awarded(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    order: dict,
    cashback_amount: float,
    profile: dict,
) -> None:
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "🎁 <b>Cashback начислен</b>\n\n"
                f"За заказ <b>{html_escape(order.get('number', '—'))}</b> вам начислено:\n"
                f"+<b>{format_usd_cents(cashback_amount)}</b> на SLIK Balance\n\n"
                "Ваш баланс:\n"
                f"<b>{format_usd_cents(profile.get('slik_balance', profile.get('bonus_balance', 0)))}</b>"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error("Не удалось уведомить о cashback: %s", e)


async def notify_status_upgrade(context: ContextTypes.DEFAULT_TYPE, user_id: int, status: str) -> None:
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "🎉 <b>Ваш статус повышен!</b>\n\n"
                f"Новый статус: <b>{html_escape(format_status(status))}</b>\n\n"
                f"Теперь вы получаете <b>{format_usd(referral_reward_for_status(status))}</b> "
                "за приглашённого друга."
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error("Не удалось уведомить о повышении статуса: %s", e)


async def get_telegram(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tg_handle = update.message.text.strip()
    if not tg_handle:
        await update.message.reply_text("Пожалуйста, укажите ваш Telegram:", reply_markup=cancel_keyboard())
        return WAITING_TELEGRAM

    user    = update.effective_user
    plan    = context.user_data["plan"]
    name    = context.user_data["name"]
    payment = context.user_data.get("payment_method", "—")

    order_data = {
        "gb":             plan["gb"],
        "days":           plan["days"],
        "price":          plan["price"],
        "country":        "Россия",
        "plan_key":       context.user_data["plan_key"],
        "payment_method": payment,
        "name":           name,
        "tg_handle":      tg_handle,
        "user_id":        user.id,
    }
    if payment == "Карта":
        order_data.update(context.user_data.get("card_payment_details") or {})

    order = append_order(order_data)
    profile, previous_status, current_status, cashback_amount = record_user_order(user, order)

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
    if cashback_amount > 0:
        await notify_cashback_awarded(context, user.id, order, cashback_amount, profile)
    if status_rank(current_status) > status_rank(previous_status):
        await notify_status_upgrade(context, user.id, current_status)
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
    card_payment_lines = card_payment_admin_lines(order)
    text = (
        "🔥 <b>Новый заказ</b>\n\n"
        f"Номер заказа: <b>{html_escape(order_number)}</b>\n\n"
        f"📶 Тариф: <b>{html_escape(order.get('gb', '—'))} / {html_escape(order.get('days', '—'))}</b>\n"
        f"💵 Цена: <b>{format_usd_price(order.get('price', '—'))}</b>\n"
        f"{card_payment_lines}"
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
        "<b>Бэкапы:</b>\n"
        "/backup — создать и отправить ZIP сейчас\n"
        "/backups — последние 10 архивов\n\n"
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
        BotCommand("backup",          "Создать резервную копию"),
        BotCommand("backups",         "Последние резервные копии"),
        BotCommand("help",            "Справка администратора"),
    ])
    schedule_automatic_backups(app)
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
    app.add_handler(CommandHandler("backup",          cmd_backup))
    app.add_handler(CommandHandler("backups",         cmd_backups))
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
