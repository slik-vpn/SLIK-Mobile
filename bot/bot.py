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
import re
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
    WebAppInfo,
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
BALANCE_LOG_FILE = Path(__file__).parent / "balance_changes.json"
PAYMENT_METHODS_FILE = Path(__file__).parent / "payment_methods.json"
CRYPTOBOT_API  = "https://pay.crypt.bot/api"

def env_float(name: str, default: float, min_value: float | None = None, max_value: float | None = None) -> float:
    try:
        value = float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


USD_RUB_MIN_RATE = env_float("USD_RUB_MIN_RATE", 50, 1, 500)
USD_RUB_MAX_RATE = env_float("USD_RUB_MAX_RATE", 200, USD_RUB_MIN_RATE, 500)
USD_RUB_FALLBACK_RATE = env_float("USD_RUB_FALLBACK_RATE", 90, USD_RUB_MIN_RATE, USD_RUB_MAX_RATE)
USD_RUB_MARKUP_PERCENT = env_float("USD_RUB_MARKUP_PERCENT", 1.5, 0, 30)
USD_RUB_MAX_SOURCE_DEVIATION_PERCENT = 5
CARD_RATE_LOCK_SECONDS = 5 * 60

def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        return default

ABANDONED_CHECKOUT_REMINDER_MINUTES = env_int("ABANDONED_CHECKOUT_REMINDER_MINUTES", 30)
ABANDONED_CHECKOUT_MAX_AGE_HOURS = 24
ESIM_EXPIRY_REMINDER_DAYS_BEFORE = env_int("ESIM_EXPIRY_REMINDER_DAYS_BEFORE", 1)
ESIM_EXPIRY_REMINDER_MAX_AGE_DAYS = env_int("ESIM_EXPIRY_REMINDER_MAX_AGE_DAYS", 60)
ESIM_EXPIRY_REMINDER_INTERVAL_SECONDS = 60 * 60


def is_cashback_enabled() -> bool:
    return str(os.environ.get("CASHBACK_ENABLED", "false")).lower() in {"1", "true", "yes", "on"}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKUPS_DIR = PROJECT_ROOT / "backups"
BACKUP_INTERVAL_SECONDS = 5 * 60 * 60
BACKUP_FIRST_RUN_SECONDS = 60
BACKUP_KEEP_LIMIT = 50
BACKUP_FILES = [
    (USERS_FILE, "bot/users.json", "users.json"),
    (ORDERS_FILE, "bot/orders.json", "orders.json"),
    (CONFIG_FILE, "bot/config.json", "config.json"),
    (BALANCE_LOG_FILE, "bot/balance_changes.json", "balance_changes.json"),
]
BACKUP_EMPTY_DEFAULTS = {
    BALANCE_LOG_FILE: "[]\n",
}
RUNTIME_JSON_FILES = [
    (USERS_FILE, "users.json"),
    (ORDERS_FILE, "orders.json"),
    (CONFIG_FILE, "config.json"),
    (BALANCE_LOG_FILE, "balance_changes.json"),
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

APPLE_ID_PRODUCTS = {
    "US": [
        {"id": "apple_us_5", "region": "US", "title": "Apple Gift Card USA $5", "amount": 5, "currency": "USD", "price_usd": 5},
        {"id": "apple_us_10", "region": "US", "title": "Apple Gift Card USA $10", "amount": 10, "currency": "USD", "price_usd": 10},
        {"id": "apple_us_15", "region": "US", "title": "Apple Gift Card USA $15", "amount": 15, "currency": "USD", "price_usd": 15},
        {"id": "apple_us_25", "region": "US", "title": "Apple Gift Card USA $25", "amount": 25, "currency": "USD", "price_usd": 25},
        {"id": "apple_us_50", "region": "US", "title": "Apple Gift Card USA $50", "amount": 50, "currency": "USD", "price_usd": 50},
        {"id": "apple_us_100", "region": "US", "title": "Apple Gift Card USA $100", "amount": 100, "currency": "USD", "price_usd": 100},
    ],
    "TR": [
        {"id": "apple_tr_100", "region": "TR", "title": "Apple Gift Card Turkey 100₺", "amount": 100, "currency": "TRY", "price_usd": 4},
        {"id": "apple_tr_250", "region": "TR", "title": "Apple Gift Card Turkey 250₺", "amount": 250, "currency": "TRY", "price_usd": 9},
        {"id": "apple_tr_500", "region": "TR", "title": "Apple Gift Card Turkey 500₺", "amount": 500, "currency": "TRY", "price_usd": 18},
        {"id": "apple_tr_1000", "region": "TR", "title": "Apple Gift Card Turkey 1000₺", "amount": 1000, "currency": "TRY", "price_usd": 36},
    ],
}

APPLE_ID_REGION_TITLES = {"US": "USA", "TR": "Turkey"}
APPLE_ID_REGION_FLAGS = {"US": "🇺🇸", "TR": "🇹🇷"}

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
    "waiting_payment": "Ожидает оплаты",
    "processing": "В работе",
    "in_progress": "В работе",
    "done": "Выдан",
    "issued": "Выдан",
    "completed": "Выдан",
    "cancelled": "Отменён",
    "canceled": "Отменён",
}
ORDER_STATUS_ICONS = {
    "new": "🟡",
    "waiting_payment": "🟠",
    "in_progress": "🔵",
    "issued": "🟢",
    "cancelled": "🔴",
}
ORDER_STATUS_ALIASES = {
    "processing": "in_progress",
    "done": "issued",
    "completed": "issued",
    "canceled": "cancelled",
}

ROLE_OWNER = "OWNER"
ROLE_ADMIN = "ADMIN"
ROLE_MANAGER = "MANAGER"
ROLE_USER = "USER"
ADMIN_ACCESS_DENIED_TEXT = "⛔ У вас нет доступа."

# ─── Состояния диалога ────────────────────────────────────────────────────────

WAITING_PAYMENT, WAITING_NAME, WAITING_TELEGRAM = range(1, 4)
WAITING_BANNER = 10

# ─── Время ────────────────────────────────────────────────────────────────────

def now_str() -> str:
    return datetime.datetime.now(tz=TZ).strftime("%d.%m.%Y %H:%M")

def now_time() -> str:
    return datetime.datetime.now(tz=TZ).strftime("%H:%M")


def parse_now_str(value: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.strptime(str(value), "%d.%m.%Y %H:%M").replace(tzinfo=TZ)
    except (TypeError, ValueError):
        return None

def local_date() -> datetime.date:
    return datetime.datetime.now(tz=TZ).date()

def parse_price(s: str) -> float:
    try:
        return float(s.replace("$", "").strip())
    except Exception:
        return 0.0


def parse_order_days(value) -> int | None:
    match = re.search(r"\d+", str(value or ""))
    if not match:
        return None
    try:
        days = int(match.group(0))
    except ValueError:
        return None
    return days if days > 0 else None

# ─── config.json ──────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "banners":  {},
    "admins":   [],
    "managers": [],
    "relay":    {},
    "payment":  {"card": "", "cryptobot_token": ""},
    "usd_rub": {
        "manual_rate": None,
        "markup_percent": USD_RUB_MARKUP_PERCENT,
        "rate_checked_at": "",
        "rate_source": "",
        "market_usd_rub_rate": None,
        "final_usd_rub_rate": None,
        "rate_method": "",
        "rate_diagnostics": [],
    },
    "notification_chats": {
        "orders": "",
        "client_activity": "",
        "new_clients": "",
        "payments": "",
        "tech_alerts": "",
    },
}

PAYMENT_METHOD_LABELS = {
    "card": "Карта",
    "cryptobot": "CryptoBot",
    "freekassa": "FreeKassa",
    "yookassa": "YooKassa",
}

DEFAULT_PAYMENT_METHODS = {
    "card": {
        "enabled": True,
        "type": "manual",
        "title": "💳 Карта",
        "client_title": "💳 Карта",
        "description": "Текущий способ оплаты картой",
        "instructions": [],
        "credentials": {},
    },
    "cryptobot": {
        "enabled": True,
        "type": "api",
        "title": "🤖 CryptoBot",
        "client_title": "🤖 CryptoBot",
        "description": "Оплата через CryptoBot",
        "instructions": [
            "Откройте @CryptoBot в Telegram",
            "Создайте приложение в Crypto Pay и получите API-токен",
            "Сохраните токен в настройках оплаты бота",
        ],
        "credentials": {},
    },
    "freekassa": {
        "enabled": False,
        "type": "api",
        "title": "🔗 FreeKassa",
        "client_title": "🔗 FreeKassa",
        "description": "Оплата через FreeKassa",
        "instructions": [
            "Необходимо зарегистрироваться на сайте FreeKassa (freekassa.com)",
            "Далее необходимо в личном кабинете получить API ключ",
            "Затем скопируйте API ключ и отправьте его боту",
            "Все готово!",
        ],
        "credentials": {"api_key": ""},
    },
    "yookassa": {
        "enabled": False,
        "type": "api",
        "title": "🟣 YooKassa",
        "client_title": "🟣 YooKassa",
        "description": "Оплата через YooKassa",
        "instructions": [],
        "credentials": {},
    },
}

PAYMENT_ADMIN_INPUT_TITLE = "payment_title"
PAYMENT_ADMIN_INPUT_CREDENTIALS = "payment_credentials"
USD_RUB_INPUT_MANUAL_RATE = "usd_rub_manual_rate"
USD_RUB_INPUT_MARKUP = "usd_rub_markup"
ADMIN_MANAGEMENT_INPUT_TELEGRAM_ID = "admin_management_telegram_id"
ADMIN_MANAGEMENT_ROLES = (ROLE_MANAGER, ROLE_ADMIN, ROLE_OWNER)


def runtime_default_value(path: Path):
    if path == CONFIG_FILE:
        return json.loads(json.dumps(DEFAULT_CONFIG))
    if path in {ORDERS_FILE, BALANCE_LOG_FILE}:
        return []
    return {}


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with tmp_path.open("wb") as tmp_file:
        tmp_file.write(payload)
        tmp_file.flush()
        os.fsync(tmp_file.fileno())
    os.replace(tmp_path, path)


def atomic_write_json(path: Path, data) -> None:
    payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    atomic_write_bytes(path, payload)


def corrupt_file_path(path: Path) -> Path:
    timestamp = datetime.datetime.now(tz=TZ).strftime("%Y%m%d_%H%M%S")
    candidate = path.with_name(f"{path.name}.corrupt.{timestamp}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.corrupt.{timestamp}.{counter}")
        counter += 1
    return candidate


def load_runtime_json(path: Path, default_value, expected_type):
    if not path.exists():
        atomic_write_json(path, default_value)
        return default_value
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, expected_type):
            raise ValueError(f"Expected {expected_type.__name__}, got {type(data).__name__}")
        return data
    except Exception:
        backup_path = corrupt_file_path(path)
        try:
            os.replace(path, backup_path)
            logger.exception("Повреждённый JSON перемещён в %s", backup_path)
        except Exception:
            logger.exception("Не удалось сохранить повреждённый JSON %s", path)
        atomic_write_json(path, default_value)
        return default_value


def save_runtime_json(path: Path, data) -> None:
    atomic_write_json(path, data)


def load_config() -> dict:
    data = load_runtime_json(CONFIG_FILE, runtime_default_value(CONFIG_FILE), dict)
    for k, v in DEFAULT_CONFIG.items():
        data.setdefault(k, json.loads(json.dumps(v)))
    chats = data.get("notification_chats")
    if not isinstance(chats, dict):
        chats = {}
        data["notification_chats"] = chats
    for kind in DEFAULT_CONFIG["notification_chats"]:
        chats.setdefault(kind, "")
    usd_rub = data.get("usd_rub")
    if not isinstance(usd_rub, dict):
        usd_rub = {}
        data["usd_rub"] = usd_rub
    for key, value in DEFAULT_CONFIG["usd_rub"].items():
        usd_rub.setdefault(key, value)
    return data


def save_config(cfg: dict) -> None:
    save_runtime_json(CONFIG_FILE, cfg)


NOTIFICATION_CHAT_META = {
    "orders": ("Заказы", "ORDERS_CHAT_ID", "чат заказов"),
    "client_activity": ("Действия клиентов", "CLIENT_ACTIVITY_CHAT_ID", "чат действий клиентов"),
    "new_clients": ("Новые клиенты", "NEW_CLIENTS_CHAT_ID", "чат новых клиентов"),
    "payments": ("Оплаты", "PAYMENTS_CHAT_ID", "чат оплат"),
    "tech_alerts": ("Техника", "TECH_ALERTS_CHAT_ID", "технический чат"),
}


def _parse_chat_id(value) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def get_notification_chat_source(kind: str) -> tuple[int | None, str]:
    if kind not in NOTIFICATION_CHAT_META:
        return get_admin_chat_id(), "fallback ADMIN_CHAT_ID"
    cfg = load_config()
    chats = cfg.get("notification_chats") if isinstance(cfg.get("notification_chats"), dict) else {}
    config_id = _parse_chat_id(chats.get(kind))
    if config_id is not None:
        return config_id, "config"
    env_name = NOTIFICATION_CHAT_META[kind][1]
    env_id = _parse_chat_id(os.environ.get(env_name, ""))
    if env_id is not None:
        return env_id, "env"
    return get_admin_chat_id(), "fallback ADMIN_CHAT_ID"


def get_notification_chat_id(kind: str) -> int | None:
    return get_notification_chat_source(kind)[0]


def get_orders_chat_id() -> int | None:
    return get_notification_chat_id("orders")


def get_orders_chat_source() -> tuple[int | None, str]:
    return get_notification_chat_source("orders")


def get_client_activity_chat_id() -> int | None:
    return get_notification_chat_id("client_activity")


def get_client_activity_chat_source() -> tuple[int | None, str]:
    return get_notification_chat_source("client_activity")


def get_new_clients_chat_id() -> int | None:
    return get_notification_chat_id("new_clients")


def get_new_clients_chat_source() -> tuple[int | None, str]:
    return get_notification_chat_source("new_clients")


def get_payments_chat_id() -> int | None:
    return get_notification_chat_id("payments")


def get_tech_alerts_chat_id() -> int | None:
    return get_notification_chat_id("tech_alerts")


def set_notification_chat_id(kind: str, chat_id: str) -> None:
    cfg = load_config()
    cfg.setdefault("notification_chats", {})[kind] = chat_id
    save_config(cfg)


def get_usd_rub_settings() -> dict:
    settings = load_config().get("usd_rub")
    if not isinstance(settings, dict):
        settings = {}
    return settings


def get_configured_usd_rub_markup_percent() -> float:
    markup = normalize_percent(get_usd_rub_settings().get("markup_percent"))
    return markup if markup is not None else USD_RUB_MARKUP_PERCENT


def get_manual_usd_rub_rate() -> float | None:
    return normalize_rate(get_usd_rub_settings().get("manual_rate"))


def save_usd_rub_settings(**updates) -> None:
    cfg = load_config()
    settings = cfg.setdefault("usd_rub", {})
    settings.update(updates)
    save_config(cfg)


# ─── payment_methods.json ─────────────────────────────────────────────────────

def default_payment_methods() -> dict:
    return json.loads(json.dumps(DEFAULT_PAYMENT_METHODS))


def merge_payment_methods(data: dict) -> dict:
    merged = {
        key: json.loads(json.dumps(value))
        for key, value in data.items()
        if isinstance(value, dict)
    }
    for key, defaults in default_payment_methods().items():
        method = merged.get(key) if isinstance(merged.get(key), dict) else {}
        for field, value in defaults.items():
            if field == "credentials":
                credentials = method.get("credentials") if isinstance(method.get("credentials"), dict) else {}
                method_credentials = dict(value)
                method_credentials.update(credentials)
                method["credentials"] = method_credentials
            else:
                method.setdefault(field, value)
        merged[key] = method
    return merged


def load_payment_methods() -> dict:
    data = load_runtime_json(PAYMENT_METHODS_FILE, default_payment_methods(), dict)
    merged = merge_payment_methods(data)
    if merged != data:
        save_payment_methods(merged)
    return merged


def save_payment_methods(methods: dict) -> None:
    save_runtime_json(PAYMENT_METHODS_FILE, merge_payment_methods(methods))


def get_payment_method(method_key: str) -> dict | None:
    return load_payment_methods().get(method_key)


def enabled_payment_methods() -> dict:
    return {key: method for key, method in load_payment_methods().items() if method.get("enabled")}


def payment_provider_label(provider: str | None) -> str:
    return PAYMENT_METHOD_LABELS.get(str(provider or ""), provider or "—")


def payment_method_client_title(provider: str) -> str:
    method = get_payment_method(provider) or {}
    return str(method.get("client_title") or PAYMENT_METHOD_LABELS.get(provider, provider))


def update_payment_method(method_key: str, **fields) -> dict | None:
    methods = load_payment_methods()
    method = methods.get(method_key)
    if not method:
        return None
    method.update(fields)
    methods[method_key] = method
    save_payment_methods(methods)
    return method


# ─── orders.json ──────────────────────────────────────────────────────────────

def load_orders() -> list:
    return load_runtime_json(ORDERS_FILE, runtime_default_value(ORDERS_FILE), list)


def save_orders(orders: list) -> None:
    save_runtime_json(ORDERS_FILE, orders)


# ─── users.json ───────────────────────────────────────────────────────────────

def ensure_users_file() -> None:
    if not USERS_FILE.exists():
        save_users({})


def load_users() -> dict:
    return load_runtime_json(USERS_FILE, runtime_default_value(USERS_FILE), dict)


def save_users(users: dict) -> None:
    save_runtime_json(USERS_FILE, users)


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
        "referral_clicks": 0,
        "referrer": None,
        "referral_bonus_awarded": False,
        "new_client_notified": False,
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


def format_rub(amount) -> str:
    try:
        rub = int(amount)
    except (TypeError, ValueError):
        rub = 0
    return f"{rub:,}".replace(",", " ") + " ₽"


def parse_iso_datetime(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return parsed


def rate_lock_now() -> datetime.datetime:
    return datetime.datetime.now(tz=TZ)


def is_card_payment_lock_active(lock: dict | None) -> bool:
    if not isinstance(lock, dict):
        return False
    locked_until = parse_iso_datetime(lock.get("rate_locked_until"))
    return bool(locked_until and locked_until > rate_lock_now())


def normalize_rate(value) -> float | None:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    return rate if USD_RUB_MIN_RATE <= rate <= USD_RUB_MAX_RATE else None


def extract_rate_from_text(text: str) -> float | None:
    """Extract a plausible USD/RUB quote from Yandex HTML/search snippets.

    Yandex pages contain many unrelated values (dates, chart ranges, percents,
    "30 days" labels). Prefer values that are located near currency markers and
    always pass the shared USD/RUB bounds. If no confident value is found, return
    None so the next structured provider can be tried.
    """
    clean_text = re.sub(r"<[^>]+>", " ", text)
    clean_text = re.sub(r"\s+", " ", clean_text)
    currency_context = re.compile(
        r"(?i)(?:usd|доллар|доллара|доллар сша|\$)[^\d]{0,80}"
        r"(\d{2,3}(?:[.,]\d{1,6})?)\s*(?:₽|руб|rub|rur)?|"
        r"(\d{2,3}(?:[.,]\d{1,6})?)\s*(?:₽|руб|rub|rur)[^а-яa-z0-9]{0,80}"
        r"(?:за|=|/)?\s*(?:1\s*)?(?:usd|доллар|доллара|доллар сша|\$)"
    )
    ignored_context = re.compile(
        r"(?i)(?:\bдн\.?\b|\bдень\b|\bдней\b|\bдня\b|"
        r"\bмесяц\w*\b|\bгод\w*\b|\bграфик\w*\b|%|\bпроцент\w*\b|"
        r"\bянвар\w*\b|\bфеврал\w*\b|\bмарт\w*\b|\bапрел\w*\b|\bма[йя]\b|"
        r"\bиюн\w*\b|\bиюл\w*\b|\bавгуст\w*\b|\bсентябр\w*\b|"
        r"\bоктябр\w*\b|\bноябр\w*\b|\bдекабр\w*\b)"
    )
    for match in currency_context.finditer(clean_text):
        raw = next((group for group in match.groups() if group), None)
        if not raw:
            continue
        context = clean_text[max(0, match.start() - 30):match.end() + 30]
        if ignored_context.search(context):
            continue
        rate = normalize_rate(raw.replace(",", "."))
        if rate is not None:
            return rate
        logger.warning("Источник Яндекс вернул невалидное значение: %s, пропущено", raw)
    return None


def normalize_percent(value) -> float | None:
    try:
        percent = float(value)
    except (TypeError, ValueError):
        return None
    return percent if 0 <= percent <= 30 else None


async def fetch_yandex_usd_rub_rate(client: httpx.AsyncClient) -> float | None:
    urls = [
        "https://yandex.ru/finance/currencies/usd-rub",
        "https://yandex.ru/search/?text=курс%20доллара%20к%20рублю",
    ]
    headers = {"User-Agent": "Mozilla/5.0 SLIK-Mobile/1.0"}
    for url in urls:
        try:
            response = await client.get(url, headers=headers)
        except Exception as e:
            logger.warning("Не удалось получить страницу Яндекса USD/RUB: %s", e)
            continue
        if response.status_code >= 400:
            logger.warning("Яндекс USD/RUB вернул HTTP %s", response.status_code)
            continue
        rate = extract_rate_from_text(response.text)
        if rate is not None:
            return rate
        logger.warning("Источник Яндекс не дал уверенного валидного курса USD/RUB, пропущено")
    return None


async def fetch_cbr_usd_rub_rate(client: httpx.AsyncClient) -> float | None:
    response = await client.get("https://www.cbr-xml-daily.ru/daily_json.js")
    response.raise_for_status()
    data = response.json()
    usd = data.get("Valute", {}).get("USD", {})
    value = normalize_rate(usd.get("Value"))
    nominal = normalize_rate(usd.get("Nominal")) or 1
    return value / nominal if value else None


async def fetch_open_er_usd_rub_rate(client: httpx.AsyncClient) -> float | None:
    response = await client.get("https://open.er-api.com/v6/latest/USD")
    response.raise_for_status()
    data = response.json()
    if data.get("result") not in {None, "success"}:
        return None
    return normalize_rate(data.get("rates", {}).get("RUB"))


async def fetch_exchangerate_host_usd_rub_rate(client: httpx.AsyncClient) -> float | None:
    response = await client.get(
        "https://api.exchangerate.host/latest",
        params={"base": "USD", "symbols": "RUB"},
    )
    response.raise_for_status()
    data = response.json()
    if data.get("success") is False:
        return None
    return normalize_rate(data.get("rates", {}).get("RUB"))


def usd_rub_source_providers() -> list[tuple[str, object]]:
    return [
        ("ЦБ РФ", fetch_cbr_usd_rub_rate),
        ("open.er-api.com", fetch_open_er_usd_rub_rate),
        ("exchangerate.host", fetch_exchangerate_host_usd_rub_rate),
        ("Яндекс", fetch_yandex_usd_rub_rate),
    ]


async def collect_usd_rub_source_rates(client: httpx.AsyncClient) -> list[dict]:
    results = []
    for source, provider in usd_rub_source_providers():
        item = {"source": source, "rate": None, "status": "rejected", "reason": "нет валидного курса"}
        try:
            raw_rate = await provider(client)
            rate = normalize_rate(raw_rate)
            if rate is not None:
                item.update({"rate": round(rate, 4), "status": "accepted", "reason": ""})
                logger.info("USD/RUB source %s accepted rate %.4f", source, rate)
            else:
                item["raw_rate"] = raw_rate
                if raw_rate is None:
                    item["reason"] = "источник не вернул курс"
                else:
                    item["reason"] = (
                        f"значение {raw_rate:.4f} ₽ вне допустимого диапазона "
                        f"{USD_RUB_MIN_RATE:g}–{USD_RUB_MAX_RATE:g} ₽"
                    )
                logger.warning("USD/RUB source %s returned invalid value %s, skipped", source, raw_rate)
        except Exception as e:
            item.update({"status": "error", "reason": str(e)})
            logger.warning("USD/RUB source %s failed: %s", source, e)
        results.append(item)
    return results


def calculate_usd_rub_market_rate(source_results: list[dict]) -> tuple[float, str, list[dict]]:
    valid = [item for item in source_results if item.get("status") == "accepted" and normalize_rate(item.get("rate")) is not None]
    filtered = valid
    if len(valid) >= 3:
        sorted_rates = sorted(float(item["rate"]) for item in valid)
        middle = len(sorted_rates) // 2
        median = sorted_rates[middle] if len(sorted_rates) % 2 else (sorted_rates[middle - 1] + sorted_rates[middle]) / 2
        filtered = []
        for item in valid:
            rate = float(item["rate"])
            deviation = abs(rate - median) / median * 100 if median else 0
            if deviation > USD_RUB_MAX_SOURCE_DEVIATION_PERCENT:
                item.update({
                    "status": "rejected",
                    "reason": f"выброс: отклонение {deviation:.2f}% от медианы {median:.4f} ₽",
                })
                logger.warning("USD/RUB source %s rejected as outlier: %.4f", item.get("source"), rate)
            else:
                filtered.append(item)
    if len(filtered) >= 2:
        rate = round(sum(float(item["rate"]) for item in filtered) / len(filtered), 4)
        method = f"среднее по {len(filtered)} источникам"
        logger.info("USD/RUB average rate calculated from %s sources: %.4f", len(filtered), rate)
        return rate, method, source_results
    if len(filtered) == 1:
        rate = round(float(filtered[0]["rate"]), 4)
        method = f"один источник: {filtered[0].get('source')}"
        logger.warning("USD/RUB rate calculated from only one source: %s %.4f", filtered[0].get("source"), rate)
        return rate, method, source_results
    logger.warning("USD/RUB fallback used because all sources failed")
    return USD_RUB_FALLBACK_RATE, "fallback", source_results


async def get_usd_rub_rate() -> tuple[float, str]:
    manual_rate = get_manual_usd_rub_rate()
    if manual_rate:
        return round(manual_rate, 4), "manual"
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
        source_results = await collect_usd_rub_source_rates(client)
    rate, method, _ = calculate_usd_rub_market_rate(source_results)
    return rate, method


async def check_market_usd_rub_rate() -> tuple[float, str]:
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
        source_results = await collect_usd_rub_source_rates(client)
    rate, method, _ = calculate_usd_rub_market_rate(source_results)
    return rate, method


async def check_market_usd_rub_rate_with_diagnostics() -> tuple[float, str, list[dict]]:
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
        source_results = await collect_usd_rub_source_rates(client)
    return calculate_usd_rub_market_rate(source_results)

async def refresh_usd_rub_rate_check() -> tuple[float, str]:
    rate, source, diagnostics = await check_market_usd_rub_rate_with_diagnostics()
    markup = get_configured_usd_rub_markup_percent()
    manual_rate = get_manual_usd_rub_rate()
    base_rate = manual_rate or rate
    save_usd_rub_settings(
        rate_checked_at=now_str(),
        rate_source=source,
        rate_method=source,
        rate_diagnostics=diagnostics,
        market_usd_rub_rate=round(rate, 4),
        final_usd_rub_rate=round(base_rate * (1 + markup / 100), 4),
    )
    return rate, source


async def create_card_payment_lock(plan: dict) -> dict:
    usd_price = parse_price(plan.get("price", "0"))
    rate, source = await get_usd_rub_rate()
    markup_percent = get_configured_usd_rub_markup_percent()
    rub_amount = math.ceil(usd_price * rate * (1 + markup_percent / 100))
    locked_until = rate_lock_now() + datetime.timedelta(seconds=CARD_RATE_LOCK_SECONDS)
    return {
        "usd_price": usd_price,
        "usd_rub_rate": round(rate, 2),
        "rate_source": source,
        "rate_checked_at": now_str(),
        "markup_percent": markup_percent,
        "final_usd_rub_rate": round(rate * (1 + markup_percent / 100), 4),
        "rub_amount": rub_amount,
        "rate_locked_until": locked_until.isoformat(timespec="seconds"),
    }


def build_card_payment_text(plan: dict, card: str, lock: dict) -> str:
    card_text = f"<code>{html_escape(card)}</code>" if card else "Реквизиты карты уточните у менеджера"
    return (
        "💳 <b>Перевод на карту</b>\n"
        f"Сумма: <b>{html_escape(plan.get('price', '—'))}</b>\n"
        "К оплате:\n"
        f"<b>{format_rub(lock.get('rub_amount'))}</b>\n"
        "Сумма зафиксирована на 5 минут.\n"
        "Карта:\n"
        f"{card_text}\n"
        "Переведите сумму и нажмите «Я оплатил»."
    )


def card_payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Я оплатил",       callback_data="payment_done")],
        [InlineKeyboardButton("❌ Отменить заявку", callback_data="cancel_order")],
    ])


def order_payment_details_from_context(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    if context.user_data.get("payment_provider") != "card":
        return None
    lock = context.user_data.get("card_payment_lock")
    if not isinstance(lock, dict):
        return None
    return {
        "usd_price": lock.get("usd_price"),
        "usd_rub_rate": lock.get("usd_rub_rate"),
        "rate_source": lock.get("rate_source"),
        "rate_checked_at": lock.get("rate_checked_at"),
        "markup_percent": lock.get("markup_percent"),
        "final_usd_rub_rate": lock.get("final_usd_rub_rate"),
        "rub_amount": lock.get("rub_amount"),
        "rate_locked_until": lock.get("rate_locked_until"),
    }


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


def normalize_order_status(status: str | None) -> str:
    raw_status = str(status or "new")
    return ORDER_STATUS_ALIASES.get(raw_status, raw_status)


def order_status_label(status: str | None) -> str:
    normalized = normalize_order_status(status)
    return ORDER_STATUS_LABELS.get(normalized, normalized)


def order_status_with_icon(status: str | None) -> str:
    normalized = normalize_order_status(status)
    return f"{ORDER_STATUS_ICONS.get(normalized, '🟡')} {order_status_label(normalized)}"


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


def safe_int(value, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def referral_analytics_for_profile(profile: dict) -> dict:
    referrals = profile.get("referrals") if isinstance(profile.get("referrals"), list) else []
    bought = sum(
        1 for entry in referrals
        if isinstance(entry, dict) and entry.get("bonus_awarded")
    )
    bonuses_awarded = round(sum(
        safe_float(entry.get("bonus_amount"))
        for entry in referrals
        if isinstance(entry, dict) and entry.get("bonus_awarded")
    ), 2)
    referrals_count = len(referrals)
    return {
        "clicks": max(safe_int(profile.get("referral_clicks")), 0),
        "referrals": referrals_count,
        "bought": bought,
        "not_bought": max(referrals_count - bought, 0),
        "bonuses_awarded": bonuses_awarded,
    }


def increment_referral_click(referrer_profile: dict) -> None:
    referrer_profile["referral_clicks"] = max(safe_int(referrer_profile.get("referral_clicks")), 0) + 1


def register_start_referral(user, referrer_id: int | None) -> None:
    if referrer_id is None or str(referrer_id) == str(user.id):
        return
    users = load_users()
    user_key = str(user.id)
    referrer_key = str(referrer_id)
    profile = users.get(user_key) if isinstance(users.get(user_key), dict) else default_user_profile(user)
    referrer_profile = users.get(referrer_key)
    if not isinstance(referrer_profile, dict):
        return

    increment_referral_click(referrer_profile)
    if profile.get("referrer"):
        users[referrer_key] = referrer_profile
        save_users(users)
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
    active_orders = [order for order in user_orders if is_revenue_order(order)]
    profile["orders_count"] = len(active_orders)
    profile["total_spent"] = round(sum(parse_price(order.get("price", "0")) for order in active_orders), 2)
    profile["status"] = calculate_user_status(float(profile.get("total_spent") or 0))
    profile.setdefault("slik_balance", profile.get("bonus_balance", 0))
    profile["bonus_balance"] = profile.get("slik_balance", 0)
    return profile


def award_cashback_if_needed(profile: dict, order: dict) -> float:
    if not is_cashback_enabled():
        return 0.0
    if order.get("cashback_awarded"):
        return 0.0
    if not is_revenue_order(order):
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
        profile.setdefault("referral_clicks", 0)
        profile.setdefault("referrer", None)
        profile.setdefault("referral_bonus_awarded", False)
        profile.setdefault("new_client_notified", False)
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
            if is_revenue_order(user_order)
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
    order.setdefault("status", "new")
    order["created_at"]         = now_str()
    order["created_date"]       = local_date().isoformat()
    order.setdefault("payment_provider", "card")
    order["cashback_awarded"]   = False
    orders.append(order)
    save_orders(orders)
    logger.info("Новый заказ: %s", order)
    return order


def find_order(order_id: int) -> dict | None:
    for order in load_orders():
        try:
            if int(order.get("id")) == int(order_id):
                return order
        except (TypeError, ValueError):
            continue
    return None


def create_checkout_order(user, plan_key: str, plan: dict) -> dict:
    return append_order({
        "product_type": "esim",
        "gb": plan["gb"],
        "days": plan["days"],
        "price": plan["price"],
        "country": "Россия",
        "plan_key": plan_key,
        "payment_method": "",
        "payment_provider": "",
        "name": "",
        "tg_handle": user_tag(user),
        "user_id": user.id,
        "status": "waiting_payment",
        "checkout_created_at": datetime.datetime.now(tz=TZ).isoformat(timespec="seconds"),
        "abandoned_reminder_sent": False,
    })


def apple_id_product_by_id(product_id: str) -> dict | None:
    for products in APPLE_ID_PRODUCTS.values():
        for product in products:
            if product["id"] == product_id:
                return product
    return None


def apple_id_product_plan(product: dict) -> dict:
    return {
        "gb": product["title"],
        "days": "ручная выдача",
        "price": format_usd(product["price_usd"]),
        "product_type": "apple_id",
        "product_id": product["id"],
        "product_title": product["title"],
        "region": product["region"],
        "amount": product["amount"],
        "currency": product["currency"],
        "price_usd": product["price_usd"],
    }


def create_apple_id_checkout_order(user, product: dict) -> dict:
    plan = apple_id_product_plan(product)
    return append_order({
        **plan,
        "country": APPLE_ID_REGION_TITLES.get(product["region"], product["region"]),
        "payment_method": "",
        "payment_provider": "",
        "name": "",
        "tg_handle": user_tag(user),
        "user_id": user.id,
        "status": "waiting_payment",
        "checkout_created_at": datetime.datetime.now(tz=TZ).isoformat(timespec="seconds"),
        "abandoned_reminder_sent": False,
    })


def update_checkout_order(order_id: int, **fields) -> dict | None:
    if order_id is None:
        return None
    orders = load_orders()
    for order in orders:
        try:
            current_id = int(order.get("id"))
        except (TypeError, ValueError):
            continue
        if current_id == int(order_id):
            order.update(fields)
            order["updated_at"] = now_str()
            save_orders(orders)
            return order
    return None


def update_order_status(order_id: int, status: str, updated_by: int | None = None) -> dict | None:
    orders = load_orders()
    for o in orders:
        try:
            current_id = int(o.get("id"))
        except (TypeError, ValueError):
            current_id = None
        if current_id == order_id:
            normalized_status = normalize_order_status(status)
            o["status"]     = normalized_status
            o["updated_at"] = now_str()
            if normalized_status == "issued":
                o.setdefault("issued_at", now_str())
                o.setdefault("expiry_reminder_sent", False)
            if updated_by is not None:
                o["status_updated_by"] = updated_by
            save_orders(orders)
            if o.get("user_id") is not None:
                sync_order_user_stats(o["user_id"])
            return o
    return None


# ─── Проверка прав ────────────────────────────────────────────────────────────

def _matches_principal(user, entry) -> bool:
    if not user or entry is None:
        return False
    entry_str = str(entry).lstrip("@").lower()
    if entry_str.isdigit():
        return str(user.id) == entry_str
    return bool(user.username and user.username.lower() == entry_str)


def _user_in_config_list(user, key: str) -> bool:
    cfg = load_config()
    return any(_matches_principal(user, entry) for entry in cfg.get(key, []))


def is_owner(user) -> bool:
    if not user:
        return False
    if user.username and user.username.lower() == OWNER_USERNAME.lower():
        return True
    admin_env = os.environ.get("ADMIN_CHAT_ID", "").strip()
    if admin_env and str(user.id) == admin_env:
        return True
    return False


def is_admin(user) -> bool:
    if is_owner(user):
        return True
    return _user_in_config_list(user, "admins")


def is_manager(user) -> bool:
    if is_owner(user) or is_admin(user):
        return True
    return _user_in_config_list(user, "managers")


def get_user_role(user) -> str:
    if is_owner(user):
        return ROLE_OWNER
    if _user_in_config_list(user, "admins"):
        return ROLE_ADMIN
    if _user_in_config_list(user, "managers"):
        return ROLE_MANAGER
    users = load_users()
    profile = users.get(str(getattr(user, "id", "")))
    role = str(profile.get("role", "")).upper() if isinstance(profile, dict) else ""
    if role in {ROLE_OWNER, ROLE_ADMIN, ROLE_MANAGER, ROLE_USER}:
        return role
    return ROLE_USER


def has_admin_access(user) -> bool:
    return get_user_role(user) in {ROLE_OWNER, ROLE_ADMIN, ROLE_MANAGER}


def has_owner_access(user) -> bool:
    return get_user_role(user) == ROLE_OWNER


def has_backup_access(user) -> bool:
    return get_user_role(user) in {ROLE_OWNER, ROLE_ADMIN}


async def deny_admin_access(update: Update) -> None:
    if update.callback_query:
        await update.callback_query.answer(ADMIN_ACCESS_DENIED_TEXT, show_alert=True)
    elif update.message:
        await update.message.reply_text(ADMIN_ACCESS_DENIED_TEXT)


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


def ensure_backup_source_file(source_path: Path, display_name: str) -> str | None:
    if source_path.exists():
        return None
    try:
        save_runtime_json(source_path, runtime_default_value(source_path))
    except Exception as error:
        logger.warning("Не удалось создать пустой файл для бэкапа %s: %s", source_path, error)
        return f"{display_name} отсутствует и пропущен"
    return f"{display_name} отсутствовал, создан пустой файл"


def validate_backup_archive(archive_path: Path) -> dict:
    errors: list[str] = []
    try:
        with zipfile.ZipFile(archive_path, "r") as zip_file:
            archive_names = set(zip_file.namelist())
            for _source_path, archive_name, display_name in BACKUP_FILES:
                if archive_name not in archive_names:
                    errors.append(f"{display_name} отсутствует в архиве")
                    continue
                try:
                    json.loads(zip_file.read(archive_name).decode("utf-8"))
                except Exception as error:
                    errors.append(f"{display_name} невалидный JSON: {error}")
    except Exception as error:
        errors.append(f"архив не открывается: {error}")
    return {"ok": not errors, "errors": errors}


def create_backup_archive(created_at: datetime.datetime | None = None) -> dict:
    created_at = created_at or datetime.datetime.now(tz=TZ)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = BACKUPS_DIR / f"backup_{created_at.strftime('%Y-%m-%d_%H-%M')}.zip"
    included: list[str] = []
    skipped: list[str] = []
    warnings: list[str] = []

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for source_path, archive_name, display_name in BACKUP_FILES:
            warning = ensure_backup_source_file(source_path, display_name)
            if warning:
                warnings.append(warning)
                logger.warning("%s: %s", warning, source_path)
            if source_path.exists():
                zip_file.write(source_path, arcname=archive_name)
                included.append(display_name)
            else:
                skipped.append(display_name)

    validation = validate_backup_archive(archive_path)
    if not validation["ok"]:
        warnings.extend(validation["errors"])
        logger.warning("Бэкап %s создан с ошибками проверки: %s", archive_path, validation["errors"])

    cleanup_old_backups()
    logger.info("Создан бэкап runtime-данных: %s", archive_path)
    return {
        "path": archive_path,
        "created_at": created_at,
        "included": included,
        "skipped": skipped,
        "warnings": warnings,
        "validation": validation,
    }


def restore_backup_archive(archive_path: Path) -> dict:
    restored: list[str] = []
    warnings: list[str] = []

    with zipfile.ZipFile(archive_path, "r") as zip_file:
        archive_names = set(zip_file.namelist())
        for target_path, archive_name, display_name in BACKUP_FILES:
            if archive_name not in archive_names:
                warning = f"{display_name} отсутствует в архиве"
                warnings.append(warning)
                logger.warning("%s: %s", warning, archive_path)
                continue
            atomic_write_bytes(target_path, zip_file.read(archive_name))
            restored.append(display_name)

    logger.info("Восстановлен бэкап runtime-данных: %s", archive_path)
    return {
        "path": archive_path,
        "restored": restored,
        "warnings": warnings,
    }


def format_backup_caption(backup_info: dict) -> str:
    created_at = backup_info["created_at"].strftime("%d.%m.%Y %H:%M")
    included = backup_info.get("included") or []
    skipped = backup_info.get("skipped") or []
    warnings = backup_info.get("warnings") or []
    validation = backup_info.get("validation") or validate_backup_archive(backup_info["path"])
    included_text = "\n".join(f"• {name}" for name in included) or "• —"
    text = (
        "💾 Автоматический бэкап SLIK Mobile\n\n"
        "Дата:\n"
        f"{created_at}\n\n"
        "В архиве:\n"
        f"{included_text}\n\n"
        + ("✅ Бэкап проверен" if validation.get("ok") else "⚠️ Есть ошибки проверки")
    )
    if skipped:
        skipped_text = "\n".join(f"• {name}" for name in skipped)
        text += f"\n\nПропущено:\n{skipped_text}"
    if warnings:
        warnings_text = "\n".join(f"• {warning}" for warning in warnings)
        text += f"\n\nПредупреждения:\n{warnings_text}"
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
        admin_id = get_tech_alerts_chat_id()
        if not admin_id:
            logger.warning("Технический чат и ADMIN_CHAT_ID не заданы; автоматический бэкап сохранён локально: %s", backup_info["path"])
            return
        await send_backup_archive(context.bot, admin_id, backup_info)
    except Exception:
        logger.exception("Ошибка автоматического бэкапа SLIK Mobile")


async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_backup_access(update.effective_user):
        await deny_admin_access(update)
        return
    try:
        backup_info = create_backup_archive()
        await send_backup_archive(context.bot, update.effective_chat.id, backup_info)
        await update.message.reply_text("Бэкап создан и отправлен.")
    except Exception:
        logger.exception("Не удалось создать или отправить ручной бэкап")
        await update.message.reply_text("Не удалось создать бэкап. Ошибка записана в лог.")


async def cmd_backups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_backup_access(update.effective_user):
        await deny_admin_access(update)
        return
    archives = list_backup_archives()[:10]
    if not archives:
        await update.message.reply_text("💾 Последние бэкапы:\n\nПока нет архивов.")
        return
    lines = ["💾 Последние бэкапы:", ""]
    lines.extend(f"{index}. {archive.name}" for index, archive in enumerate(archives, start=1))
    await update.message.reply_text("\n".join(lines), reply_markup=backups_keyboard())


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
    """Отправляет уведомление о действии клиента в выбранный чат."""
    admin_id = get_client_activity_chat_id()
    _route_chat_id, source = get_client_activity_chat_source()
    logger.info("notification route selected: type=client_activity chat_id=%s source=%s helper=get_client_activity_chat_id", admin_id, source)
    if not admin_id:
        return
    text = f"👣 <b>Действие клиента</b>\n\nДействие: {html_escape(action)}"
    if extra:
        text += f"\n{html_escape(extra)}"
    text += (
        f"\n\n👤 Имя: {html_escape(user.full_name)}\n"
        f"📨 Username: {user_tag_html(user)}\n"
        f"🆔 Telegram ID: <code>{user.id}</code>\n"
        f"🕒 Время: {now_str()}\n"
        f"Маршрут: client_activity · {html_escape(source)} · <code>{html_escape(str(admin_id))}</code>"
    )
    try:
        await context.bot.send_message(chat_id=admin_id, text=text, parse_mode="HTML")
    except Exception as e:
        logger.error("track_action error: %s", e)


async def notify_new_client(
    context: ContextTypes.DEFAULT_TYPE,
    user,
    referrer_id: int | None = None,
) -> None:
    """Отправляет однократное уведомление о новом клиенте в выделенный чат."""
    if not user or has_admin_access(user):
        return

    users = load_users()
    key = str(user.id)
    profile = users.get(key)
    if not isinstance(profile, dict):
        return
    if profile.get("new_client_notified"):
        return

    chat_id = get_new_clients_chat_id()
    _route_chat_id, route_source = get_new_clients_chat_source()
    logger.info("notification route selected: type=new_clients chat_id=%s source=%s helper=get_new_clients_chat_id", chat_id, route_source)
    if not chat_id:
        return

    saved_referrer_id = profile.get("referrer")
    effective_referrer_id = referrer_id or saved_referrer_id
    source = "referral" if effective_referrer_id else "direct"
    text = (
        "🆕 <b>Новый клиент</b>\n\n"
        f"Имя: <b>{html_escape(user.full_name or '—')}</b>\n"
        f"Username: <b>{user_tag_html(user)}</b>\n"
        f"User ID: <code>{user.id}</code>\n"
        f"Время: {html_escape(now_str())}\n"
        f"Источник: {html_escape(source)}"
    )
    if effective_referrer_id:
        text += f"\nПришёл по приглашению: <code>{html_escape(str(effective_referrer_id))}</code>"

    try:
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    except Exception as e:
        logger.error("new client notification error: %s", e)
        return

    users = load_users()
    profile = users.get(key)
    if isinstance(profile, dict):
        profile["new_client_notified"] = True
        users[key] = profile
        save_users(users)


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


ORDER_LIST_FILTERS = {
    "new": {"new"},
    "in_progress": {"in_progress"},
    "issued": {"issued"},
    "cancelled": {"cancelled"},
    "pending": {"new", "in_progress"},
}
ORDER_LIST_TITLES = {
    "new": "🟡 Новые заявки",
    "in_progress": "🔵 В работе",
    "issued": "🟢 Выданные заявки",
    "cancelled": "🔴 Отменённые заявки",
    "pending": "🟡 Активные заявки",
}
STATUS_NOTIFICATION_TEXT = {
    "in_progress": "🔵 Ваш заказ {number} взят в работу.",
    "issued": "🟢 Ваш заказ {number} выдан.\nЕсли eSIM уже отправлена менеджером, проверьте чат.",
    "cancelled": "🔴 Ваш заказ {number} отменён.\nЕсли это ошибка — напишите в поддержку.",
}


def filter_orders_by_status(orders: list, filter_key: str) -> list:
    statuses = ORDER_LIST_FILTERS.get(filter_key, {filter_key})
    return [order for order in orders if normalize_order_status(order.get("status")) in statuses]


def order_number_plain(order: dict) -> str:
    number = str(order.get("number") or f"#{order.get('id', '—')}")
    return number if number.startswith("#") else f"#{number}"


def format_order_button_text(order: dict) -> str:
    if order.get("product_type") == "apple_id":
        amount = order.get("amount", "—")
        currency = order.get("currency", "")
        nominal = f"${amount}" if currency == "USD" else f"{amount}₺" if currency == "TRY" else f"{amount} {currency}".strip()
        region = APPLE_ID_REGION_TITLES.get(order.get("region"), order.get("region", "—"))
        return f"{order_number_plain(order)} — 🍎 Apple ID / {region} / {nominal}"
    return (
        f"{order_number_plain(order)} — {order.get('country', 'Россия')} "
        f"{order.get('gb', '—')} — {order.get('price', '—')}"
    )


def build_orders_dashboard() -> str:
    orders = load_orders()
    today = local_date()
    today_orders = orders_by_period(orders, today)
    week_orders = orders_by_period(orders, today - datetime.timedelta(days=7))
    month_orders = orders_by_period(orders, today - datetime.timedelta(days=30))

    def count_status(items: list, status: str) -> int:
        return sum(1 for order in items if normalize_order_status(order.get("status")) == status)

    week_revenue_orders = [order for order in week_orders if is_revenue_order(order)]
    month_revenue_orders = [order for order in month_orders if is_revenue_order(order)]
    week_waiting_payment = count_status(week_orders, "waiting_payment")
    month_waiting_payment = count_status(month_orders, "waiting_payment")
    week_total = sum(parse_price(order.get("price", "0")) for order in week_revenue_orders)
    month_total = sum(parse_price(order.get("price", "0")) for order in month_revenue_orders)
    return (
        "📋 <b>Заказы</b>\n\n"
        "<b>Сегодня:</b>\n"
        f"🆕 Новых: <b>{count_status(today_orders, 'new')}</b>\n"
        f"🔵 В работе: <b>{count_status(today_orders, 'in_progress')}</b>\n"
        f"🟢 Выдано: <b>{count_status(today_orders, 'issued')}</b>\n"
        f"🔴 Отменено: <b>{count_status(today_orders, 'cancelled')}</b>\n\n"
        "<b>За 7 дней:</b>\n"
        f"📦 Всего заказов: <b>{len(week_revenue_orders)}</b>\n"
        f"🟠 Ожидают оплаты: <b>{week_waiting_payment}</b>\n"
        f"💵 Сумма: <b>${week_total:.2f}</b>\n\n"
        "<b>За 30 дней:</b>\n"
        f"📦 Всего заказов: <b>{len(month_revenue_orders)}</b>\n"
        f"🟠 Ожидают оплаты: <b>{month_waiting_payment}</b>\n"
        f"💵 Сумма: <b>${month_total:.2f}</b>\n\n"
        "<b>Быстрые действия:</b>\n"
        "🟡 Новые заявки\n"
        "🔵 В работе\n"
        "🟢 Выданные\n"
        "🔴 Отменённые\n"
        "📊 Статистика"
    )


def orders_dashboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟡 Новые", callback_data="orders_list:new")],
        [InlineKeyboardButton("🔵 В работе", callback_data="orders_list:in_progress")],
        [InlineKeyboardButton("🟢 Выданные", callback_data="orders_list:issued")],
        [InlineKeyboardButton("🔴 Отменённые", callback_data="orders_list:cancelled")],
        [InlineKeyboardButton("📊 Статистика", callback_data="orders_stats")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel")],
    ])


def order_list_keyboard(filter_key: str) -> InlineKeyboardMarkup:
    orders = filter_orders_by_status(load_orders(), filter_key)
    latest_orders = sorted(orders, key=order_sort_key, reverse=True)[:10]
    rows = [
        [InlineKeyboardButton(format_order_button_text(order), callback_data=f"order_card:{order.get('id')}")]
        for order in latest_orders
    ]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_orders")])
    return InlineKeyboardMarkup(rows)


def build_order_list_text(filter_key: str) -> str:
    title = ORDER_LIST_TITLES.get(filter_key, "📋 Заявки")
    orders = filter_orders_by_status(load_orders(), filter_key)
    if not orders:
        return f"{title}\n\nЗаявок в этой категории нет."
    return f"{title}\n\nПоследние 10 заказов:"


def find_order(order_id: int) -> dict | None:
    for order in load_orders():
        try:
            current_id = int(order.get("id"))
        except (TypeError, ValueError):
            current_id = None
        if current_id == order_id:
            return order
    return None


def build_order_card_text(order: dict) -> str:
    payment_provider = order.get("payment_provider") or "card"
    payment_method = payment_provider_label(payment_provider)
    payment_details = order.get("payment_details") if isinstance(order.get("payment_details"), dict) else {}
    card_lines = ""
    if payment_provider == "card":
        rate = float(payment_details.get("usd_rub_rate") or 0)
        markup = float(payment_details.get("markup_percent") or 0)
        final_rate = float(payment_details.get("final_usd_rub_rate") or 0)
        rate_checked_at = payment_details.get("rate_checked_at") or "—"
        card_lines = (
            f"💳 К оплате: <b>{html_escape(format_rub(payment_details.get('rub_amount')))}</b>\n"
            f"Курс: <b>{rate:.2f} ₽</b>\n"
            f"Проверка курса: <b>{html_escape(rate_checked_at)}</b>\n"
            f"Комиссия: <b>{markup:g}%</b>\n"
            f"Итоговый курс: <b>{final_rate:.4f} ₽</b>\n"
        )
    username = order.get("tg_handle") or "—"
    if order.get("product_type") == "apple_id":
        amount = order.get("amount", "—")
        currency = order.get("currency", "")
        nominal = f"${amount}" if currency == "USD" else f"{amount}₺" if currency == "TRY" else f"{amount} {currency}".strip()
        region = APPLE_ID_REGION_TITLES.get(order.get("region"), order.get("region", "—"))
        return (
            f"🍎 <b>Заказ Apple ID {html_escape(order_number_plain(order))}</b>\n\n"
            f"👤 Клиент: <b>{html_escape(order.get('name', '—'))}</b>\n"
            f"🆔 Telegram ID: <code>{html_escape(order.get('user_id', '—'))}</code>\n"
            f"Username: <b>{html_escape(username)}</b>\n\n"
            f"Тип товара: <b>Apple ID</b>\n"
            f"Регион: <b>{html_escape(region)}</b>\n"
            f"Номинал: <b>{html_escape(nominal)}</b>\n"
            f"Товар: <b>{html_escape(order.get('product_title', order.get('gb', '—')))}</b>\n"
            f"💵 Цена: <b>{html_escape(order.get('price', '—'))}</b>\n\n"
            "<b>Способ оплаты:</b>\n"
            f"{html_escape(payment_method)}\n\n"
            f"{card_lines}"
            "<b>Статус:</b>\n"
            f"{html_escape(order_status_with_icon(order.get('status')))}\n\n"
            "<b>Дата:</b>\n"
            f"{html_escape(format_order_date(order))}"
        )
    return (
        f"📦 <b>Заказ {html_escape(order_number_plain(order))}</b>\n\n"
        f"👤 Клиент: <b>{html_escape(order.get('name', '—'))}</b>\n"
        f"🆔 Telegram ID: <code>{html_escape(order.get('user_id', '—'))}</code>\n"
        f"Username: <b>{html_escape(username)}</b>\n\n"
        f"🌍 Страна: <b>{html_escape(order.get('country', 'Россия'))}</b>\n"
        f"📦 Тариф: <b>{html_escape(order.get('gb', '—'))}</b>\n"
        f"💵 Цена: <b>{html_escape(order.get('price', '—'))}</b>\n\n"
        "<b>Способ оплаты:</b>\n"
        f"{html_escape(payment_method)}\n\n"
        f"{card_lines}"
        "<b>Статус:</b>\n"
        f"{html_escape(order_status_with_icon(order.get('status')))}\n\n"
        "<b>Дата:</b>\n"
        f"{html_escape(format_order_date(order))}"
    )


def order_card_keyboard(order_id: int, back_callback: str = "admin_orders") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ В работу", callback_data=f"order_status:in_progress:{order_id}")],
        [InlineKeyboardButton("📤 Выдано", callback_data=f"order_status:issued:{order_id}")],
        [InlineKeyboardButton("❌ Отменить", callback_data=f"order_status:cancelled:{order_id}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=back_callback)],
    ])


def build_orders_stats_text() -> str:
    orders = load_orders()
    today = local_date()
    week_count, week_total = calc_stats(orders, today - datetime.timedelta(days=7))
    month_count, month_total = calc_stats(orders, today - datetime.timedelta(days=30))
    return (
        "📊 <b>Статистика заказов</b>\n\n"
        f"За 7 дней: <b>{week_count}</b> / <b>${week_total:.2f}</b>\n"
        f"За 30 дней: <b>{month_count}</b> / <b>${month_total:.2f}</b>"
    )


def is_revenue_order(order: dict) -> bool:
    return normalize_order_status(order.get("status")) not in {"cancelled", "waiting_payment"}


def analytics_orders_since(orders: list, since: datetime.date) -> list[dict]:
    return [
        order for order in orders
        if (moment := parse_order_datetime(order)) and moment.astimezone(TZ).date() >= since
    ]


def analytics_order_stats(orders: list) -> tuple[int, float]:
    revenue_orders = [order for order in orders if is_revenue_order(order)]
    revenue = round(sum(parse_price(order.get("price", "0")) for order in revenue_orders), 2)
    return len(revenue_orders), revenue


def parse_user_created_datetime(value: str | None) -> datetime.datetime | None:
    parsed = parse_iso_datetime(value)
    if parsed:
        return parsed
    raw_value = str(value or "")
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(raw_value[:16], fmt).replace(tzinfo=TZ)
        except ValueError:
            continue
    return None


def new_clients_count_for_date(users: dict, target_date: datetime.date) -> int:
    count = 0
    for profile in users.values():
        if not isinstance(profile, dict):
            continue
        created_at = parse_user_created_datetime(str(profile.get("created_at") or ""))
        if created_at and created_at.astimezone(TZ).date() == target_date:
            count += 1
    return count


def top_countries_by_orders(orders: list, limit: int = 5) -> list[tuple[str, int]]:
    country_counts: dict[str, int] = {}
    for order in orders:
        if not is_revenue_order(order):
            continue
        country = str(order.get("country") or "Россия").strip() or "Россия"
        country_counts[country] = country_counts.get(country, 0) + 1
    return sorted(country_counts.items(), key=lambda item: (-item[1], item[0]))[:limit]


def build_analytics_text() -> str:
    orders = load_orders()
    users = load_users()
    today = local_date()
    today_orders = analytics_orders_since(orders, today)
    week_orders = analytics_orders_since(orders, today - datetime.timedelta(days=6))
    month_orders = analytics_orders_since(orders, today - datetime.timedelta(days=29))

    today_count, today_revenue = analytics_order_stats(today_orders)
    week_count, week_revenue = analytics_order_stats(week_orders)
    month_count, month_revenue = analytics_order_stats(month_orders)
    all_count, all_revenue = analytics_order_stats(orders)
    average_order = round(all_revenue / all_count, 2) if all_count else 0
    new_clients_today = new_clients_count_for_date(users, today)
    top_countries = top_countries_by_orders(orders)
    top_countries_text = (
        "\n".join(f"{index}. {html_escape(country)} — <b>{count}</b>" for index, (country, count) in enumerate(top_countries, start=1))
        if top_countries else "—"
    )

    return (
        "📊 <b>Аналитика</b>\n\n"
        "📅 <b>Сегодня</b>\n"
        f"• Заказов: <b>{today_count}</b>\n"
        f"• Выручка: <b>{format_usd_cents(today_revenue)}</b>\n"
        f"• Новых клиентов: <b>{new_clients_today}</b>\n\n"
        "📅 <b>Последние 7 дней</b>\n"
        f"• Заказов: <b>{week_count}</b>\n"
        f"• Выручка: <b>{format_usd_cents(week_revenue)}</b>\n\n"
        "📅 <b>Последние 30 дней</b>\n"
        f"• Заказов: <b>{month_count}</b>\n"
        f"• Выручка: <b>{format_usd_cents(month_revenue)}</b>\n\n"
        "💰 <b>Средний чек</b>\n"
        f"<b>{format_usd_cents(average_order)}</b>\n\n"
        "🌍 <b>Топ-5 стран по количеству заказов</b>\n"
        f"{top_countries_text}"
    )


def analytics_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_analytics_back")]])


CLIENT_CATEGORY_TITLES = {
    "no_orders": "🆕 Без покупок",
    "buyers": "💰 Покупатели",
    "return": "🔄 Вернуть клиентов",
    "top": "💎 Топ клиенты",
}
CLIENT_INPUT_BALANCE = "client_balance"
CLIENT_INPUT_MESSAGE = "client_message"
CLIENT_INPUT_SEARCH = "client_search"
BROADCAST_INPUT_MESSAGE = "broadcast_message"
NOTIFICATION_CHAT_INPUT = "notification_chat"
BROADCAST_CATEGORIES = {
    "all": "👥 Все клиенты",
    "no_orders": "🆕 Без заказов",
    "buyers": "💳 С заказами",
    "balance": "💰 С балансом",
    "vip": "👑 VIP / Premium / Ambassador",
    "regular": "🧳 Traveller / Explorer / Nomad",
    "referrers": "👥 Рефереры",
    "inactive": "😴 Неактивные",
}


def load_balance_log() -> list:
    return load_runtime_json(BALANCE_LOG_FILE, runtime_default_value(BALANCE_LOG_FILE), list)


def append_balance_log(admin_id: int, user_id: int, amount: float) -> None:
    log = load_balance_log()
    log.append({
        "admin_id": admin_id,
        "user_id": user_id,
        "amount": amount,
        "created_at": datetime.datetime.now(tz=TZ).isoformat(timespec="seconds"),
    })
    save_runtime_json(BALANCE_LOG_FILE, log)


def parse_order_datetime(order: dict) -> datetime.datetime | None:
    created_date = order.get("created_date")
    if created_date:
        try:
            return datetime.datetime.combine(datetime.date.fromisoformat(str(created_date)), datetime.time.min, tzinfo=TZ)
        except ValueError:
            pass
    created_at = str(order.get("created_at") or "")
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.datetime.strptime(created_at[:16], fmt)
            return parsed.replace(tzinfo=TZ)
        except ValueError:
            continue
    return None


def days_ago_text(moment: datetime.datetime | None) -> str:
    if not moment:
        return "—"
    today = datetime.datetime.now(tz=TZ).date()
    days = max((today - moment.astimezone(TZ).date()).days, 0)
    if days == 0:
        return "сегодня"
    if days == 1:
        return "1 день назад"
    if 2 <= days <= 4:
        return f"{days} дня назад"
    return f"{days} дней назад"


def client_display_name(user_id: str, profile: dict) -> str:
    name = str(profile.get("full_name") or "").strip()
    if name:
        return name
    username = str(profile.get("username") or "").strip().lstrip("@")
    if username:
        return f"@{username}"
    return f"ID {user_id}"


def collect_clients() -> list[dict]:
    users = load_users()
    orders = load_orders()
    orders_by_user: dict[str, list] = {}
    for order in orders:
        user_id = order.get("user_id")
        if user_id is not None:
            orders_by_user.setdefault(str(user_id), []).append(order)

    clients = []
    for user_id, profile in users.items():
        if not isinstance(profile, dict):
            continue
        user_orders = orders_by_user.get(str(user_id), [])
        active_orders = [order for order in user_orders if is_revenue_order(order)]
        total_spent = round(sum(parse_price(order.get("price", "0")) for order in active_orders), 2)
        order_dates = [date for date in (parse_order_datetime(order) for order in active_orders) if date]
        last_order_at = max(order_dates, default=None)
        orders_count = len(active_orders)
        status = calculate_user_status(total_spent)
        created_at = parse_iso_datetime(str(profile.get("created_at") or ""))
        if created_at is None:
            for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
                try:
                    created_at = datetime.datetime.strptime(str(profile.get("created_at") or ""), fmt).replace(tzinfo=TZ)
                    break
                except ValueError:
                    pass
        clients.append({
            "user_id": str(user_id),
            "profile": profile,
            "orders": sorted(active_orders, key=order_sort_key, reverse=True),
            "orders_count": orders_count,
            "total_spent": total_spent,
            "last_order_at": last_order_at,
            "created_at": created_at or datetime.datetime.min.replace(tzinfo=TZ),
            "status": status,
        })
    return clients


def client_category_items(category: str) -> list[dict]:
    clients = collect_clients()
    now_date = datetime.datetime.now(tz=TZ).date()
    if category == "no_orders":
        items = [client for client in clients if client["orders_count"] == 0]
        return sorted(items, key=lambda client: client["created_at"], reverse=True)[:20]
    if category == "buyers":
        items = [client for client in clients if client["orders_count"] > 0]
        return sorted(items, key=lambda client: client["last_order_at"] or client["created_at"], reverse=True)[:20]
    if category == "return":
        items = [
            client for client in clients
            if client["orders_count"] > 0
            and client["last_order_at"]
            and (now_date - client["last_order_at"].astimezone(TZ).date()).days > 30
        ]
        return sorted(items, key=lambda client: client["last_order_at"] or client["created_at"], reverse=True)[:20]
    if category == "top":
        items = [client for client in clients if client["orders_count"] > 0]
        return sorted(items, key=lambda client: client["total_spent"], reverse=True)[:20]
    return []


def clients_dashboard_text() -> str:
    clients = collect_clients()
    now_date = datetime.datetime.now(tz=TZ).date()
    no_orders = sum(1 for client in clients if client["orders_count"] == 0)
    buyers = sum(1 for client in clients if client["orders_count"] > 0)
    return_clients = sum(
        1 for client in clients
        if client["orders_count"] > 0
        and client["last_order_at"]
        and (now_date - client["last_order_at"].astimezone(TZ).date()).days > 30
    )
    premium = sum(1 for client in clients if client["status"] in {"Premium", "Ambassador"})
    return (
        "👥 <b>Клиенты</b>\n"
        f"Всего клиентов: <b>{len(clients)}</b>\n"
        f"🆕 Без покупок: <b>{no_orders}</b>\n"
        f"💰 Покупатели: <b>{buyers}</b>\n"
        f"🔄 Не покупали более 30 дней: <b>{return_clients}</b>\n"
        f"💎 Premium/VIP: <b>{premium}</b>"
    )


def clients_dashboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆕 Без покупок", callback_data="clients_cat:no_orders")],
        [InlineKeyboardButton("💰 Покупатели", callback_data="clients_cat:buyers")],
        [InlineKeyboardButton("🔄 Вернуть клиентов", callback_data="clients_cat:return")],
        [InlineKeyboardButton("💎 Топ клиенты", callback_data="clients_cat:top")],
        [InlineKeyboardButton("🔍 Найти клиента", callback_data="clients_search")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel")],
    ])


def client_list_text(category: str) -> str:
    title = CLIENT_CATEGORY_TITLES.get(category, "👥 Клиенты")
    items = client_category_items(category)
    if not items:
        return f"{title}\n\nКлиентов в этой категории нет."
    lines = [title, "", "Последние 20 клиентов:" if category != "top" else "ТОП-20 клиентов:", ""]
    for client in items:
        lines.append(f"{html_escape(client_display_name(client['user_id'], client['profile']))} — <b>{format_usd_cents(client['total_spent'])}</b>")
    return "\n".join(lines)


def client_list_keyboard(category: str) -> InlineKeyboardMarkup:
    rows = []
    for client in client_category_items(category):
        name = client_display_name(client["user_id"], client["profile"])
        rows.append([InlineKeyboardButton(f"{name} — {format_usd(client['total_spent'])}", callback_data=f"client_card:{client['user_id']}:{category}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_clients")])
    return InlineKeyboardMarkup(rows)


def find_client(user_id: str) -> dict | None:
    return next((client for client in collect_clients() if client["user_id"] == str(user_id)), None)


def client_card_text(user_id: str) -> str:
    client = find_client(user_id)
    if not client:
        return "Клиент не найден."
    profile = client["profile"]
    username = str(profile.get("username") or "").strip().lstrip("@")
    username_text = f"@{username}" if username else "—"
    referral_stats = referral_analytics_for_profile(profile)
    return (
        f"👤 <b>{html_escape(client_display_name(user_id, profile))}</b>\n"
        f"🆔 Telegram ID: <code>{html_escape(user_id)}</code>\n"
        "Username:\n"
        f"{html_escape(username_text)}\n"
        f"📦 Заказов: <b>{client['orders_count']}</b>\n"
        "💰 Потрачено:\n"
        f"<b>{format_usd_cents(client['total_spent'])}</b>\n"
        "💵 SLIK Balance:\n"
        f"<b>{format_usd_cents(profile.get('slik_balance', profile.get('bonus_balance', 0)))}</b>\n"
        "🏅 Статус:\n"
        f"<b>{html_escape(format_status(client['status']))}</b>\n"
        "👥 Реферальная аналитика:\n"
        f"Переходов: <b>{referral_stats['clicks']}</b>\n"
        f"Купили: <b>{referral_stats['bought']}</b>\n"
        f"Не купили: <b>{referral_stats['not_bought']}</b>\n"
        f"Бонусов начислено: <b>{format_usd_cents(referral_stats['bonuses_awarded'])}</b>\n"
        "📅 Последний заказ:\n"
        f"<b>{html_escape(days_ago_text(client['last_order_at']))}</b>"
    )


def client_card_keyboard(user_id: str, back: str = "buyers", user=None) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("📦 Заказы клиента", callback_data=f"client_orders:{user_id}")]]
    if get_user_role(user) in {ROLE_OWNER, ROLE_ADMIN}:
        rows.append([InlineKeyboardButton("💰 Изменить баланс", callback_data=f"client_balance:{user_id}")])
        rows.append([InlineKeyboardButton("✉️ Написать клиенту", callback_data=f"client_message:{user_id}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"clients_cat:{back}" if back in CLIENT_CATEGORY_TITLES else "admin_clients")])
    return InlineKeyboardMarkup(rows)


def client_orders_text(user_id: str) -> str:
    client = find_client(user_id)
    if not client:
        return "Клиент не найден."
    if not client["orders"]:
        return f"📦 <b>Заказы клиента</b>\n\nУ клиента {html_escape(client_display_name(user_id, client['profile']))} пока нет заказов."
    return f"📦 <b>Заказы клиента</b>\n\n{html_escape(client_display_name(user_id, client['profile']))}: <b>{len(client['orders'])}</b>"


def client_orders_keyboard(user_id: str) -> InlineKeyboardMarkup:
    client = find_client(user_id)
    rows = []
    if client:
        for order in client["orders"]:
            rows.append([InlineKeyboardButton(format_order_button_text(order), callback_data=f"client_order_card:{user_id}:{order.get('id')}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"client_card:{user_id}:buyers")])
    return InlineKeyboardMarkup(rows)


def search_clients(query_text: str) -> list[dict]:
    query = query_text.strip().lower().lstrip("@")
    if not query:
        return []
    results = []
    for client in collect_clients():
        profile = client["profile"]
        haystack = " ".join([
            client["user_id"],
            str(profile.get("telegram_id") or ""),
            str(profile.get("username") or "").lower().lstrip("@"),
            str(profile.get("full_name") or "").lower(),
        ])
        if query in haystack:
            results.append(client)
    return results[:20]


def search_results_text(results: list[dict], query_text: str) -> str:
    if not results:
        return f"🔍 <b>Поиск клиента</b>\n\nПо запросу <b>{html_escape(query_text)}</b> ничего не найдено."
    lines = ["🔍 <b>Поиск клиента</b>", "", f"Найдено: <b>{len(results)}</b>", ""]
    for client in results:
        lines.append(f"{html_escape(client_display_name(client['user_id'], client['profile']))} — <b>{format_usd_cents(client['total_spent'])}</b>")
    return "\n".join(lines)


def search_results_keyboard(results: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"{client_display_name(client['user_id'], client['profile'])} — {format_usd(client['total_spent'])}", callback_data=f"client_card:{client['user_id']}:search")]
        for client in results
    ]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_clients")])
    return InlineKeyboardMarkup(rows)


def has_broadcast_access(user) -> bool:
    return get_user_role(user) in {ROLE_OWNER, ROLE_ADMIN}


def broadcast_category_title(category: str) -> str:
    return BROADCAST_CATEGORIES.get(category, "📰 Рассылка")


def broadcast_recipients(category: str) -> list[dict]:
    clients = collect_clients()
    now_date = datetime.datetime.now(tz=TZ).date()

    def has_positive_balance(client: dict) -> bool:
        profile = client["profile"]
        return (
            safe_float(profile.get("slik_balance", profile.get("bonus_balance", 0))) > 0
            or safe_float(profile.get("bonus_balance")) > 0
        )

    def is_referrer(client: dict) -> bool:
        profile = client["profile"]
        referrals = profile.get("referrals")
        return (isinstance(referrals, list) and len(referrals) > 0) or safe_int(profile.get("referral_clicks")) > 0

    def is_inactive(client: dict) -> bool:
        if client["orders_count"] == 0:
            return True
        last_order_at = client.get("last_order_at")
        return bool(last_order_at and (now_date - last_order_at.astimezone(TZ).date()).days > 30)

    filters_by_category = {
        "all": lambda client: True,
        "no_orders": lambda client: client["orders_count"] == 0,
        "buyers": lambda client: client["orders_count"] > 0,
        "balance": has_positive_balance,
        "vip": lambda client: client["status"] in {"Premium", "Ambassador"},
        "regular": lambda client: client["status"] in {"Traveller", "Explorer", "Nomad"},
        "referrers": is_referrer,
        "inactive": is_inactive,
    }
    predicate = filters_by_category.get(category)
    if not predicate:
        return []
    return [client for client in clients if predicate(client)]


def broadcast_menu_text() -> str:
    return "📰 <b>Рассылки</b>\n\nВыберите категорию получателей:"


def broadcast_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(title, callback_data=f"broadcast_cat:{category}")]
        for category, title in BROADCAST_CATEGORIES.items()
    ] + [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel")]])


def broadcast_category_text(category: str) -> str:
    recipients_count = len(broadcast_recipients(category))
    return (
        "📰 <b>Рассылки</b>\n\n"
        f"Категория: <b>{html_escape(broadcast_category_title(category))}</b>\n"
        f"Примерно получателей: <b>{recipients_count}</b>"
    )


def broadcast_category_keyboard(category: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ Написать сообщение", callback_data=f"broadcast_compose:{category}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_news")],
    ])


def broadcast_preview_text(category: str, message_text: str) -> str:
    recipients_count = len(broadcast_recipients(category))
    return (
        "📰 <b>Предпросмотр рассылки</b>\n\n"
        f"Категория: <b>{html_escape(broadcast_category_title(category))}</b>\n"
        f"Получателей: <b>{recipients_count}</b>\n\n"
        "Текст сообщения:\n"
        f"{html_escape(message_text)}"
    )


def broadcast_preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Отправить", callback_data="broadcast_send")],
        [InlineKeyboardButton("❌ Отмена", callback_data="broadcast_cancel")],
    ])


async def send_broadcast_message(context: ContextTypes.DEFAULT_TYPE, recipients: list[dict], message_text: str) -> tuple[int, int]:
    sent = 0
    failed = 0
    for client in recipients:
        try:
            await context.bot.send_message(chat_id=int(client["user_id"]), text=message_text)
            sent += 1
        except Exception as error:
            failed += 1
            logger.warning("Не удалось отправить рассылку пользователю %s: %s", client.get("user_id"), error)
    return sent, failed


async def notify_client_order_status(context: ContextTypes.DEFAULT_TYPE, order: dict) -> None:
    user_id = order.get("user_id")
    if user_id is None:
        return
    status = normalize_order_status(order.get("status"))
    template = STATUS_NOTIFICATION_TEXT.get(status)
    if not template:
        return
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=template.format(number=order_number_plain(order)),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👨‍💻 Поддержка", url=SUPPORT_URL)],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")],
            ]),
        )
    except Exception as e:
        logger.warning("Не удалось уведомить клиента о статусе заказа %s: %s", order.get("id"), e)


def format_file_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def backup_info_from_path(path: Path) -> dict:
    return {
        "path": path,
        "created_at": datetime.datetime.fromtimestamp(path.stat().st_mtime, tz=TZ),
        "included": [],
        "skipped": [],
        "validation": validate_backup_archive(path),
    }


def build_backups_dashboard() -> str:
    archives = list_backup_archives()
    latest = archives[0] if archives else None
    latest_time = datetime.datetime.fromtimestamp(latest.stat().st_mtime, tz=TZ).strftime("%d.%m.%Y %H:%M") if latest else "—"
    latest_size = format_file_size(latest.stat().st_size) if latest else "—"
    return (
        "💾 <b>Бэкапы</b>\n\n"
        "<b>Последний бэкап:</b>\n"
        f"{latest_time}\n\n"
        "<b>Всего архивов:</b>\n"
        f"{len(archives)}\n\n"
        "<b>Последний размер:</b>\n"
        f"{latest_size}"
    )


def backups_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Скачать последний", callback_data="backup_download_latest")],
        [InlineKeyboardButton("🆕 Создать бэкап", callback_data="backup_create")],
        [InlineKeyboardButton("📋 Список архивов", callback_data="backup_list")],
        [InlineKeyboardButton("♻️ Восстановить последний", callback_data="backup_restore_prompt")],
        [InlineKeyboardButton("🗑 Очистить старые", callback_data="backup_cleanup_prompt")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel")],
    ])


def backup_restore_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Восстановить", callback_data="backup_restore_latest")],
        [InlineKeyboardButton("❌ Нет", callback_data="admin_backups")],
    ])


def backup_cleanup_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да", callback_data="backup_cleanup_yes")],
        [InlineKeyboardButton("❌ Нет", callback_data="admin_backups")],
    ])


def build_backup_list_text() -> str:
    archives = list_backup_archives()[:10]
    lines = ["💾 <b>Последние архивы</b>", ""]
    if archives:
        lines.extend(f"{index}. <code>{archive.name}</code> — {format_file_size(archive.stat().st_size)}" for index, archive in enumerate(archives, start=1))
    else:
        lines.append("Архивы не найдены.")
    return "\n".join(lines)




def read_runtime_json_status(path: Path) -> dict:
    if not path.exists():
        return {"ok": False, "message": "файл отсутствует", "size": 0}
    size = path.stat().st_size
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return {"ok": True, "message": "читается", "size": size}
    except Exception as error:
        return {"ok": False, "message": f"ошибка: {error}", "size": size}


def build_healthcheck_text() -> str:
    archives = list_backup_archives()
    latest = archives[0] if archives else None
    latest_text = (
        f"<code>{html_escape(latest.name)}</code> — {format_file_size(latest.stat().st_size)}"
        if latest else "—"
    )
    lines = ["🩺 <b>Проверка системы</b>", ""]
    has_warnings = False
    total_size = 0
    for path, display_name in RUNTIME_JSON_FILES:
        status = read_runtime_json_status(path)
        total_size += status["size"]
        icon = "✅" if status["ok"] else "⚠️"
        has_warnings = has_warnings or not status["ok"]
        lines.append(f"{icon} <code>{html_escape(display_name)}</code>: {html_escape(status['message'])}")
    lines.extend([
        "",
        f"💾 Последний бэкап: {latest_text}",
        f"📦 Количество бэкапов: <b>{len(archives)}</b>",
        f"📁 Размер runtime-файлов: <b>{format_file_size(total_size)}</b>",
        "",
        "Статус: " + ("⚠️ есть предупреждения" if has_warnings else "✅ всё хорошо"),
    ])
    return "\n".join(lines)


def healthcheck_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel")]])


def payment_methods_admin_text() -> str:
    methods = load_payment_methods()
    lines = ["💳 <b>Платёжные способы</b>", ""]
    for key, method in methods.items():
        status = "включён" if method.get("enabled") else "выключен"
        lines.extend([
            f"{html_escape(method.get('title', key))}",
            f"Статус: <b>{status}</b>",
            f"Тип: <code>{html_escape(method.get('type', '—'))}</code>",
            f"Публичное название: <b>{html_escape(method.get('client_title', '—'))}</b>",
            "",
        ])
    lines.append("Выберите способ, чтобы изменить настройки.")
    return "\n".join(lines)


def payment_methods_admin_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(str(method.get("title") or key), callback_data=f"payment_method:{key}")]
        for key, method in load_payment_methods().items()
    ]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


def usd_rub_diagnostics_text(settings: dict) -> str:
    diagnostics = settings.get("rate_diagnostics")
    if not isinstance(diagnostics, list) or not diagnostics:
        return ""
    lines = ["", "Источники:"]
    for item in diagnostics:
        if not isinstance(item, dict):
            continue
        source = html_escape(str(item.get("source") or "—"))
        rate = normalize_rate(item.get("rate"))
        if item.get("status") == "accepted" and rate is not None:
            lines.append(f"✅ {source}: {rate:.4f} ₽")
        else:
            reason = html_escape(str(item.get("reason") or "отклонён"))
            raw_value = item.get("raw_rate")
            try:
                raw_rate = float(raw_value)
            except (TypeError, ValueError):
                raw_rate = None
            raw_text = f", значение {raw_rate:.4f} ₽" if raw_rate is not None else ""
            lines.append(f"❌ {source}: {reason}{raw_text}")
    return "\n".join(lines) + "\n"


def usd_rub_admin_text() -> str:
    settings = get_usd_rub_settings()
    markup = get_configured_usd_rub_markup_percent()
    manual_rate = get_manual_usd_rub_rate()
    checked_at = settings.get("rate_checked_at") or "ещё не проверялся"
    market_rate = normalize_rate(settings.get("market_usd_rub_rate"))
    final_rate = normalize_rate(settings.get("final_usd_rub_rate"))
    source = settings.get("rate_source") or "—"
    diagnostics_text = usd_rub_diagnostics_text(settings)
    method_warning = ""
    if str(source).startswith("один источник"):
        method_warning = "⚠️ Внимание: курс рассчитан только по одному источнику.\n"
    elif source == "fallback":
        method_warning = (
            "⚠️ Используется fallback-курс.\n"
            "Причина: все источники недоступны или вернули невалидный курс.\n"
        )
    active_rate = manual_rate or market_rate or USD_RUB_FALLBACK_RATE
    calculated_final = active_rate * (1 + markup / 100)
    market_rate_text = f"{market_rate:.4f} ₽" if market_rate else "—"
    manual_rate_text = f"{manual_rate:.4f} ₽" if manual_rate else "не задан"
    return (
        "💱 <b>Курс USD/RUB</b>\n\n"
        f"Последняя проверка: <b>{html_escape(str(checked_at))}</b>\n"
        f"Источник: <b>{html_escape(str(source))}</b>\n"
        f"Рыночный курс: <b>{market_rate_text}</b>\n"
        f"Ручной курс: <b>{manual_rate_text}</b>\n"
        f"{method_warning}"
        f"{diagnostics_text}"
        f"Наценка: <b>{markup:g}%</b>\n"
        f"Итоговый курс: <b>{(final_rate or calculated_final):.4f} ₽</b>\n\n"
        "Итоговый курс используется для расчёта оплаты картой."
    )


def usd_rub_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Проверить текущий курс", callback_data="usd_rub_check")],
        [InlineKeyboardButton("✏️ Ручной курс", callback_data="usd_rub_set_manual")],
        [InlineKeyboardButton("♻️ Сбросить ручной курс", callback_data="usd_rub_reset_manual")],
        [InlineKeyboardButton("📈 Настроить наценку", callback_data="usd_rub_set_markup")],
        [InlineKeyboardButton("♻️ Сбросить наценку", callback_data="usd_rub_reset_markup")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel")],
    ])


def credentials_summary(credentials: dict) -> str:
    if not credentials:
        return "—"
    lines = []
    for key, value in credentials.items():
        display_value = "заполнено" if str(value or "").strip() else "пусто"
        lines.append(f"• <code>{html_escape(key)}</code>: <b>{display_value}</b>")
    return "\n".join(lines)


def payment_method_admin_text(method_key: str) -> str:
    method = get_payment_method(method_key)
    if not method:
        return "Способ оплаты не найден."
    status = "включён" if method.get("enabled") else "выключен"
    instructions = method.get("instructions") if isinstance(method.get("instructions"), list) else []
    instruction_preview = "Есть инструкция" if instructions else "Инструкция не задана"
    return (
        f"{html_escape(method.get('title', method_key))}\n\n"
        f"Статус: <b>{status}</b>\n"
        f"Тип: <code>{html_escape(method.get('type', '—'))}</code>\n"
        f"Описание: {html_escape(method.get('description', '—'))}\n"
        f"Инструкция подключения: <b>{instruction_preview}</b>\n"
        f"Публичное название для клиента: <b>{html_escape(method.get('client_title', '—'))}</b>\n\n"
        "<b>Технические поля/API данные:</b>\n"
        f"{credentials_summary(method.get('credentials') if isinstance(method.get('credentials'), dict) else {})}"
    )


def payment_method_admin_keyboard(method_key: str) -> InlineKeyboardMarkup:
    method = get_payment_method(method_key) or {}
    toggle_text = "🔴 Выключить" if method.get("enabled") else "🟢 Включить"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_text, callback_data=f"payment_toggle:{method_key}")],
        [InlineKeyboardButton("📖 Инструкция подключения", callback_data=f"payment_instructions:{method_key}")],
        [InlineKeyboardButton("✏️ Публичное название", callback_data=f"payment_edit_title:{method_key}")],
        [InlineKeyboardButton("🔐 API данные / реквизиты", callback_data=f"payment_edit_credentials:{method_key}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_payments")],
    ])


def payment_method_instructions_text(method_key: str) -> str:
    method = get_payment_method(method_key)
    if not method:
        return "Способ оплаты не найден."
    instructions = method.get("instructions") if isinstance(method.get("instructions"), list) else []
    if method_key == "freekassa":
        header = "🔗 <b>FreeKassa (Физ.лицо)</b>"
    else:
        header = f"{html_escape(method.get('title', method_key))}"
    if not instructions:
        return f"{header}\n\nИнструкция подключения пока не задана."
    steps = "\n".join(f"{index}. {html_escape(step)}" for index, step in enumerate(instructions, start=1))
    return f"{header}\n\n{steps}"


def parse_credentials_input(text: str, method_key: str) -> dict:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    parsed = {}
    for line in lines:
        if "=" in line:
            key, value = line.split("=", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            default_key = "card_details" if method_key == "card" else "api_key"
            key, value = default_key, line
        key = key.strip().lower().replace(" ", "_")
        parsed[key] = value.strip()
    return parsed


def format_restore_result(restore_info: dict) -> str:
    restored = restore_info.get("restored") or []
    warnings = restore_info.get("warnings") or []
    restored_text = "\n".join(f"• {name}" for name in restored) or "• —"
    text = (
        "✅ <b>Бэкап восстановлен</b>\n\n"
        f"Файл: <code>{html_escape(restore_info['path'].name)}</code>\n\n"
        "Восстановлено:\n"
        f"{restored_text}"
    )
    if warnings:
        warnings_text = "\n".join(f"• {html_escape(warning)}" for warning in warnings)
        text += f"\n\nПредупреждения:\n{warnings_text}"
    return text


# ─── Клавиатуры ───────────────────────────────────────────────────────────────

def get_tma_url() -> str | None:
    tma_url = os.environ.get("TMA_URL", "").strip()
    return tma_url or None


def main_menu_keyboard(user=None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🌍 Купить eSIM",              callback_data="buy_esim")],
        [InlineKeyboardButton("🍎 Пополнить Apple ID",       callback_data="buy_apple_id")],
        [InlineKeyboardButton("👤 Личный кабинет",           callback_data="profile")],
        [InlineKeyboardButton("👨‍💻 Поддержка",              url=SUPPORT_URL)],
    ]
    tma_url = get_tma_url()
    if tma_url:
        rows.append([InlineKeyboardButton("🚀 Открыть приложение", web_app=WebAppInfo(url=tma_url))])
    if has_admin_access(user):
        rows.append([InlineKeyboardButton("🛠 Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


def admin_panel_keyboard(user=None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📊 Бизнес-разделы", callback_data="admin_business_sections")],
        [InlineKeyboardButton("💳 Оплата и курс", callback_data="admin_payment_sections")],
        [InlineKeyboardButton("🛠 Сервис", callback_data="admin_service_sections")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(rows)


def admin_business_sections_keyboard(user=None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📋 Заказы", callback_data="admin_orders")],
        [InlineKeyboardButton("📊 Аналитика", callback_data="admin_analytics")],
        [InlineKeyboardButton("👥 Клиенты", callback_data="admin_clients")],
    ]
    if has_broadcast_access(user):
        rows.append([InlineKeyboardButton("📰 Новости", callback_data="admin_news")])
    rows.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


def admin_payment_sections_keyboard(user=None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Платёжные способы", callback_data="admin_payments")],
        [InlineKeyboardButton("💱 Курс USD/RUB", callback_data="admin_usd_rub")],
        [InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")],
    ])


def admin_service_sections_keyboard(user=None) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("🔔 Чаты уведомлений", callback_data="admin_notification_chats")]]
    if has_backup_access(user):
        rows.append([InlineKeyboardButton("🩺 Проверка системы", callback_data="admin_healthcheck")])
        rows.append([InlineKeyboardButton("💾 Бэкапы", callback_data="admin_backups")])
    if has_owner_access(user):
        rows.append([InlineKeyboardButton("👤 Администраторы", callback_data="admin_admins")])
    rows.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)



def notification_chat_line(kind: str) -> str:
    title, env_name, _test_label = NOTIFICATION_CHAT_META[kind]
    chat_id, source = get_notification_chat_source(kind)
    cfg = load_config()
    chats = cfg.get("notification_chats") if isinstance(cfg.get("notification_chats"), dict) else {}
    configured = str(chats.get(kind) or "").strip()
    env_value = str(os.environ.get(env_name, "") or "").strip()
    if source == "config":
        source_text = "config.json"
    elif source == "env":
        source_text = env_name
    else:
        source_text = "используется ADMIN_CHAT_ID"
    value = f"<code>{chat_id}</code>" if chat_id is not None else "<b>не настроен</b>"
    details = []
    if configured:
        details.append(f"config: <code>{html_escape(configured)}</code>")
    if env_value:
        details.append(f"env: <code>{html_escape(env_value)}</code>")
    if not details:
        details.append("config/env пустые")
    return f"• <b>{html_escape(title)}</b>: {value} — {html_escape(source_text)} ({'; '.join(details)})"


def notification_chats_admin_text() -> str:
    lines = [notification_chat_line(kind) for kind in NOTIFICATION_CHAT_META]
    return "⚙️ <b>Уведомления / Чаты</b>\n\n" + "\n".join(lines) + "\n\nЕсли отдельный чат не задан, используется ADMIN_CHAT_ID."


def notification_chats_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(title, callback_data=f"notification_chat:{kind}")] for kind, (title, _env, _label) in NOTIFICATION_CHAT_META.items()]
    rows.append([InlineKeyboardButton("📘 Инструкция", callback_data="notification_chats_help")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


def notification_chats_help_text() -> str:
    return (
        "📘 <b>Как подключить чаты уведомлений</b>\n\n"
        "1. Создайте отдельные Telegram-группы:\n"
        "   • SLIK Заказы\n"
        "   • SLIK Действия клиентов\n"
        "   • SLIK Новые клиенты\n"
        "   • SLIK Оплаты\n"
        "   • SLIK Техника\n\n"
        "2. Добавьте бота SLIK Mobile в нужную группу.\n\n"
        "3. В этой группе напишите:\n"
        "   <code>/chatid</code>\n\n"
        "4. Бот пришлёт:\n"
        "   <code>Chat ID: -1001234567890</code>\n\n"
        "5. Скопируйте этот ID.\n\n"
        "6. Вернитесь в бота:\n"
        "   Админ-панель → 🔔 Чаты уведомлений\n\n"
        "7. Выберите нужный тип:\n"
        "   • Заказы\n"
        "   • Действия клиентов\n"
        "   • Новые клиенты\n"
        "   • Оплаты\n"
        "   • Техника\n\n"
        "8. Нажмите “✏️ Изменить” и вставьте chat_id.\n\n"
        "9. Нажмите “🧪 Тест”. Если сообщение пришло в группу — чат подключён.\n\n"
        "10. Если тест не пришёл:\n"
        "   • проверьте, что бот добавлен в группу;\n"
        "   • проверьте, что chat_id скопирован полностью;\n"
        "   • проверьте, что chat_id начинается с минуса;\n"
        "   • повторите /chatid в нужной группе.\n\n"
        "<b>Важно:</b> если отдельный чат не указан, уведомления идут в основной ADMIN_CHAT_ID."
    )


def notification_chats_help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔔 К настройкам чатов", callback_data="admin_notification_chats")],
        [InlineKeyboardButton("⬅️ Админ-панель", callback_data="admin_panel")],
    ])


def notification_chat_detail_text(kind: str) -> str:
    title = NOTIFICATION_CHAT_META[kind][0]
    return f"⚙️ <b>{html_escape(title)}</b>\n\n" + notification_chat_line(kind)


def notification_routes_text() -> str:
    lines = []
    for kind in ("orders", "client_activity", "new_clients", "payments", "tech_alerts"):
        title, _env, _label = NOTIFICATION_CHAT_META[kind]
        chat_id, source = get_notification_chat_source(kind)
        chat_text = str(chat_id) if chat_id is not None else "не задан"
        lines.append(f"• <b>{html_escape(title)}</b>: <code>{html_escape(chat_text)}</code> — {html_escape(source)}")
    cfg = load_config()
    chats = cfg.get("notification_chats") if isinstance(cfg.get("notification_chats"), dict) else {}
    return (
        "🔔 <b>Реальные маршруты уведомлений</b>\n\n"
        + "\n".join(lines)
        + f"\n\nconfig.json: <code>{html_escape(str(CONFIG_FILE))}</code>"
        + f"\nnotification_chats: <code>{html_escape(json.dumps(chats, ensure_ascii=False))}</code>"
    )


def notification_chat_detail_keyboard(kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Изменить", callback_data=f"notification_chat_edit:{kind}")],
        [InlineKeyboardButton("🧪 Тест", callback_data=f"notification_chat_test:{kind}")],
        [InlineKeyboardButton("🧹 Очистить", callback_data=f"notification_chat_clear:{kind}")],
        [InlineKeyboardButton("📘 Инструкция", callback_data="notification_chats_help")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_notification_chats")],
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


def apple_id_start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇺🇸 Apple ID USA", callback_data="apple_id_region:US")],
        [InlineKeyboardButton("🇹🇷 Apple ID Turkey", callback_data="apple_id_region:TR")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
    ])


def apple_id_products_keyboard(region: str) -> InlineKeyboardMarkup:
    rows = []
    for product in APPLE_ID_PRODUCTS.get(region, []):
        amount = f"${product['amount']}" if product["currency"] == "USD" else f"{product['amount']}₺"
        rows.append([InlineKeyboardButton(amount, callback_data=f"apple_id_product:{product['id']}")])
    rows.append([InlineKeyboardButton("◀️ Назад", callback_data="buy_apple_id")])
    return InlineKeyboardMarkup(rows)


def apple_id_product_keyboard(product: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Купить", callback_data=f"buy_apple_id_product:{product['id']}")],
        [InlineKeyboardButton("◀️ Назад", callback_data=f"apple_id_region:{product['region']}")],
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
    rows = [
        [InlineKeyboardButton(str(method.get("client_title") or method.get("title")), callback_data=f"pay_{key}")]
        for key, method in enabled_payment_methods().items()
    ]
    if not rows:
        rows.append([InlineKeyboardButton("💳 Банковская карта", callback_data="pay_card")])
    rows.append([
        InlineKeyboardButton("⬅️ Назад",       callback_data=f"back_to_plan_{plan_key}"),
        InlineKeyboardButton("🏠 Главное меню", callback_data="back_main"),
    ])
    return InlineKeyboardMarkup(rows)


def abandoned_checkout_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Продолжить оплату", callback_data=f"abandoned_continue:{order_id}")],
        [InlineKeyboardButton("🌍 Выбрать другую eSIM", callback_data="buy_esim")],
        [InlineKeyboardButton("👨‍💻 Поддержка", url=SUPPORT_URL)],
    ])


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отменить заявку", callback_data="cancel_order")],
    ])


def admin_order_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ В работу", callback_data=f"order_status:in_progress:{order_id}")],
        [InlineKeyboardButton("📤 Выдано", callback_data=f"order_status:issued:{order_id}")],
        [InlineKeyboardButton("❌ Отменить", callback_data=f"order_status:cancelled:{order_id}")],
    ])


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


def user_orders_keyboard(orders: list) -> InlineKeyboardMarkup:
    latest_orders = sorted(orders, key=order_sort_key, reverse=True)[:10]
    rows = [
        [InlineKeyboardButton(format_order_button_text(order), callback_data=f"user_order:{order.get('id')}")]
        for order in latest_orders
        if order.get("id") is not None
    ]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="profile")])
    return InlineKeyboardMarkup(rows)


def user_order_card_keyboard(order_id: int) -> InlineKeyboardMarkup:
    order = find_order(order_id)
    if order and order.get("product_type") == "apple_id":
        return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="profile_orders")]])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 Повторить заказ", callback_data=f"repeat_order:{order_id}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="profile_orders")],
    ])


def unavailable_plan_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🌍 Выбрать eSIM", callback_data="buy_esim")]])


# ─── Главное меню ─────────────────────────────────────────────────────────────

MAIN_MENU_TEXT = (
    "📶 <b>SLIK Mobile</b>\n\n"
    "Интернет через eSIM за 2 минуты.\n\n"
    "Выберите действие:"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    is_new_client = False
    referrer_id = None
    if user:
        users_before_start = load_users()
        is_new_client = str(user.id) not in users_before_start
        referrer_id = extract_referrer_id(context)
        ensure_user_profile(user)
        register_start_referral(user, referrer_id)
    if update.message:
        try:
            await update.message.reply_text("...", reply_markup=ReplyKeyboardRemove())
        except Exception:
            pass

        try:
            await send_screen(
                update.message, "start", MAIN_MENU_TEXT,
                main_menu_keyboard(user), local_file=BANNER_IMAGE,
            )
        except Exception:
            await update.message.reply_text(
                MAIN_MENU_TEXT,
                reply_markup=main_menu_keyboard(user),
                parse_mode="HTML",
            )
        if user and not has_admin_access(user):
            if is_new_client:
                await notify_new_client(context, user, referrer_id)
            else:
                await track_action(context, user, "открыл бот")
    elif update.callback_query:
        await edit_or_send(update.callback_query, context, MAIN_MENU_TEXT, main_menu_keyboard(user))


# ─── Навигационные экраны ─────────────────────────────────────────────────────

async def show_buy_esim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    await edit_or_send(query, context, "🌍 <b>Выберите страну:</b>", buy_esim_keyboard())
    if not has_admin_access(user):
        await track_action(context, user, "нажал «Купить eSIM»")


async def show_apple_id_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    text = (
        "🍎 <b>Пополнение Apple ID</b>\n\n"
        "Выберите регион вашего Apple ID:\n\n"
        "🇺🇸 USA — подарочные карты Apple Gift Card в долларах\n"
        "🇹🇷 Turkey — подарочные карты Apple Gift Card в лирах\n\n"
        "Важно:\n"
        "Код подходит только для выбранного региона Apple ID. Перед покупкой убедитесь, что регион аккаунта совпадает."
    )
    await edit_or_send(query, context, text, apple_id_start_keyboard())
    if not has_admin_access(query.from_user):
        await track_action(context, query.from_user, "нажал «Пополнить Apple ID»")


async def show_apple_id_region(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    region = query.data.split(":", 1)[1]
    if region not in APPLE_ID_PRODUCTS:
        await query.answer("Регион не найден.", show_alert=True)
        return
    flag = APPLE_ID_REGION_FLAGS.get(region, "")
    title = APPLE_ID_REGION_TITLES.get(region, region)
    text = f"{flag} <b>Apple ID {html_escape(title)}</b>\n\nВыберите номинал:"
    await edit_or_send(query, context, text, apple_id_products_keyboard(region))


async def show_apple_id_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    product_id = query.data.split(":", 1)[1]
    product = apple_id_product_by_id(product_id)
    if not product:
        await query.answer("Товар не найден.", show_alert=True)
        return
    region = product["region"]
    region_title = APPLE_ID_REGION_TITLES.get(region, region)
    flag = APPLE_ID_REGION_FLAGS.get(region, "")
    nominal = f"${product['amount']}" if product["currency"] == "USD" else f"{product['amount']}₺"
    text = (
        f"🍎 <b>{html_escape(product['title'])}</b>\n\n"
        f"Регион: {flag} {html_escape(region_title)}\n"
        f"Номинал: <b>{html_escape(nominal)}</b>\n"
        f"Стоимость: <b>{html_escape(format_usd(product['price_usd']))}</b>\n\n"
        f"Важно:\nКод можно активировать только на Apple ID региона {html_escape(region_title)}.\n\n"
        "После оплаты менеджер проверит заказ и отправит код."
    )
    await edit_or_send(query, context, text, apple_id_product_keyboard(product))


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
    if not has_admin_access(user):
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
    if not has_admin_access(query.from_user):
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
    if not has_admin_access(query.from_user):
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
    if not has_admin_access(query.from_user):
        await track_action(context, query.from_user, "нажал «Поддержка»")


async def show_existing_checkout_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split(":", 1)[1])
    order = find_order(order_id)
    if (
        not order
        or str(order.get("user_id")) != str(query.from_user.id)
        or normalize_order_status(order.get("status")) != "waiting_payment"
    ):
        await edit_or_send(
            query, context,
            "Этот заказ уже оплачен, отменён или устарел. Выберите eSIM заново.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🌍 Выбрать eSIM", callback_data="buy_esim")]]),
        )
        return ConversationHandler.END

    plan_key = str(order.get("plan_key") or "")
    plan = PLAN_MAP.get(plan_key, {"gb": order.get("gb", "—"), "days": order.get("days", "—"), "price": order.get("price", "0")})
    context.user_data["checkout_order_id"] = order_id
    context.user_data["plan_key"] = plan_key
    context.user_data["plan"] = plan
    provider = order.get("payment_provider") or "card"
    context.user_data["payment_provider"] = provider
    context.user_data["payment_method"] = order.get("payment_method") or payment_provider_label(provider)

    if provider == "cryptobot" and order.get("cryptobot_invoice_id"):
        rows = []
        if order.get("cryptobot_pay_url"):
            rows.append([InlineKeyboardButton("🤖 Оплатить в CryptoBot", url=order["cryptobot_pay_url"])])
        rows.extend([
            [InlineKeyboardButton("🔄 Проверить оплату", callback_data=f"check_payment_{order['cryptobot_invoice_id']}")],
            [InlineKeyboardButton("❌ Отменить заявку", callback_data="cancel_order")],
        ])
        await edit_or_send(
            query, context,
            "🤖 <b>Оплата через CryptoBot</b>\n\n"
            f"Сумма: <b>{html_escape(plan.get('price', '—'))}</b>\n"
            "Откройте уже созданный счёт, оплатите его и нажмите «Проверить оплату».",
            InlineKeyboardMarkup(rows),
        )
        return WAITING_PAYMENT

    cfg = load_config()
    lock = await create_card_payment_lock(plan)
    context.user_data["card_payment_lock"] = lock
    update_checkout_order(order_id, payment_method=payment_provider_label("card"), payment_provider="card", payment_details=order_payment_details_from_context(context))
    await edit_or_send(query, context, build_card_payment_text(plan, cfg["payment"].get("card", ""), lock), card_payment_keyboard())
    return WAITING_PAYMENT


def mark_abandoned_reminder_sent_if_still_waiting(order_id: int) -> bool:
    fresh_orders = load_orders()
    for fresh_order in fresh_orders:
        try:
            is_same_order = int(fresh_order.get("id")) == int(order_id)
        except (TypeError, ValueError):
            is_same_order = False
        if not is_same_order:
            continue
        if normalize_order_status(fresh_order.get("status")) != "waiting_payment" or fresh_order.get("abandoned_reminder_sent"):
            return False
        fresh_order["abandoned_reminder_sent"] = True
        fresh_order["abandoned_reminder_sent_at"] = now_str()
        save_orders(fresh_orders)
        return True
    return False


async def abandoned_checkout_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.datetime.now(tz=TZ)
    candidate_orders = load_orders()
    for order in candidate_orders:
        if normalize_order_status(order.get("status")) != "waiting_payment" or order.get("abandoned_reminder_sent"):
            continue
        order_id = order.get("id")
        if order_id is None:
            continue
        created_at = order.get("checkout_created_at")
        try:
            created_dt = datetime.datetime.fromisoformat(str(created_at)).astimezone(TZ)
        except (TypeError, ValueError):
            continue
        age = now - created_dt
        if age < datetime.timedelta(minutes=ABANDONED_CHECKOUT_REMINDER_MINUTES) or age > datetime.timedelta(hours=ABANDONED_CHECKOUT_MAX_AGE_HOURS):
            continue
        user_id = order.get("user_id")
        if not user_id:
            continue
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "Вы начали оформление eSIM, но не завершили оплату.\n\n"
                    "Заказ ещё можно оплатить.\n"
                    "Если поездка актуальна — продолжите оформление."
                ),
                reply_markup=abandoned_checkout_keyboard(order["id"]),
            )
        except Exception as e:
            logger.error("Не удалось отправить abandoned checkout reminder для заказа %s: %s", order.get("number"), e)
            continue

        if mark_abandoned_reminder_sent_if_still_waiting(order_id):
            logger.info("Abandoned checkout reminder sent for order %s", order.get("number"))
        else:
            logger.info(
                "Abandoned checkout reminder was sent but order %s changed before flag update; leaving order unchanged",
                order.get("number"),
            )


def expiry_reminder_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 Повторить заказ", callback_data=f"repeat_order:{order_id}")],
        [InlineKeyboardButton("🌍 Выбрать другую eSIM", callback_data="buy_esim")],
        [InlineKeyboardButton("👨‍💻 Поддержка", url=SUPPORT_URL)],
    ])


def mark_expiry_reminder_sent_if_still_issued(order_id: int) -> bool:
    fresh_orders = load_orders()
    for fresh_order in fresh_orders:
        try:
            is_same_order = int(fresh_order.get("id")) == int(order_id)
        except (TypeError, ValueError):
            is_same_order = False
        if not is_same_order:
            continue
        if normalize_order_status(fresh_order.get("status")) != "issued" or fresh_order.get("expiry_reminder_sent"):
            return False
        fresh_order["expiry_reminder_sent"] = True
        fresh_order["expiry_reminder_sent_at"] = now_str()
        save_orders(fresh_orders)
        return True
    return False


async def esim_expiry_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.datetime.now(tz=TZ)
    candidate_orders = load_orders()
    for order in candidate_orders:
        if normalize_order_status(order.get("status")) != "issued" or order.get("expiry_reminder_sent"):
            continue
        order_id = order.get("id")
        if order_id is None:
            continue
        issued_at = parse_now_str(order.get("issued_at"))
        days = parse_order_days(order.get("days"))
        if not issued_at or days is None:
            continue
        age = now - issued_at
        if age < datetime.timedelta(0) or age > datetime.timedelta(days=ESIM_EXPIRY_REMINDER_MAX_AGE_DAYS):
            continue
        expiry_at = issued_at + datetime.timedelta(days=days)
        reminder_at = expiry_at - datetime.timedelta(days=ESIM_EXPIRY_REMINDER_DAYS_BEFORE)
        if now < reminder_at or now > expiry_at:
            continue
        user_id = order.get("user_id")
        if not user_id:
            continue
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "Ваша eSIM скоро закончится.\n\n"
                    "Если интернет всё ещё нужен — можно быстро купить такой же пакет ещё раз."
                ),
                reply_markup=expiry_reminder_keyboard(int(order_id)),
            )
        except Exception as e:
            logger.error("Не удалось отправить eSIM expiry reminder для заказа %s: %s", order.get("number"), e)
            continue

        if mark_expiry_reminder_sent_if_still_issued(order_id):
            logger.info("eSIM expiry reminder sent for order %s", order.get("number"))
        else:
            logger.info(
                "eSIM expiry reminder was sent but order %s changed before flag update; leaving order unchanged",
                order.get("number"),
            )


def schedule_esim_expiry_reminders(app: Application) -> None:
    if not app.job_queue:
        logger.warning("JobQueue недоступен; eSIM expiry reminders не запущены")
        return
    app.job_queue.run_repeating(
        esim_expiry_reminder_job,
        interval=ESIM_EXPIRY_REMINDER_INTERVAL_SECONDS,
        first=ESIM_EXPIRY_REMINDER_INTERVAL_SECONDS,
        name="esim_expiry_reminders",
    )


def schedule_abandoned_checkout_reminders(app: Application) -> None:
    if not app.job_queue:
        logger.warning("JobQueue недоступен; abandoned checkout reminders не запущены")
        return
    app.job_queue.run_repeating(abandoned_checkout_reminder_job, interval=60, first=60, name="abandoned_checkout_reminders")


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
            if is_revenue_order(order)
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
        if order.get("product_type") == "apple_id":
            lines.extend([
                f"🧾 Заказ: <b>{html_escape(str(order.get('number') or order.get('id') or '—'))}</b>",
                f"🍎 Товар: <b>{html_escape(order.get('product_title', order.get('gb', '—')))}</b>",
                f"💵 Сумма: <b>{html_escape(order.get('price', '—'))}</b>",
                f"📅 Дата: <b>{html_escape(format_order_date(order))}</b>",
                f"🔖 Статус: <b>{html_escape(order_status_label(order.get('status', 'new')))}</b>",
                "",
                "Откройте заказ кнопкой ниже, чтобы посмотреть детали.",
            ])
            continue
        lines.extend([
            f"🧾 Заказ: <b>{html_escape(str(order.get('number') or order.get('id') or '—'))}</b>",
            f"🌍 Страна: <b>{html_escape(order.get('country', 'Россия'))}</b>",
            f"📦 Тариф: <b>{html_escape(order.get('gb', '—'))}</b>",
            f"💵 Сумма: <b>{html_escape(order.get('price', '—'))}</b>",
            f"📅 Дата: <b>{html_escape(format_order_date(order))}</b>",
            f"🔖 Статус: <b>{html_escape(order_status_label(order.get('status', 'new')))}</b>",
            "",
            "Откройте заказ кнопкой ниже, чтобы повторить покупку.",
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

    await edit_or_send(query, context, format_user_orders(orders), user_orders_keyboard(orders))


def build_user_order_card_text(order: dict) -> str:
    if order.get("product_type") == "apple_id":
        amount = order.get("amount", "—")
        currency = order.get("currency", "")
        nominal = f"${amount}" if currency == "USD" else f"{amount}₺" if currency == "TRY" else f"{amount} {currency}".strip()
        region = APPLE_ID_REGION_TITLES.get(order.get("region"), order.get("region", "—"))
        return (
            "🍎 <b>Заказ Apple ID</b>\n\n"
            f"🧾 Номер: <b>{html_escape(str(order.get('number') or order.get('id') or '—'))}</b>\n"
            f"Товар: <b>{html_escape(order.get('product_title', order.get('gb', '—')))}</b>\n"
            f"Регион: <b>{html_escape(region)}</b>\n"
            f"Номинал: <b>{html_escape(nominal)}</b>\n"
            f"💵 Сумма: <b>{html_escape(order.get('price', '—'))}</b>\n"
            f"🔖 Статус: <b>{html_escape(order_status_label(order.get('status', 'new')))}</b>\n"
            f"📅 Дата: <b>{html_escape(format_order_date(order))}</b>\n\n"
            "После подтверждения оплаты менеджер отправит код вручную."
        )
    return (
        "📦 <b>Заказ</b>\n\n"
        f"🧾 Номер: <b>{html_escape(str(order.get('number') or order.get('id') or '—'))}</b>\n"
        f"🌍 Страна: <b>{html_escape(order.get('country', 'Россия'))}</b>\n"
        f"📦 Тариф: <b>{html_escape(order.get('gb', '—'))}</b>\n"
        f"📅 Срок: <b>{html_escape(order.get('days', '—'))}</b>\n"
        f"💵 Сумма: <b>{html_escape(order.get('price', '—'))}</b>\n"
        f"🔖 Статус: <b>{html_escape(order_status_label(order.get('status', 'new')))}</b>\n"
        f"📅 Дата: <b>{html_escape(format_order_date(order))}</b>\n\n"
        "Нажмите «Повторить заказ», чтобы создать новый checkout на такой же тариф. Старый заказ не изменится."
    )


async def show_user_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    order_id = int(query.data.split(":", 1)[1])
    order = find_order(order_id)
    if not order or str(order.get("user_id")) != str(query.from_user.id):
        await query.answer("Заказ не найден.", show_alert=True)
        return
    await query.answer()
    await edit_or_send(query, context, build_user_order_card_text(order), user_order_card_keyboard(order_id))


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
    referral_stats = referral_analytics_for_profile(profile)
    username = await get_bot_username(context)
    referral_link = f"https://t.me/{username}?start=ref_{query.from_user.id}" if username else f"/start ref_{query.from_user.id}"
    text = (
        "👥 <b>Пригласить друга</b>\n\n"
        f"Ваш статус: <b>{html_escape(format_status(status))}</b>\n\n"
        "За первую заявку друга:\n"
        f"Вы получите: <b>{format_usd(referral_reward)}</b>\n"
        f"Друг получит: <b>{format_usd(FRIEND_REFERRAL_REWARD_USD)}</b>\n\n"
        "Ваша статистика:\n"
        f"Переходов: <b>{referral_stats['clicks']}</b>\n"
        f"Купили: <b>{referral_stats['bought']}</b>\n"
        f"Не купили: <b>{referral_stats['not_bought']}</b>\n"
        f"Бонусов начислено: <b>{format_usd_cents(referral_stats['bonuses_awarded'])}</b>\n\n"
        f"Ваша ссылка:\n<code>{html_escape(referral_link)}</code>"
    )
    await edit_or_send(query, context, text, profile_back_keyboard())


async def show_profile_bonuses(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    profile = sync_user_order_stats(query.from_user, ensure_user_profile(query.from_user))
    referral_stats = referral_analytics_for_profile(profile)
    status = profile.get("status", "Traveller")
    referral_reward = referral_reward_for_profile(profile)
    text = (
        "💰 <b>SLIK Balance</b>\n\n"
        f"Баланс: <b>{format_usd_cents(profile.get('slik_balance', profile.get('bonus_balance', 0)))}</b>\n"
        f"Статус: <b>{html_escape(format_status(status))}</b>\n"
        f"Ваш кэшбэк: <b>{cashback_percent_for_status(status)}%</b>\n"
        f"Ваш бонус за друга: <b>{format_usd(referral_reward)}</b>\n\n"
        "Реферальная аналитика:\n"
        f"Переходов: <b>{referral_stats['clicks']}</b>\n"
        f"Купили: <b>{referral_stats['bought']}</b>\n"
        f"Не купили: <b>{referral_stats['not_bought']}</b>\n"
        f"Бонусов начислено: <b>{format_usd_cents(referral_stats['bonuses_awarded'])}</b>\n\n"
        f"Друг по вашей ссылке получает: <b>{format_usd(FRIEND_REFERRAL_REWARD_USD)}</b>."
    )
    await edit_or_send(query, context, text, profile_back_keyboard())


# ─── Диалог покупки ───────────────────────────────────────────────────────────

async def start_purchase_for_plan(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_key: str, plan: dict, action_label: str = "нажал «Купить»") -> int:
    query = update.callback_query
    context.user_data["plan_key"] = plan_key
    context.user_data["plan"]     = plan
    order = create_checkout_order(query.from_user, plan_key, plan)
    context.user_data["checkout_order_id"] = order["id"]

    methods = enabled_payment_methods()
    if list(methods.keys()) == ["card"] or not methods:
        cfg = load_config()
        card = cfg["payment"].get("card", "")
        context.user_data["payment_method"] = payment_provider_label("card")
        context.user_data["payment_provider"] = "card"
        lock = await create_card_payment_lock(plan)
        context.user_data["card_payment_lock"] = lock
        update_checkout_order(order["id"], payment_method=payment_provider_label("card"), payment_provider="card", payment_details=order_payment_details_from_context(context))
        await query.message.reply_text(
            build_card_payment_text(plan, card, lock),
            parse_mode="HTML",
            reply_markup=card_payment_keyboard(),
        )
    else:
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
        await track_action(context, query.from_user, action_label,
                           f"Тариф: {plan['gb']} / {plan['days']}\nЦена: {plan['price']}")
    return WAITING_PAYMENT


async def start_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    plan_key = query.data.replace("buy_", "")
    plan = PLAN_MAP.get(plan_key)
    if not plan:
        return ConversationHandler.END
    return await start_purchase_for_plan(update, context, plan_key, plan)


async def start_apple_id_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    product_id = query.data.split(":", 1)[1]
    product = apple_id_product_by_id(product_id)
    if not product:
        await query.answer("Товар не найден.", show_alert=True)
        return ConversationHandler.END
    plan = apple_id_product_plan(product)
    context.user_data["plan_key"] = product_id
    context.user_data["plan"] = plan
    order = create_apple_id_checkout_order(query.from_user, product)
    context.user_data["checkout_order_id"] = order["id"]

    methods = enabled_payment_methods()
    if list(methods.keys()) == ["card"] or not methods:
        cfg = load_config()
        card = cfg["payment"].get("card", "")
        context.user_data["payment_method"] = payment_provider_label("card")
        context.user_data["payment_provider"] = "card"
        lock = await create_card_payment_lock(plan)
        context.user_data["card_payment_lock"] = lock
        update_checkout_order(order["id"], payment_method=payment_provider_label("card"), payment_provider="card", payment_details=order_payment_details_from_context(context))
        await query.message.reply_text(build_card_payment_text(plan, card, lock), parse_mode="HTML", reply_markup=card_payment_keyboard())
    else:
        await query.message.reply_text(
            "💳 <b>Выберите способ оплаты</b>\n\n"
            f"🍎 Товар: <b>{html_escape(product['title'])}</b>\n"
            f"💵 Цена: <b>{html_escape(plan['price'])}</b>",
            parse_mode="HTML",
            reply_markup=payment_keyboard(product_id),
        )
    if not has_admin_access(query.from_user):
        await track_action(context, query.from_user, "нажал «Купить Apple ID»", f"Товар: {product['title']}\nЦена: {plan['price']}")
    return WAITING_PAYMENT


async def repeat_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    order_id = int(query.data.split(":", 1)[1])
    order = find_order(order_id)
    if not order or str(order.get("user_id")) != str(query.from_user.id):
        await query.answer("Заказ не найден.", show_alert=True)
        return ConversationHandler.END
    plan_key = str(order.get("plan_key") or "")
    plan = PLAN_MAP.get(plan_key)
    if not plan:
        await query.answer()
        await edit_or_send(
            query, context,
            "Этот тариф больше недоступен. Выберите актуальный пакет.",
            unavailable_plan_keyboard(),
        )
        return ConversationHandler.END
    await query.answer()
    return await start_purchase_for_plan(update, context, plan_key, plan, "нажал «Повторить заказ»")


async def choose_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    plan = context.user_data.get("plan", {})
    if not plan and (data in {"pay_card", "pay_cryptobot", "pay_freekassa", "pay_yookassa", "payment_done"} or data.startswith("check_payment_")):
        await query.message.reply_text(
            "Платёжная сессия устарела. Выберите товар заново.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")]]),
        )
        return ConversationHandler.END

    if data in {"pay_freekassa", "pay_yookassa"}:
        provider = data.replace("pay_", "")
        context.user_data["payment_method"] = payment_provider_label(provider)
        context.user_data["payment_provider"] = provider
        await query.message.reply_text(
            "Этот способ оплаты скоро будет доступен. Выберите оплату картой.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Оплатить картой", callback_data="pay_card")],
                [InlineKeyboardButton("❌ Отменить заявку", callback_data="cancel_order")],
            ]),
        )
        return WAITING_PAYMENT

    if data == "pay_cryptobot":
        cfg = load_config()
        token = cfg["payment"].get("cryptobot_token", "").strip()
        if not token:
            await query.message.reply_text(
                "CryptoBot временно недоступен. Выберите оплату картой.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Оплатить картой", callback_data="pay_card")],
                    [InlineKeyboardButton("❌ Отменить заявку", callback_data="cancel_order")],
                ]),
            )
            return WAITING_PAYMENT

        context.user_data["payment_method"] = payment_provider_label("cryptobot")
        context.user_data["payment_provider"] = "cryptobot"
        amount = parse_price(plan.get("price", "0"))
        description = (
            f"SLIK Apple ID {plan.get('product_title', '')}".strip()
            if plan.get("product_type") == "apple_id"
            else f"SLIK eSIM {plan.get('gb', '')} / {plan.get('days', '')}".strip()
        )
        invoice = await crypto_create_invoice(token, amount, description, f"user:{query.from_user.id}:plan:{context.user_data.get('plan_key', '')}")
        if not invoice:
            await query.message.reply_text(
                "Не удалось создать счёт CryptoBot. Выберите оплату картой.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Оплатить картой", callback_data="pay_card")],
                    [InlineKeyboardButton("❌ Отменить заявку", callback_data="cancel_order")],
                ]),
            )
            return WAITING_PAYMENT

        invoice_id = invoice.get("invoice_id")
        pay_url = invoice.get("pay_url") or invoice.get("bot_invoice_url") or invoice.get("mini_app_invoice_url")
        update_checkout_order(
            context.user_data.get("checkout_order_id"),
            payment_method=payment_provider_label("cryptobot"),
            payment_provider="cryptobot",
            cryptobot_invoice_id=invoice_id,
            cryptobot_pay_url=pay_url,
        )
        rows = []
        if pay_url:
            rows.append([InlineKeyboardButton("🤖 Оплатить в CryptoBot", url=pay_url)])
        rows.extend([
            [InlineKeyboardButton("🔄 Проверить оплату", callback_data=f"check_payment_{invoice_id}")],
            [InlineKeyboardButton("❌ Отменить заявку", callback_data="cancel_order")],
        ])
        await query.message.reply_text(
            "🤖 <b>Оплата через CryptoBot</b>\n\n"
            f"Сумма: <b>{html_escape(plan.get('price', '—'))}</b>\n"
            "Откройте счёт, оплатите его и нажмите «Проверить оплату».",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return WAITING_PAYMENT

    if data == "payment_done":
        if context.user_data.get("payment_method") == "Карта" and not is_card_payment_lock_active(
            context.user_data.get("card_payment_lock")
        ):
            cfg = load_config()
            card = cfg["payment"].get("card", "")
            new_lock = await create_card_payment_lock(plan)
            context.user_data["card_payment_lock"] = new_lock
            await query.message.reply_text(
                "⏳ <b>Время действия суммы истекло</b>\n"
                "Курс изменился, поэтому сумма к оплате пересчитана.\n"
                "Новая сумма к оплате:\n"
                f"<b>{format_rub(new_lock.get('rub_amount'))}</b>\n"
                "Переведите новую сумму и нажмите «Я оплатил».",
                parse_mode="HTML",
            )
            await query.message.reply_text(
                build_card_payment_text(plan, card, new_lock),
                parse_mode="HTML",
                reply_markup=card_payment_keyboard(),
            )
            return WAITING_PAYMENT

        await query.message.reply_text(
            "📝 <b>Оформление заявки</b>\n\nКак вас зовут?",
            parse_mode="HTML", reply_markup=cancel_keyboard(),
        )
        return WAITING_NAME

    elif data == "pay_card":
        cfg = load_config()
        card = cfg["payment"].get("card", "")
        context.user_data["payment_method"] = payment_provider_label("card")
        context.user_data["payment_provider"] = "card"
        lock = await create_card_payment_lock(plan)
        context.user_data["card_payment_lock"] = lock
        update_checkout_order(context.user_data.get("checkout_order_id"), payment_method=payment_provider_label("card"), payment_provider="card", payment_details=order_payment_details_from_context(context))
        await query.message.reply_text(
            build_card_payment_text(plan, card, lock),
            parse_mode="HTML",
            reply_markup=card_payment_keyboard(),
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
        product = apple_id_product_by_id(plan_key)
        if product:
            context.user_data.pop("checkout_order_id", None)
            region = product["region"]
            region_title = APPLE_ID_REGION_TITLES.get(region, region)
            flag = APPLE_ID_REGION_FLAGS.get(region, "")
            nominal = f"${product['amount']}" if product["currency"] == "USD" else f"{product['amount']}₺"
            text = (
                f"🍎 <b>{html_escape(product['title'])}</b>\n\n"
                f"Регион: {flag} {html_escape(region_title)}\n"
                f"Номинал: <b>{html_escape(nominal)}</b>\n"
                f"Стоимость: <b>{html_escape(format_usd(product['price_usd']))}</b>\n\n"
                f"Важно:\nКод можно активировать только на Apple ID региона {html_escape(region_title)}.\n\n"
                "После оплаты менеджер проверит заказ и отправит код."
            )
            await edit_or_send(query, context, text, apple_id_product_keyboard(product))
            return ConversationHandler.END
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
    payment_provider = context.user_data.get("payment_provider", "card")
    payment = context.user_data.get("payment_method", payment_provider_label(payment_provider))

    order_payload = {
        "product_type":    plan.get("product_type", "esim"),
        "gb":             plan["gb"],
        "days":           plan["days"],
        "price":          plan["price"],
        "country":        "Россия",
        "plan_key":       context.user_data["plan_key"],
        "payment_method": payment,
        "payment_provider": payment_provider,
        "name":           name,
        "tg_handle":      tg_handle,
        "user_id":        user.id,
    }
    if plan.get("product_type") == "apple_id":
        order_payload.update({
            "product_id": plan.get("product_id"),
            "product_title": plan.get("product_title"),
            "region": plan.get("region"),
            "amount": plan.get("amount"),
            "currency": plan.get("currency"),
            "price_usd": plan.get("price_usd"),
            "country": APPLE_ID_REGION_TITLES.get(plan.get("region"), plan.get("region", "—")),
        })
    payment_details = order_payment_details_from_context(context)
    if payment_details:
        order_payload["payment_details"] = payment_details
    checkout_order_id = context.user_data.get("checkout_order_id")
    if checkout_order_id:
        order = update_checkout_order(checkout_order_id, **order_payload, status="new") or append_order(order_payload)
    else:
        order = append_order(order_payload)
    profile, previous_status, current_status, cashback_amount = record_user_order(user, order)

    if plan.get("product_type") == "apple_id":
        nominal = f"${plan.get('amount')}" if plan.get("currency") == "USD" else f"{plan.get('amount')}₺"
        client_text = (
            "✅ <b>Заявка создана</b>\n\n"
            f"🧾 Номер заказа: <b>{order['number']}</b>\n\n"
            f"Товар: <b>{html_escape(plan.get('product_title', plan['gb']))}</b>\n"
            f"Регион: <b>{html_escape(APPLE_ID_REGION_TITLES.get(plan.get('region'), plan.get('region', '—')))}</b>\n"
            f"Номинал: <b>{html_escape(nominal)}</b>\n"
            f"Сумма: <b>{html_escape(plan['price'])}</b>\n\n"
            "После проверки оплаты менеджер отправит код в этот чат."
        )
    else:
        client_text = (
            "✅ <b>Заявка принята</b>\n\n"
            f"🧾 Номер заказа: <b>{order['number']}</b>\n\n"
            f"📶 Тариф: <b>{plan['gb']} / {plan['days']}</b>\n"
            f"💵 Цена: <b>{plan['price']}</b>\n\n"
            "Спасибо за заявку.\n\n"
            "Менеджер свяжется с вами в течение нескольких минут и отправит вашу eSIM.\n\n"
            "⚡ Среднее время обработки — до 5 минут."
        )
    await update.message.reply_text(
        client_text,
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
    if not has_admin_access(user):
        if plan.get("product_type") == "apple_id":
            details = f"Товар: {plan.get('product_title')}\nЦена: {plan['price']}\nОплата: {payment}"
        else:
            details = f"Тариф: {plan['gb']} / {plan['days']}\nЦена: {plan['price']}\nОплата: {payment}"
        await track_action(context, user, "создал заявку", details)
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_order_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if context.user_data.get("checkout_order_id"):
        update_checkout_order(context.user_data.get("checkout_order_id"), status="cancelled")
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
                "order notification route: orders chat %s (order %s, attempt %s, helper: get_orders_chat_id)",
                admin_id, order_id, attempt,
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
    admin_id = get_orders_chat_id()
    _route_chat_id, source = get_orders_chat_source()
    logger.info("notification route selected: type=orders chat_id=%s source=%s helper=get_orders_chat_id", admin_id, source)
    order_number = order.get("number", "—")
    order_id = order.get("id")
    if not admin_id:
        logger.warning(
            "Админ-уведомление по заказу %s не отправлено: чат заказов и ADMIN_CHAT_ID не заданы",
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
    payment_details = order.get("payment_details") if isinstance(order.get("payment_details"), dict) else {}
    payment_details_line = ""
    if payment_method == "Карта" and payment_details:
        rate_text = f"{float(payment_details.get('usd_rub_rate') or 0):.2f}"
        markup_text = f"{float(payment_details.get('markup_percent') or 0):g}"
        final_rate_text = f"{float(payment_details.get('final_usd_rub_rate') or 0):.4f}"
        rate_checked_at = payment_details.get("rate_checked_at") or "—"
        payment_details_line = (
            f"Источник курса: <b>{html_escape(payment_details.get('rate_source', '—'))}</b>\n"
            f"Курс: <b>{html_escape(rate_text)} ₽</b>\n"
            f"Время проверки курса: <b>{html_escape(rate_checked_at)}</b>\n"
            f"Комиссия: <b>{html_escape(markup_text)}%</b>\n"
            f"Итоговый курс: <b>{html_escape(final_rate_text)} ₽</b>\n"
            f"К оплате: <b>{html_escape(format_rub(payment_details.get('rub_amount')))}</b>\n"
        )
    if order.get("product_type") == "apple_id":
        amount = order.get("amount", "—")
        currency = order.get("currency", "")
        nominal = f"${amount}" if currency == "USD" else f"{amount}₺" if currency == "TRY" else f"{amount} {currency}".strip()
        region = APPLE_ID_REGION_TITLES.get(order.get("region"), order.get("region", "—"))
        text = (
            "🍎 <b>Новый заказ Apple ID</b>\n\n"
            f"Номер заказа: <b>{html_escape(order_number)}</b>\n\n"
            f"Клиент: <b>{html_escape(order.get('tg_handle', '—'))}</b> / ID <code>{html_escape(order.get('user_id', '—'))}</code>\n"
            f"Имя: <b>{html_escape(order.get('name', '—'))}</b>\n"
            f"Регион: <b>{html_escape(region)}</b>\n"
            f"Номинал: <b>{html_escape(nominal)}</b>\n"
            f"Товар: <b>{html_escape(order.get('product_title', order.get('gb', '—')))}</b>\n"
            f"Сумма: <b>{html_escape(order.get('price', '—'))}</b>\n"
            f"{payment_line}"
            f"{payment_details_line}"
            f"Статус: <b>{html_escape(order_status_label(order.get('status', 'new')))}</b>\n\n"
            "После подтверждения оплаты отправьте клиенту код вручную.\n\n"
            f"🕒 {html_escape(order.get('created_at', '—'))}\n"
            f"Маршрут: orders · {html_escape(source)} · <code>{html_escape(str(admin_id))}</code>"
        )
    else:
        text = (
            "🔥 <b>Новый заказ</b>\n\n"
            f"Номер заказа: <b>{html_escape(order_number)}</b>\n\n"
            f"📶 Тариф: <b>{html_escape(order.get('gb', '—'))} / {html_escape(order.get('days', '—'))}</b>\n"
            f"💵 Цена: <b>{html_escape(order.get('price', '—'))}</b>\n"
            f"{payment_line}"
            f"{payment_details_line}\n"
            f"👤 Имя: <b>{html_escape(order.get('name', '—'))}</b>\n"
            f"📨 Telegram: <b>{html_escape(order.get('tg_handle', '—'))}</b>\n\n"
            f"🕒 {html_escape(order.get('created_at', '—'))}\n"
            f"Маршрут: orders · {html_escape(source)} · <code>{html_escape(str(admin_id))}</code>"
        )
    await send_admin_order_message(context, admin_id, text, order_id)


async def handle_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not has_admin_access(query.from_user):
        await deny_admin_access(update)
        return

    data = query.data
    if data.startswith("order_status:"):
        _prefix, status, order_id_raw = data.split(":", 2)
        order_id = int(order_id_raw)
    else:
        action = "issued" if data.startswith("done_") else "cancelled"
        status = action
        order_id = int(data.split("_", 1)[1])

    order = update_order_status(order_id, status, query.from_user.id)
    if not order:
        await query.answer("Заявка не найдена.", show_alert=True)
        return

    await query.answer(f"Статус: {order_status_label(order.get('status'))}")
    await notify_client_order_status(context, order)
    await edit_or_send(query, context, build_order_card_text(order), order_card_keyboard(order_id))


# ─── Вводы Clients CRM ───────────────────────────────────────────────────────

async def handle_client_crm_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg or not msg.text:
        return
    input_mode = context.user_data.get("client_input")
    if not input_mode:
        return
    if not has_admin_access(update.effective_user):
        context.user_data.pop("client_input", None)
        context.user_data.pop("client_target_id", None)
        await deny_admin_access(update)
        return

    if input_mode == ADMIN_MANAGEMENT_INPUT_TELEGRAM_ID:
        if not has_owner_access(update.effective_user):
            context.user_data.pop("client_input", None)
            await msg.reply_text("⛔️ Недостаточно прав.")
            return
        telegram_id = msg.text.strip()
        if not telegram_id.isdigit():
            await msg.reply_text("Введите числовой Telegram ID.", parse_mode="HTML")
            return
        context.user_data.pop("client_input", None)
        context.user_data["admin_management_target_id"] = telegram_id
        await msg.reply_text("Выберите роль:", reply_markup=admin_role_keyboard("add", telegram_id))
        return

    if input_mode == NOTIFICATION_CHAT_INPUT:
        kind = str(context.user_data.get("notification_chat_kind") or "")
        if kind not in NOTIFICATION_CHAT_META:
            context.user_data.pop("client_input", None)
            context.user_data.pop("notification_chat_kind", None)
            await msg.reply_text("Тип чата не найден.", reply_markup=notification_chats_keyboard())
            return
        chat_id = msg.text.strip()
        if _parse_chat_id(chat_id) is None:
            await msg.reply_text("Введите chat_id числом, например <code>-1001234567890</code>.", parse_mode="HTML")
            return
        set_notification_chat_id(kind, chat_id)
        context.user_data.pop("client_input", None)
        context.user_data.pop("notification_chat_kind", None)
        await msg.reply_text("✅ Чат уведомлений сохранён.", parse_mode="HTML", reply_markup=notification_chat_detail_keyboard(kind))
        return

    if input_mode in {USD_RUB_INPUT_MANUAL_RATE, USD_RUB_INPUT_MARKUP}:
        if not has_admin_access(update.effective_user):
            context.user_data.pop("client_input", None)
            await deny_admin_access(update)
            return
        if input_mode == USD_RUB_INPUT_MANUAL_RATE:
            rate = normalize_rate(msg.text.strip().replace(",", "."))
            if rate is None:
                await msg.reply_text("Введите курс числом от 30 до 200, например <code>92.5</code>.", parse_mode="HTML")
                return
            markup = get_configured_usd_rub_markup_percent()
            save_usd_rub_settings(
                manual_rate=round(rate, 4),
                rate_checked_at=now_str(),
                final_usd_rub_rate=round(rate * (1 + markup / 100), 4),
            )
        else:
            markup = normalize_percent(msg.text.strip().replace(",", "."))
            if markup is None:
                await msg.reply_text("Введите наценку числом от 0 до 30, например <code>1.5</code>.", parse_mode="HTML")
                return
            base_rate = get_manual_usd_rub_rate() or normalize_rate(get_usd_rub_settings().get("market_usd_rub_rate")) or USD_RUB_FALLBACK_RATE
            save_usd_rub_settings(
                markup_percent=round(markup, 4),
                rate_checked_at=now_str(),
                final_usd_rub_rate=round(base_rate * (1 + markup / 100), 4),
            )
        context.user_data.pop("client_input", None)
        await msg.reply_text("✅ Настройки USD/RUB сохранены.", parse_mode="HTML", reply_markup=usd_rub_admin_keyboard())
        return

    if input_mode in {PAYMENT_ADMIN_INPUT_TITLE, PAYMENT_ADMIN_INPUT_CREDENTIALS}:
        method_key = str(context.user_data.get("payment_method_key") or "")
        method = get_payment_method(method_key)
        if not method:
            context.user_data.pop("client_input", None)
            context.user_data.pop("payment_method_key", None)
            await msg.reply_text("Способ оплаты не найден.", reply_markup=payment_methods_admin_keyboard())
            return

        if input_mode == PAYMENT_ADMIN_INPUT_TITLE:
            client_title = msg.text.strip()
            if not client_title:
                await msg.reply_text("Введите непустое публичное название.")
                return
            update_payment_method(method_key, client_title=client_title)
            context.user_data.pop("client_input", None)
            context.user_data.pop("payment_method_key", None)
            await msg.reply_text(
                "✅ Публичное название сохранено.",
                reply_markup=payment_method_admin_keyboard(method_key),
            )
            return

        credentials = parse_credentials_input(msg.text.strip(), method_key)
        if not credentials:
            await msg.reply_text("Введите API данные или реквизиты.")
            return
        method_credentials = method.get("credentials") if isinstance(method.get("credentials"), dict) else {}
        method_credentials.update(credentials)
        update_payment_method(method_key, credentials=method_credentials)
        if method_key == "card" and credentials.get("card_details"):
            cfg = load_config()
            cfg.setdefault("payment", {})["card"] = credentials["card_details"]
            save_config(cfg)
        context.user_data.pop("client_input", None)
        context.user_data.pop("payment_method_key", None)
        await msg.reply_text(
            "✅ Технические поля сохранены.",
            reply_markup=payment_method_admin_keyboard(method_key),
        )
        return

    if input_mode == BROADCAST_INPUT_MESSAGE:
        if not has_broadcast_access(update.effective_user):
            context.user_data.pop("client_input", None)
            context.user_data.pop("broadcast_category", None)
            await msg.reply_text("⛔ Рассылки доступны только ADMIN и OWNER.")
            return
        category = str(context.user_data.get("broadcast_category") or "")
        if category not in BROADCAST_CATEGORIES:
            context.user_data.pop("client_input", None)
            context.user_data.pop("broadcast_category", None)
            await msg.reply_text("Категория рассылки не найдена.", reply_markup=broadcast_menu_keyboard(), parse_mode="HTML")
            return
        text = msg.text.strip()
        if not text:
            await msg.reply_text("Введите непустой текст рассылки.")
            return
        if not broadcast_recipients(category):
            context.user_data.pop("client_input", None)
            context.user_data.pop("broadcast_category", None)
            await msg.reply_text("В выбранной категории нет получателей. Рассылка не отправлена.", reply_markup=broadcast_menu_keyboard(), parse_mode="HTML")
            return
        context.user_data["broadcast_text"] = text
        context.user_data.pop("client_input", None)
        await msg.reply_text(
            broadcast_preview_text(category, text),
            parse_mode="HTML",
            reply_markup=broadcast_preview_keyboard(),
        )
        return

    if input_mode == CLIENT_INPUT_SEARCH:
        query_text = msg.text.strip()
        context.user_data.pop("client_input", None)
        results = search_clients(query_text)
        await msg.reply_text(
            search_results_text(results, query_text),
            parse_mode="HTML",
            reply_markup=search_results_keyboard(results),
        )
        return

    user_id = str(context.user_data.get("client_target_id") or "")
    if not user_id or not find_client(user_id):
        context.user_data.pop("client_input", None)
        context.user_data.pop("client_target_id", None)
        await msg.reply_text("Клиент не найден.")
        return

    if input_mode == CLIENT_INPUT_BALANCE:
        if get_user_role(update.effective_user) not in {ROLE_OWNER, ROLE_ADMIN}:
            context.user_data.pop("client_input", None)
            context.user_data.pop("client_target_id", None)
            await msg.reply_text("⛔ MANAGER не может менять баланс.")
            return
        raw_amount = msg.text.strip().replace(",", ".")
        try:
            amount = float(raw_amount)
        except ValueError:
            await msg.reply_text("Введите сумму в формате +5, -3 или +10.5.")
            return
        if amount == 0:
            await msg.reply_text("Сумма не должна быть равна 0.")
            return
        users = load_users()
        profile = users.get(user_id)
        if not isinstance(profile, dict):
            await msg.reply_text("Клиент не найден.")
            return
        old_balance = float(profile.get("slik_balance", profile.get("bonus_balance", 0)) or 0)
        new_balance = round(old_balance + amount, 2)
        profile["slik_balance"] = new_balance
        profile["bonus_balance"] = new_balance
        users[user_id] = profile
        save_users(users)
        append_balance_log(update.effective_user.id, int(user_id), amount)
        context.user_data.pop("client_input", None)
        context.user_data.pop("client_target_id", None)
        await msg.reply_text(
            "✅ Баланс обновлён.\n\n"
            f"Было: <b>{format_usd_cents(old_balance)}</b>\n"
            f"Изменение: <b>{format_usd_cents(amount)}</b>\n"
            f"Стало: <b>{format_usd_cents(new_balance)}</b>",
            parse_mode="HTML",
            reply_markup=client_card_keyboard(user_id, "buyers", update.effective_user),
        )
        return

    if input_mode == CLIENT_INPUT_MESSAGE:
        if get_user_role(update.effective_user) not in {ROLE_OWNER, ROLE_ADMIN}:
            context.user_data.pop("client_input", None)
            context.user_data.pop("client_target_id", None)
            await msg.reply_text("⛔ MANAGER не может писать клиентам.")
            return
        text = msg.text.strip()
        if not text:
            await msg.reply_text("Введите непустое сообщение.")
            return
        context.user_data.pop("client_input", None)
        context.user_data.pop("client_target_id", None)
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text=f"👨‍💻 <b>Сообщение от SLIK Mobile:</b>\n\n{html_escape(text)}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("👨‍💻 Поддержка", url=SUPPORT_URL)],
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")],
                ]),
            )
            await msg.reply_text("✅ Сообщение отправлено.", reply_markup=client_card_keyboard(user_id, "buyers", update.effective_user))
        except Exception:
            logger.exception("Не удалось доставить сообщение клиенту %s", user_id)
            await msg.reply_text("❌ Не удалось доставить сообщение.", reply_markup=client_card_keyboard(user_id, "buyers", update.effective_user))


# ─── Ответ админа клиенту через reply ────────────────────────────────────────

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Если администратор отвечает reply на уведомление в админ-чате — пересылаем клиенту."""
    msg = update.message
    if not msg or not msg.reply_to_message:
        return

    admin_id = get_admin_chat_id()
    if not admin_id or msg.chat_id != admin_id:
        return

    if not has_admin_access(msg.from_user):
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
    if has_admin_access(user):
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
    if not has_admin_access(update.effective_user):
        await deny_admin_access(update)
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
    if not has_admin_access(update.effective_user):
        await deny_admin_access(update)
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
    if not has_admin_access(update.effective_user):
        await deny_admin_access(update)
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
    if not has_admin_access(update.effective_user):
        await deny_admin_access(update)
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
        await deny_admin_access(update)
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
        await deny_admin_access(update)
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
    if not has_admin_access(update.effective_user):
        await deny_admin_access(update)
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
    if not has_admin_access(update.effective_user):
        await deny_admin_access(update)
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
    if not has_admin_access(update.effective_user):
        await deny_admin_access(update)
        return
    await update.message.reply_text(build_orders_dashboard(), parse_mode="HTML", reply_markup=orders_dashboard_keyboard())


async def cmd_orders_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user):
        await deny_admin_access(update)
        return
    orders = orders_by_period(load_orders(), local_date())
    await send_order_list(update.message, orders[::-1], f"📅 <b>Заказы сегодня</b>")


async def cmd_orders_7d(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user):
        await deny_admin_access(update)
        return
    since = local_date() - datetime.timedelta(days=7)
    orders = orders_by_period(load_orders(), since)
    await send_order_list(update.message, orders[::-1], "📅 <b>Заказы за 7 дней</b>")


async def cmd_orders_30d(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user):
        await deny_admin_access(update)
        return
    since = local_date() - datetime.timedelta(days=30)
    orders = orders_by_period(load_orders(), since)
    await send_order_list(update.message, orders[::-1], "📅 <b>Заказы за 30 дней</b>")


async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user):
        await deny_admin_access(update)
        return
    await update.message.reply_text(build_order_list_text("pending"), parse_mode="HTML", reply_markup=order_list_keyboard("pending"))


async def cmd_completed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user):
        await deny_admin_access(update)
        return
    await update.message.reply_text(build_order_list_text("issued"), parse_mode="HTML", reply_markup=order_list_keyboard("issued"))


async def cmd_cancelled(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user):
        await deny_admin_access(update)
        return
    await update.message.reply_text(build_order_list_text("cancelled"), parse_mode="HTML", reply_markup=order_list_keyboard("cancelled"))


def calc_stats(orders: list, since: datetime.date) -> tuple[int, float]:
    filtered = orders_by_period(orders, since)
    revenue_orders = [order for order in filtered if is_revenue_order(order)]
    count = len(revenue_orders)
    total = sum(parse_price(o.get("price", "0")) for o in revenue_orders)
    return count, total


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user):
        await deny_admin_access(update)
        return
    orders = load_orders()
    today  = local_date()
    week   = today - datetime.timedelta(days=7)
    month  = today - datetime.timedelta(days=30)

    def block(since: datetime.date, label: str) -> str:
        count, total = calc_stats(orders, since)
        return f"{label}:\nЗаказов: <b>{count}</b>\nСумма: <b>${total:g}</b>"

    cancelled_orders = [o for o in orders if normalize_order_status(o.get("status")) == "cancelled"]
    cancelled_sum    = sum(parse_price(o.get("price", "0")) for o in cancelled_orders)

    revenue_orders = [order for order in orders if is_revenue_order(order)]
    all_count = len(revenue_orders)
    all_sum   = sum(parse_price(o.get("price", "0")) for o in revenue_orders)

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


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user):
        await deny_admin_access(update)
        return
    await update.message.reply_text(admin_panel_text(update.effective_user), parse_mode="HTML", reply_markup=admin_panel_keyboard(update.effective_user))


async def cmd_clients(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user):
        await deny_admin_access(update)
        return
    await update.message.reply_text(clients_dashboard_text(), parse_mode="HTML", reply_markup=clients_dashboard_keyboard())


async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_broadcast_access(update.effective_user):
        await deny_admin_access(update)
        return
    await update.message.reply_text(broadcast_menu_text(), parse_mode="HTML", reply_markup=broadcast_menu_keyboard())


def admin_panel_text(user) -> str:
    role = get_user_role(user)
    return (
        "🛠 <b>Админ-панель SLIK Mobile</b>\n\n"
        f"Роль: <b>{role}</b>\n\n"
        "Доступные разделы:\n"
        "• 📊 Бизнес-разделы — заказы, аналитика, клиенты, новости\n"
        "• 💳 Оплата и курс — платёжные способы и USD/RUB\n"
        "• 🛠 Сервис — уведомления, проверка системы, бэкапы"
    )


def admin_business_sections_text(user) -> str:
    lines = [
        "📊 <b>Бизнес-разделы</b>",
        "",
        "Выберите раздел:",
        "• 📋 Заказы",
        "• 📊 Аналитика",
        "• 👥 Клиенты",
    ]
    if has_broadcast_access(user):
        lines.append("• 📰 Новости")
    return "\n".join(lines)


def admin_payment_sections_text(user) -> str:
    return (
        "💳 <b>Оплата и курс</b>\n\n"
        "Выберите раздел:\n"
        "• 💳 Платёжные способы\n"
        "• 💱 Курс USD/RUB"
    )


def admin_service_sections_text(user) -> str:
    lines = [
        "🛠 <b>Сервис</b>",
        "",
        "Выберите раздел:",
        "• 🔔 Чаты уведомлений",
    ]
    if has_backup_access(user):
        lines.extend(["• 🩺 Проверка системы", "• 💾 Бэкапы"])
    if has_owner_access(user):
        lines.append("• 👤 Администраторы")
    return "\n".join(lines)


def admin_role_from_profile(profile: dict) -> str:
    role = str(profile.get("role", "")).upper()
    return role if role in {ROLE_OWNER, ROLE_ADMIN, ROLE_MANAGER} else ""


def admin_display_name(user_id: str, profile: dict) -> str:
    if profile.get("legacy_username"):
        return f"@{profile['legacy_username']}"
    username = str(profile.get("username") or "").strip().lstrip("@")
    full_name = str(profile.get("full_name") or "").strip()
    if username:
        return f"@{username}"
    return full_name or "Без имени"


def admin_identifier_text(user_id: str, profile: dict) -> str:
    if profile.get("legacy_username"):
        return "legacy username"
    return f"<code>{html_escape(user_id)}</code>"


def admin_target_label(user_id: str) -> str:
    if user_id.startswith("legacy_username|"):
        _prefix, _config_key, username = user_id.split("|", 2)
        return f"@{html_escape(username)}"
    return f"<code>{html_escape(user_id)}</code>"


def list_admin_users() -> list[tuple[str, dict, str]]:
    users = load_users()
    cfg = load_config()
    admins: dict[str, tuple[dict, str]] = {}
    for user_id, profile in users.items():
        if not isinstance(profile, dict):
            continue
        role = admin_role_from_profile(profile)
        if role:
            admins[str(user_id)] = (profile, role)
    for entry in cfg.get("admins", []):
        entry_text = str(entry).strip().lstrip("@")
        if entry_text.isdigit():
            admins.setdefault(entry_text, (users.get(entry_text, {}) if isinstance(users.get(entry_text), dict) else {"telegram_id": int(entry_text)}, ROLE_ADMIN))
        elif entry_text:
            admins.setdefault(f"legacy_username|admins|{entry_text}", ({"legacy_username": entry_text}, ROLE_ADMIN))
    for entry in cfg.get("managers", []):
        entry_text = str(entry).strip().lstrip("@")
        if entry_text.isdigit() and entry_text not in admins:
            admins[entry_text] = (users.get(entry_text, {}) if isinstance(users.get(entry_text), dict) else {"telegram_id": int(entry_text)}, ROLE_MANAGER)
        elif entry_text:
            admins.setdefault(f"legacy_username|managers|{entry_text}", ({"legacy_username": entry_text}, ROLE_MANAGER))
    return sorted((user_id, profile, role) for user_id, (profile, role) in admins.items())


def count_owner_roles(exclude_user_id: str | None = None) -> int:
    count = 1  # OWNER_USERNAME is the immutable primary owner.
    for user_id, _profile, role in list_admin_users():
        if role == ROLE_OWNER and str(user_id) != str(exclude_user_id or ""):
            count += 1
    return count


def set_stored_user_role(user_id: str, role: str) -> None:
    users = load_users()
    profile = users.get(str(user_id))
    if not isinstance(profile, dict):
        profile = {
            "telegram_id": int(user_id),
            "username": "",
            "full_name": "",
            "created_at": now_str(),
            "orders_count": 0,
            "total_spent": 0,
            "bonus_balance": 0,
            "slik_balance": 0,
            "referrals": [],
            "referral_clicks": 0,
            "referrer": None,
            "referral_bonus_awarded": False,
            "new_client_notified": False,
            "status": "Traveller",
        }
    profile["telegram_id"] = int(user_id)
    profile["role"] = role
    users[str(user_id)] = profile
    save_users(users)
    cfg = load_config()
    for key in ("admins", "managers"):
        cfg[key] = [entry for entry in cfg.get(key, []) if str(entry) != str(user_id)]
    if role == ROLE_ADMIN:
        cfg.setdefault("admins", []).append(str(user_id))
    elif role == ROLE_MANAGER:
        cfg.setdefault("managers", []).append(str(user_id))
    save_config(cfg)


def remove_admin_access(user_id: str) -> None:
    if user_id.startswith("legacy_username|"):
        _prefix, config_key, username = user_id.split("|", 2)
        cfg = load_config()
        cfg[config_key] = [
            entry for entry in cfg.get(config_key, [])
            if str(entry).strip().lstrip("@").lower() != username.lower()
        ]
        save_config(cfg)
        return
    set_stored_user_role(user_id, ROLE_USER)


def clear_admin_management_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get("client_input") == ADMIN_MANAGEMENT_INPUT_TELEGRAM_ID:
        context.user_data.pop("client_input", None)
    for key in list(context.user_data.keys()):
        if str(key).startswith("admin_management_"):
            context.user_data.pop(key, None)


def admin_management_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить администратора", callback_data="admin_admins_add")],
        [InlineKeyboardButton("🔁 Изменить роль", callback_data="admin_admins_change_role")],
        [InlineKeyboardButton("➖ Удалить администратора", callback_data="admin_admins_remove")],
        [InlineKeyboardButton("◀️ Назад", callback_data="admin_service_sections")],
    ])


def admin_management_text() -> str:
    lines = [
        "👤 <b>Администраторы</b>",
        "",
        "Здесь можно управлять доступами к админ-панели.",
        "",
        "Роли:",
        "• OWNER — полный доступ и управление администраторами",
        "• ADMIN — доступ к админ-панели без управления владельцами",
        "• MANAGER — ограниченный рабочий доступ",
        "",
        "Текущие пользователи с правами:",
    ]
    admins = list_admin_users()
    if admins:
        for index, (user_id, profile, role) in enumerate(admins, 1):
            lines.append(f"{index}. {html_escape(admin_display_name(user_id, profile))} — {role} — {admin_identifier_text(user_id, profile)}")
    else:
        lines.append("• Дополнительные пользователи не найдены.")
    lines.extend(["", "Выберите действие:"])
    return "\n".join(lines)


def admin_user_list_keyboard(action: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"{admin_display_name(user_id, profile)} — {role}", callback_data=f"admin_admins_select:{action}:{user_id}")]
        for user_id, profile, role in list_admin_users()
    ]
    rows.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_admins")])
    return InlineKeyboardMarkup(rows)


def admin_role_keyboard(action: str, user_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(role, callback_data=f"admin_admins_role:{action}:{user_id}:{role}")]
        for role in ADMIN_MANAGEMENT_ROLES
    ] + [[InlineKeyboardButton("❌ Отмена", callback_data="admin_admins_cancel")]])


def admin_confirm_keyboard(action: str, user_id: str, role: str = "") -> InlineKeyboardMarkup:
    suffix = f":{role}" if role else ""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить", callback_data=f"admin_admins_confirm:{action}:{user_id}{suffix}")],
        [InlineKeyboardButton("❌ Отмена", callback_data="admin_admins_cancel")],
    ])


async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not has_admin_access(query.from_user):
        await deny_admin_access(update)
        return
    await query.answer()
    await edit_or_send(query, context, admin_panel_text(query.from_user), admin_panel_keyboard(query.from_user))


async def show_admin_business_sections(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not has_admin_access(query.from_user):
        await deny_admin_access(update)
        return
    await query.answer()
    await edit_or_send(
        query,
        context,
        admin_business_sections_text(query.from_user),
        admin_business_sections_keyboard(query.from_user),
    )


async def show_admin_payment_sections(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not has_admin_access(query.from_user):
        await deny_admin_access(update)
        return
    await query.answer()
    await edit_or_send(
        query,
        context,
        admin_payment_sections_text(query.from_user),
        admin_payment_sections_keyboard(query.from_user),
    )


async def show_admin_service_sections(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not has_admin_access(query.from_user):
        await deny_admin_access(update)
        return
    await query.answer()
    await edit_or_send(
        query,
        context,
        admin_service_sections_text(query.from_user),
        admin_service_sections_keyboard(query.from_user),
    )


async def show_admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not has_admin_access(query.from_user):
        await deny_admin_access(update)
        return
    await query.answer()
    await edit_or_send(query, context, build_orders_dashboard(), orders_dashboard_keyboard())


async def show_admin_analytics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not has_admin_access(query.from_user):
        await deny_admin_access(update)
        return
    await query.answer()
    await edit_or_send(query, context, build_analytics_text(), analytics_keyboard())


async def show_admin_clients(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not has_admin_access(query.from_user):
        await deny_admin_access(update)
        return
    await query.answer()
    await edit_or_send(query, context, clients_dashboard_text(), clients_dashboard_keyboard())


async def show_admin_news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not has_broadcast_access(query.from_user):
        await deny_admin_access(update)
        return
    await query.answer()
    await edit_or_send(query, context, broadcast_menu_text(), broadcast_menu_keyboard())


async def show_admin_healthcheck(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not has_backup_access(query.from_user):
        await deny_admin_access(update)
        return
    await query.answer()
    await edit_or_send(query, context, build_healthcheck_text(), healthcheck_keyboard())


async def show_admin_backups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not has_backup_access(query.from_user):
        await deny_admin_access(update)
        return
    await query.answer()
    await edit_or_send(query, context, build_backups_dashboard(), backups_keyboard())


async def show_admin_admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not has_owner_access(query.from_user):
        await query.answer("⛔️ Недостаточно прав.", show_alert=True)
        return
    await query.answer()
    await edit_or_send(query, context, admin_management_text(), admin_management_keyboard())


async def show_admin_payments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not has_admin_access(query.from_user):
        await deny_admin_access(update)
        return
    await query.answer()
    await edit_or_send(query, context, payment_methods_admin_text(), payment_methods_admin_keyboard())


async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat:
        await update.message.reply_text(f"Chat ID: {update.effective_chat.id}")


async def cmd_notification_routes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user):
        await deny_admin_access(update)
        return
    await update.message.reply_text(notification_routes_text(), parse_mode="HTML")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_admin_access(update.effective_user):
        await deny_admin_access(update)
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
        "/setpayment crypto <i>ссылка</i>\n"
        "/notification_routes — реальные маршруты уведомлений\n\n"
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
        "3. Получить ID группы командой /chatid\n"
        "4. Установить ADMIN_CHAT_ID = <i>-100XXXXXXXXX</i>",
        parse_mode="HTML",
    )


# ─── Роутер callback ──────────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data  = query.data

    backup_callbacks = {
        "admin_backups",
        "admin_healthcheck",
        "backup_download_latest",
        "backup_create",
        "backup_list",
        "backup_cleanup_prompt",
        "backup_cleanup_yes",
        "backup_restore_prompt",
        "backup_restore_latest",
    }
    broadcast_callbacks = {"admin_news", "broadcast_send", "broadcast_cancel"}
    owner_callbacks = ("admin_admins",)
    admin_prefixes = (
        "admin_",
        "usd_rub_",
        "notification_chat:",
        "notification_chat_edit:",
        "notification_chat_test:",
        "notification_chat_clear:",
        "notification_chats_help",
        "orders_list:",
        "order_card:",
        "order_status:",
        "clients_",
        "client_card:",
        "client_orders:",
        "client_order_card:",
        "client_balance:",
        "client_message:",
        "payment_method:",
        "payment_toggle:",
        "payment_instructions:",
        "payment_edit_",
    )
    if data.startswith(owner_callbacks) and not has_owner_access(query.from_user):
        await query.answer("⛔️ Недостаточно прав.", show_alert=True)
    elif data in backup_callbacks and not has_backup_access(query.from_user):
        await deny_admin_access(update)
    elif (data in broadcast_callbacks or data.startswith(("broadcast_cat:", "broadcast_compose:"))) and not has_broadcast_access(query.from_user):
        await deny_admin_access(update)
    elif (data.startswith(admin_prefixes) or data == "orders_stats") and not has_admin_access(query.from_user):
        await deny_admin_access(update)
    elif data.startswith("order_status:"):
        await handle_admin_action(update, context)
    elif data.startswith("orders_list:"):
        await query.answer()
        filter_key = data.split(":", 1)[1]
        await edit_or_send(query, context, build_order_list_text(filter_key), order_list_keyboard(filter_key))
    elif data.startswith("order_card:"):
        order_id = int(data.split(":", 1)[1])
        order = find_order(order_id)
        if not order:
            await query.answer("Заявка не найдена.", show_alert=True)
            return
        await query.answer()
        await edit_or_send(query, context, build_order_card_text(order), order_card_keyboard(order_id))
    elif data.startswith("clients_cat:"):
        await query.answer()
        category = data.split(":", 1)[1]
        await edit_or_send(query, context, client_list_text(category), client_list_keyboard(category))
    elif data == "clients_search":
        await query.answer()
        context.user_data["client_input"] = CLIENT_INPUT_SEARCH
        await edit_or_send(
            query, context,
            "🔍 <b>Найти клиента</b>\n\nВведите Telegram ID, username или имя клиента.",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_clients")]]),
        )
    elif data.startswith("client_card:"):
        _prefix, user_id, back = data.split(":", 2)
        if not find_client(user_id):
            await query.answer("Клиент не найден.", show_alert=True)
            return
        await query.answer()
        await edit_or_send(query, context, client_card_text(user_id), client_card_keyboard(user_id, back, query.from_user))
    elif data.startswith("client_orders:"):
        user_id = data.split(":", 1)[1]
        await query.answer()
        await edit_or_send(query, context, client_orders_text(user_id), client_orders_keyboard(user_id))
    elif data.startswith("client_order_card:"):
        _prefix, user_id, order_id_raw = data.split(":", 2)
        order = find_order(int(order_id_raw))
        if not order:
            await query.answer("Заявка не найдена.", show_alert=True)
            return
        await query.answer()
        await edit_or_send(query, context, build_order_card_text(order), order_card_keyboard(int(order_id_raw), f"client_orders:{user_id}"))
    elif data.startswith("client_balance:"):
        if get_user_role(query.from_user) not in {ROLE_OWNER, ROLE_ADMIN}:
            await query.answer("MANAGER не может менять баланс.", show_alert=True)
            return
        user_id = data.split(":", 1)[1]
        context.user_data["client_input"] = CLIENT_INPUT_BALANCE
        context.user_data["client_target_id"] = user_id
        await query.answer()
        await edit_or_send(
            query, context,
            "💰 <b>Изменить баланс</b>\n\nВведите сумму.\nПримеры:\n<code>+5</code>\n<code>-3</code>\n<code>+10.5</code>",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=f"client_card:{user_id}:buyers")]]),
        )
    elif data.startswith("client_message:"):
        if get_user_role(query.from_user) not in {ROLE_OWNER, ROLE_ADMIN}:
            await query.answer("MANAGER не может писать клиентам.", show_alert=True)
            return
        user_id = data.split(":", 1)[1]
        context.user_data["client_input"] = CLIENT_INPUT_MESSAGE
        context.user_data["client_target_id"] = user_id
        await query.answer()
        await edit_or_send(
            query, context,
            "✉️ <b>Написать клиенту</b>\n\nВведите сообщение для отправки клиенту.",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=f"client_card:{user_id}:buyers")]]),
        )
    elif data.startswith("broadcast_cat:"):
        category = data.split(":", 1)[1]
        if category not in BROADCAST_CATEGORIES:
            await query.answer("Категория не найдена.", show_alert=True)
            return
        await query.answer()
        await edit_or_send(query, context, broadcast_category_text(category), broadcast_category_keyboard(category))
    elif data.startswith("broadcast_compose:"):
        category = data.split(":", 1)[1]
        if category not in BROADCAST_CATEGORIES:
            await query.answer("Категория не найдена.", show_alert=True)
            return
        if not broadcast_recipients(category):
            await query.answer("В категории нет получателей.", show_alert=True)
            return
        context.user_data["client_input"] = BROADCAST_INPUT_MESSAGE
        context.user_data["broadcast_category"] = category
        context.user_data.pop("broadcast_text", None)
        await query.answer()
        await edit_or_send(
            query, context,
            "✍️ <b>Текст рассылки</b>\n\n"
            f"Категория: <b>{html_escape(broadcast_category_title(category))}</b>\n"
            f"Получателей: <b>{len(broadcast_recipients(category))}</b>\n\n"
            "Введите текст сообщения. В v1 поддерживается только текст.",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=f"broadcast_cat:{category}")]]),
        )
    elif data == "broadcast_cancel":
        context.user_data.pop("client_input", None)
        context.user_data.pop("broadcast_category", None)
        context.user_data.pop("broadcast_text", None)
        await query.answer("Рассылка отменена.")
        await edit_or_send(query, context, broadcast_menu_text(), broadcast_menu_keyboard())
    elif data == "broadcast_send":
        category = str(context.user_data.get("broadcast_category") or "")
        message_text = str(context.user_data.get("broadcast_text") or "").strip()
        if category not in BROADCAST_CATEGORIES:
            await query.answer("Категория рассылки не найдена.", show_alert=True)
            return
        if not message_text:
            await query.answer("Текст рассылки пустой.", show_alert=True)
            return
        recipients = broadcast_recipients(category)
        if not recipients:
            await query.answer("В категории нет получателей.", show_alert=True)
            return
        await query.answer("Отправляю рассылку...")
        sent, failed = await send_broadcast_message(context, recipients, message_text)
        context.user_data.pop("client_input", None)
        context.user_data.pop("broadcast_category", None)
        context.user_data.pop("broadcast_text", None)
        await edit_or_send(
            query, context,
            "✅ <b>Рассылка завершена</b>\n\n"
            f"Категория: <b>{html_escape(broadcast_category_title(category))}</b>\n"
            f"Отправлено: <b>{sent}</b>\n"
            f"Ошибок: <b>{failed}</b>",
            broadcast_menu_keyboard(),
        )
    elif data == "admin_admins":
        clear_admin_management_state(context)
        await show_admin_admins(update, context)
    elif data == "admin_admins_add":
        context.user_data["client_input"] = ADMIN_MANAGEMENT_INPUT_TELEGRAM_ID
        await query.answer()
        await edit_or_send(
            query,
            context,
            "➕ <b>Добавить администратора</b>\n\nВведите Telegram ID пользователя, которого нужно добавить.",
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="admin_admins_cancel")]]),
        )
    elif data == "admin_admins_cancel":
        clear_admin_management_state(context)
        await query.answer("Отменено.")
        await edit_or_send(query, context, admin_management_text(), admin_management_keyboard())
    elif data == "admin_admins_change_role":
        await query.answer()
        await edit_or_send(query, context, "Выберите пользователя:", admin_user_list_keyboard("change"))
    elif data == "admin_admins_remove":
        await query.answer()
        await edit_or_send(query, context, "Выберите пользователя:", admin_user_list_keyboard("remove"))
    elif data.startswith("admin_admins_select:"):
        _prefix, action, user_id = data.split(":", 2)
        if action == "remove":
            role = next((role for selected_id, _profile, role in list_admin_users() if selected_id == user_id), "")
            if role == ROLE_OWNER:
                await query.answer("Проверьте удаление OWNER внимательно.", show_alert=True)
            else:
                await query.answer()
            await edit_or_send(
                query,
                context,
                f"Удалить права администратора у пользователя {admin_target_label(user_id)}?",
                admin_confirm_keyboard("remove", user_id),
            )
        else:
            if user_id.startswith("legacy_username|"):
                await query.answer("Нужен Telegram ID.", show_alert=True)
                await edit_or_send(
                    query,
                    context,
                    "Для изменения роли legacy username-пользователя попросите его открыть бота и нажать /start, затем добавьте его по Telegram ID.",
                    admin_management_keyboard(),
                )
                return
            await query.answer()
            await edit_or_send(query, context, "Выберите роль:", admin_role_keyboard("change", user_id))
    elif data.startswith("admin_admins_role:"):
        _prefix, action, user_id, role = data.split(":", 3)
        if role not in ADMIN_MANAGEMENT_ROLES:
            await query.answer("Роль не найдена.", show_alert=True)
            return
        if role == ROLE_OWNER:
            await query.answer("OWNER получает полный доступ, включая управление администраторами.", show_alert=True)
        else:
            await query.answer()
        verb = "Добавить пользователя" if action == "add" else "Изменить роль пользователя"
        tail = f"с ролью {role}" if action == "add" else f"на {role}"
        await edit_or_send(
            query,
            context,
            f"{verb} <code>{html_escape(user_id)}</code> {tail}?",
            admin_confirm_keyboard(action, user_id, role),
        )
    elif data.startswith("admin_admins_confirm:"):
        parts = data.split(":")
        action, user_id = parts[1], parts[2]
        role = parts[3] if len(parts) > 3 else ""
        current_role = next((admin_role for selected_id, _profile, admin_role in list_admin_users() if selected_id == user_id), "")
        if action in {"change", "add"}:
            if role not in ADMIN_MANAGEMENT_ROLES:
                await query.answer("Роль не найдена.", show_alert=True)
                return
            if current_role == ROLE_OWNER and role != ROLE_OWNER and count_owner_roles(exclude_user_id=user_id) < 1:
                await query.answer("Нельзя снять роль с последнего OWNER.", show_alert=True)
                return
            set_stored_user_role(user_id, role)
            clear_admin_management_state(context)
            await query.answer("Роль сохранена.")
            await edit_or_send(
                query,
                context,
                f"✅ Пользователь <code>{html_escape(user_id)}</code> назначен {role}.",
                admin_management_keyboard(),
            )
        elif action == "remove":
            if current_role == ROLE_OWNER and count_owner_roles(exclude_user_id=user_id) < 1:
                await query.answer("Нельзя удалить последнего OWNER.", show_alert=True)
                return
            remove_admin_access(user_id)
            clear_admin_management_state(context)
            await query.answer("Права удалены.")
            await edit_or_send(
                query,
                context,
                f"✅ Права администратора у пользователя {admin_target_label(user_id)} удалены.",
                admin_management_keyboard(),
            )
    elif data == "admin_payments":
        await show_admin_payments(update, context)
    elif data == "admin_usd_rub":
        await query.answer()
        await edit_or_send(query, context, usd_rub_admin_text(), usd_rub_admin_keyboard())
    elif data == "usd_rub_check":
        await query.answer("Проверяю курс...")
        await refresh_usd_rub_rate_check()
        await edit_or_send(query, context, usd_rub_admin_text(), usd_rub_admin_keyboard())
    elif data == "usd_rub_set_manual":
        context.user_data["client_input"] = USD_RUB_INPUT_MANUAL_RATE
        await query.answer()
        await edit_or_send(
            query, context,
            f"✏️ <b>Ручной курс USD/RUB</b>\n\nВведите курс числом от {USD_RUB_MIN_RATE:g} до {USD_RUB_MAX_RATE:g}, например <code>72.14</code>.",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_usd_rub")]]),
        )
    elif data == "usd_rub_reset_manual":
        await query.answer("Ручной курс сброшен.")
        save_usd_rub_settings(manual_rate=None)
        await refresh_usd_rub_rate_check()
        await edit_or_send(query, context, usd_rub_admin_text(), usd_rub_admin_keyboard())
    elif data == "usd_rub_set_markup":
        context.user_data["client_input"] = USD_RUB_INPUT_MARKUP
        await query.answer()
        await edit_or_send(
            query, context,
            "📈 <b>Наценка к курсу</b>\n\nВведите процент от 0 до 30, например <code>1.5</code>.",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_usd_rub")]]),
        )
    elif data == "usd_rub_reset_markup":
        await query.answer("Наценка сброшена.")
        save_usd_rub_settings(markup_percent=USD_RUB_MARKUP_PERCENT)
        await refresh_usd_rub_rate_check()
        await edit_or_send(query, context, usd_rub_admin_text(), usd_rub_admin_keyboard())
    elif data == "admin_notification_chats":
        await query.answer()
        await edit_or_send(query, context, notification_chats_admin_text(), notification_chats_keyboard())
    elif data == "notification_chats_help":
        await query.answer()
        await edit_or_send(query, context, notification_chats_help_text(), notification_chats_help_keyboard())
    elif data.startswith("notification_chat:"):
        kind = data.split(":", 1)[1]
        if kind not in NOTIFICATION_CHAT_META:
            await query.answer("Тип чата не найден.", show_alert=True)
            return
        await query.answer()
        await edit_or_send(query, context, notification_chat_detail_text(kind), notification_chat_detail_keyboard(kind))
    elif data.startswith("notification_chat_edit:"):
        kind = data.split(":", 1)[1]
        if kind not in NOTIFICATION_CHAT_META:
            await query.answer("Тип чата не найден.", show_alert=True)
            return
        context.user_data["client_input"] = NOTIFICATION_CHAT_INPUT
        context.user_data["notification_chat_kind"] = kind
        await query.answer()
        await edit_or_send(query, context, "✏️ <b>Изменить чат уведомлений</b>\n\nОтправьте chat_id числом, например <code>-1001234567890</code>.", InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=f"notification_chat:{kind}")]]))
    elif data.startswith("notification_chat_clear:"):
        kind = data.split(":", 1)[1]
        if kind not in NOTIFICATION_CHAT_META:
            await query.answer("Тип чата не найден.", show_alert=True)
            return
        set_notification_chat_id(kind, "")
        await query.answer("Настройка очищена.")
        await edit_or_send(query, context, notification_chat_detail_text(kind), notification_chat_detail_keyboard(kind))
    elif data.startswith("notification_chat_test:"):
        kind = data.split(":", 1)[1]
        if kind not in NOTIFICATION_CHAT_META:
            await query.answer("Тип чата не найден.", show_alert=True)
            return
        chat_id = get_notification_chat_id(kind)
        if chat_id is None:
            await query.answer("Чат не настроен.", show_alert=True)
            return
        _chat_id, source = get_notification_chat_source(kind)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Тест уведомлений SLIK Mobile: {NOTIFICATION_CHAT_META[kind][2]} подключён.\nИсточник: {source}",
            )
            await query.answer("Тест отправлен.")
        except Exception as exc:
            logger.warning("Notification chat test failed for %s/%s: %s", kind, chat_id, exc)
            await query.answer("Не удалось отправить сообщение. Проверьте, что бот добавлен в группу и chat_id указан верно.", show_alert=True)
    elif data.startswith("payment_method:"):
        method_key = data.split(":", 1)[1]
        if not get_payment_method(method_key):
            await query.answer("Способ оплаты не найден.", show_alert=True)
            return
        await query.answer()
        await edit_or_send(query, context, payment_method_admin_text(method_key), payment_method_admin_keyboard(method_key))
    elif data.startswith("payment_toggle:"):
        method_key = data.split(":", 1)[1]
        method = get_payment_method(method_key)
        if not method:
            await query.answer("Способ оплаты не найден.", show_alert=True)
            return
        update_payment_method(method_key, enabled=not bool(method.get("enabled")))
        await query.answer("Настройки сохранены.")
        await edit_or_send(query, context, payment_method_admin_text(method_key), payment_method_admin_keyboard(method_key))
    elif data.startswith("payment_instructions:"):
        method_key = data.split(":", 1)[1]
        await query.answer()
        await edit_or_send(
            query, context,
            payment_method_instructions_text(method_key),
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=f"payment_method:{method_key}")]]),
        )
    elif data.startswith("payment_edit_title:"):
        method_key = data.split(":", 1)[1]
        context.user_data["client_input"] = PAYMENT_ADMIN_INPUT_TITLE
        context.user_data["payment_method_key"] = method_key
        await query.answer()
        await edit_or_send(
            query, context,
            "✏️ <b>Публичное название</b>\n\nВведите название, которое увидит клиент.",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=f"payment_method:{method_key}")]]),
        )
    elif data.startswith("payment_edit_credentials:"):
        method_key = data.split(":", 1)[1]
        context.user_data["client_input"] = PAYMENT_ADMIN_INPUT_CREDENTIALS
        context.user_data["payment_method_key"] = method_key
        await query.answer()
        await edit_or_send(
            query, context,
            "🔐 <b>API данные / реквизиты</b>\n\n"
            "Введите данные в формате <code>ключ=значение</code>.\n"
            "Можно отправить несколько строк. Для карты можно отправить реквизиты одной строкой.",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=f"payment_method:{method_key}")]]),
        )
    elif data == "orders_stats":
        await query.answer()
        await edit_or_send(
            query, context, build_orders_stats_text(),
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_orders")]]),
        )
    elif data == "backup_download_latest":
        await query.answer()
        archives = list_backup_archives()
        if not archives:
            await edit_or_send(query, context, "Архивы не найдены.", backups_keyboard())
            return
        await send_backup_archive(context.bot, query.message.chat_id, backup_info_from_path(archives[0]))
    elif data == "backup_create":
        await query.answer("Создаю бэкап...")
        try:
            backup_info = create_backup_archive()
            await edit_or_send(
                query, context,
                f"✅ <b>Бэкап создан</b>\nФайл: <code>{html_escape(backup_info['path'].name)}</code>",
                backups_keyboard(),
            )
            await send_backup_archive(context.bot, query.message.chat_id, backup_info)
        except Exception:
            logger.exception("Не удалось создать или отправить бэкап кнопкой")
            await edit_or_send(query, context, "Не удалось создать бэкап. Ошибка записана в лог.", backups_keyboard())
    elif data == "backup_list":
        await query.answer()
        await edit_or_send(query, context, build_backup_list_text(), backups_keyboard())
    elif data == "backup_restore_prompt":
        await query.answer()
        archives = list_backup_archives()
        if not archives:
            await edit_or_send(query, context, "Архивы не найдены.", backups_keyboard())
            return
        await edit_or_send(
            query, context,
            "⚠️ <b>Восстановить последний архив?</b>\n"
            f"Файл: <code>{html_escape(archives[0].name)}</code>\n\n"
            "Текущие runtime-файлы будут перезаписаны.",
            backup_restore_confirm_keyboard(),
        )
    elif data == "backup_restore_latest":
        await query.answer("Восстанавливаю бэкап...")
        archives = list_backup_archives()
        if not archives:
            await edit_or_send(query, context, "Архивы не найдены.", backups_keyboard())
            return
        try:
            restore_info = restore_backup_archive(archives[0])
            await edit_or_send(query, context, format_restore_result(restore_info), backups_keyboard())
        except Exception:
            logger.exception("Не удалось восстановить последний бэкап")
            await edit_or_send(query, context, "Не удалось восстановить бэкап. Ошибка записана в лог.", backups_keyboard())
    elif data == "backup_cleanup_prompt":
        await query.answer()
        await edit_or_send(
            query, context,
            "⚠️ <b>Удалить старые архивы?</b>\nОстанутся последние 10 архивов.",
            backup_cleanup_confirm_keyboard(),
        )
    elif data == "backup_cleanup_yes":
        await query.answer()
        cleanup_old_backups(keep_limit=10)
        await edit_or_send(query, context, "✅ Старые архивы удалены.", backups_keyboard())
    elif data in {"admin_panel", "admin_analytics_back"}:
        await show_admin_panel(update, context)
    elif data == "admin_business_sections":
        await show_admin_business_sections(update, context)
    elif data == "admin_payment_sections":
        await show_admin_payment_sections(update, context)
    elif data == "admin_service_sections":
        await show_admin_service_sections(update, context)
    elif data == "admin_orders":
        await show_admin_orders(update, context)
    elif data == "admin_analytics":
        await show_admin_analytics(update, context)
    elif data == "admin_clients":
        await show_admin_clients(update, context)
    elif data == "admin_news":
        await show_admin_news(update, context)
    elif data == "admin_healthcheck":
        await show_admin_healthcheck(update, context)
    elif data == "admin_backups":
        await show_admin_backups(update, context)
    elif data == "buy_esim":
        await show_buy_esim(update, context)
    elif data == "buy_apple_id":
        await show_apple_id_start(update, context)
    elif data.startswith("apple_id_region:"):
        await show_apple_id_region(update, context)
    elif data.startswith("apple_id_product:"):
        await show_apple_id_product(update, context)
    elif data == "region_russia":
        await show_region_russia(update, context)
    elif data == "region_worldwide":
        await show_region_worldwide(update, context)
    elif data == "instructions":
        await show_instructions(update, context)
    elif data == "support_screen":
        await show_support_screen(update, context)
    elif data.startswith("abandoned_continue:"):
        await show_existing_checkout_payment(update, context)
    elif data == "profile":
        await show_profile(update, context)
    elif data == "profile_orders":
        await show_my_orders(update, context)
    elif data.startswith("user_order:"):
        await show_user_order(update, context)
    elif data.startswith("repeat_order:"):
        await repeat_order(update, context)
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
    try:
        await app.bot.set_my_commands([
            BotCommand("start",           "Главное меню"),
            BotCommand("admin",           "Админ-панель"),
            BotCommand("clients",         "Клиенты CRM"),
            BotCommand("news",            "CRM рассылки"),
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
            BotCommand("chatid",          "Показать ID текущего чата"),
            BotCommand("help",            "Справка администратора"),
        ])
        logger.info("Команды зарегистрированы в Telegram")
    except (NetworkError, TimedOut) as exc:
        logger.warning("Telegram API timeout/network error during post_init; bot will continue: %s", exc)
    schedule_automatic_backups(app)
    schedule_abandoned_checkout_reminders(app)
    schedule_esim_expiry_reminders(app)


# ─── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Переменная окружения TELEGRAM_BOT_TOKEN не задана")

    app = (
        Application.builder()
        .token(token)
        .connect_timeout(float(os.environ.get("TELEGRAM_CONNECT_TIMEOUT", "10")))
        .read_timeout(float(os.environ.get("TELEGRAM_READ_TIMEOUT", "20")))
        .write_timeout(float(os.environ.get("TELEGRAM_WRITE_TIMEOUT", "10")))
        .pool_timeout(float(os.environ.get("TELEGRAM_POOL_TIMEOUT", "10")))
        .post_init(post_init)
        .build()
    )

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
        entry_points=[
            CallbackQueryHandler(start_purchase, pattern=r"^buy_plan_"),
            CallbackQueryHandler(start_apple_id_purchase, pattern=r"^buy_apple_id_product:"),
            CallbackQueryHandler(repeat_order, pattern=r"^repeat_order:\d+$"),
            CallbackQueryHandler(show_existing_checkout_payment, pattern=r"^abandoned_continue:\d+$"),
        ],
        states={
            WAITING_PAYMENT: [
                CallbackQueryHandler(choose_payment,
                    pattern=r"^(pay_card|pay_cryptobot|pay_freekassa|pay_yookassa|payment_done|check_payment_\d+|back_to_plan_.+)$"),
                CallbackQueryHandler(show_existing_checkout_payment, pattern=r"^abandoned_continue:\d+$"),
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
        handle_admin_action, pattern=r"^((done|cancelled)_\d+|order_status:(in_progress|issued|cancelled):\d+)$"
    ))
    app.add_handler(CallbackQueryHandler(
        show_existing_checkout_payment, pattern=r"^abandoned_continue:\d+$"
    ))

    # ── Команды ──────────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",           start))
    app.add_handler(CommandHandler("admin",           cmd_admin))
    app.add_handler(CommandHandler("clients",         cmd_clients))
    app.add_handler(CommandHandler("news",            cmd_news))
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
    app.add_handler(CommandHandler("chatid",          cmd_chatid))
    app.add_handler(CommandHandler("notification_routes", cmd_notification_routes))
    app.add_handler(CommandHandler("help",            cmd_help))

    # ── Навигационные callback'и ──────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(handle_callback))

    # ── Вводы админа в Clients CRM ──────────────────────────────────────────
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_client_crm_input,
    ), group=-1)

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
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        bootstrap_retries=int(os.environ.get("TELEGRAM_BOOTSTRAP_RETRIES", "-1")),
    )


if __name__ == "__main__":
    main()
