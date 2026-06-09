"""Production entrypoint for the manual SLIK Mobile MVP.

This module keeps bot.py logic intact and applies deployment-time hardening:
- global Telegram error handler
- legacy order normalization
- HTML escaping for user-provided text in high-risk flows
"""

from __future__ import annotations

import datetime
import html
import logging
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import bot

logger = logging.getLogger(__name__)

_original_load_orders = bot.load_orders
_original_save_orders = bot.save_orders


def escape_html(value: Any, default: str = "-") -> str:
    if value is None:
        return default
    text = str(value)
    if not text:
        return default
    return html.escape(text, quote=False)


def safe_user_tag(user) -> str:
    username = getattr(user, "username", None)
    return f"@{escape_html(username)}" if username else "-"


def _created_date_from_order(order: dict) -> str:
    created_date = order.get("created_date")
    if created_date:
        try:
            datetime.date.fromisoformat(str(created_date))
            return str(created_date)
        except ValueError:
            pass

    created_at = str(order.get("created_at", ""))
    try:
        return datetime.datetime.strptime(created_at[:10], "%d.%m.%Y").date().isoformat()
    except ValueError:
        return "2000-01-01"


def normalize_order(order: dict, index: int) -> dict:
    normalized = dict(order)
    order_id = normalized.get("id")
    if not isinstance(order_id, int):
        try:
            order_id = int(order_id)
        except (TypeError, ValueError):
            order_id = index
    normalized["id"] = order_id
    normalized.setdefault("number", f"#{order_id:04d}")
    normalized.setdefault("status", "new")
    normalized.setdefault("created_at", "-")
    normalized["created_date"] = _created_date_from_order(normalized)
    normalized.setdefault("payment_method", "-")
    return normalized


def load_orders() -> list:
    orders = _original_load_orders()
    if not isinstance(orders, list):
        return []
    return [normalize_order(order, idx) for idx, order in enumerate(orders, start=1) if isinstance(order, dict)]


def save_orders(orders: list) -> None:
    normalized = [normalize_order(order, idx) for idx, order in enumerate(orders, start=1) if isinstance(order, dict)]
    _original_save_orders(normalized)


def orders_by_period(orders: list, since: datetime.date) -> list:
    result = []
    for order in orders:
        try:
            created_date = datetime.date.fromisoformat(str(order.get("created_date", "2000-01-01")))
        except ValueError:
            created_date = datetime.date(2000, 1, 1)
        if created_date >= since:
            result.append(order)
    return result


def format_order_list(orders: list, title: str) -> list[str]:
    status_icon = {"new": "NEW", "done": "OK", "cancelled": "X"}
    chunks, current = [], ""
    header = f"{title} (<b>{len(orders)}</b>):\n\n"
    for idx, raw_order in enumerate(orders, start=1):
        order = normalize_order(raw_order, idx)
        icon = status_icon.get(order.get("status"), "NEW")
        line = (
            f"{icon} <b>{escape_html(order.get('number'))}</b> - {escape_html(order.get('created_at'))}\n"
            f"   Тариф: {escape_html(order.get('gb'))} - {escape_html(order.get('price'))}\n"
            f"   Клиент: {escape_html(order.get('name'))} - {escape_html(order.get('tg_handle'))}\n\n"
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


async def track_action(context, user, action: str, extra: str = "") -> None:
    admin_id = bot.get_activity_chat_id()
    if not admin_id:
        return
    text = f"<b>Действие клиента</b>\n\nДействие: {escape_html(action)}"
    if extra:
        text += f"\n{escape_html(extra)}"
    text += (
        f"\n\nИмя: {escape_html(getattr(user, 'full_name', '-'))}\n"
        f"Username: {safe_user_tag(user)}\n"
        f"Telegram ID: <code>{getattr(user, 'id', '-')}</code>\n"
        f"Время: {bot.now_str()}"
    )
    try:
        await context.bot.send_message(chat_id=admin_id, text=text, parse_mode="HTML")
    except Exception as exc:
        logger.error("track_action error: %s", exc)


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Пожалуйста, введите ваше имя:", reply_markup=bot.cancel_keyboard())
        return bot.WAITING_NAME
    context.user_data["name"] = name
    await update.message.reply_text(
        f"Отлично, <b>{escape_html(name)}</b>!\n\nУкажите ваш Telegram для связи\n(например, @username):",
        parse_mode="HTML",
        reply_markup=bot.cancel_keyboard(),
    )
    return bot.WAITING_TELEGRAM


async def notify_admin(context: ContextTypes.DEFAULT_TYPE, order: dict) -> None:
    admin_id = bot.get_orders_chat_id()
    if not admin_id:
        logger.warning("ORDERS_CHAT_ID and ADMIN_CHAT_ID are not set; order notification was not sent")
        return
    payment_line = f"Оплата: <b>{escape_html(order.get('payment_method'))}</b>\n" if order.get("payment_method") else ""
    text = (
        "<b>Новый заказ</b>\n\n"
        f"Номер заказа: <b>{escape_html(order.get('number'))}</b>\n\n"
        f"Тариф: <b>{escape_html(order.get('gb'))} / {escape_html(order.get('days'))}</b>\n"
        f"Цена: <b>{escape_html(order.get('price'))}</b>\n"
        f"{payment_line}\n"
        f"Имя: <b>{escape_html(order.get('name'))}</b>\n"
        f"Telegram: <b>{escape_html(order.get('tg_handle'))}</b>\n\n"
        f"{escape_html(order.get('created_at'))}"
    )
    try:
        await context.bot.send_message(
            chat_id=admin_id,
            text=text,
            parse_mode="HTML",
            reply_markup=bot.admin_order_keyboard(order["id"]),
        )
    except Exception as exc:
        logger.error("Order notification error: %s", exc)


async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg or not msg.reply_to_message:
        return
    admin_id = bot.get_admin_chat_id()
    if not admin_id or msg.chat_id != admin_id or not bot.is_admin(msg.from_user):
        return
    user_id = bot.load_config().get("relay", {}).get(str(msg.reply_to_message.message_id))
    if not user_id:
        return
    reply_text = (msg.text or msg.caption or "").strip()
    if not reply_text:
        return
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"<b>Ответ менеджера:</b>\n\n{escape_html(reply_text)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Поддержка", url=bot.SUPPORT_URL)],
                [InlineKeyboardButton("Главное меню", callback_data="back_main")],
            ]),
        )
        await msg.reply_text("Ответ отправлен клиенту.")
    except Exception as exc:
        await msg.reply_text(f"Не удалось отправить: {escape_html(exc)}")


async def handle_unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg or not msg.text:
        return
    user = update.effective_user
    admin_id = bot.get_admin_chat_id()
    if msg.chat_id in bot.get_configured_notification_chat_ids():
        return
    if msg.text.startswith("/") or bot.is_admin(user):
        return

    await msg.reply_text(
        "Я не понял сообщение.\n\nЯ уже позвал менеджера - он скоро поможет.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Поддержка", url=bot.SUPPORT_URL)],
            [InlineKeyboardButton("Главное меню", callback_data="back_main")],
        ]),
    )

    if admin_id:
        notification = (
            "<b>Новое сообщение от клиента</b>\n\n"
            f"Имя: {escape_html(getattr(user, 'full_name', '-'))}\n"
            f"Username: {safe_user_tag(user)}\n"
            f"Telegram ID: <code>{getattr(user, 'id', '-')}</code>\n\n"
            f"Сообщение:\n<i>{escape_html(msg.text)}</i>\n\n"
            "Ответьте reply / свайпом на это сообщение, чтобы отправить ответ клиенту."
        )
        try:
            sent = await context.bot.send_message(chat_id=admin_id, text=notification, parse_mode="HTML")
            cfg = bot.load_config()
            relay = cfg.setdefault("relay", {})
            relay[str(sent.message_id)] = user.id
            if len(relay) > 2000:
                for key in list(relay.keys())[:1000]:
                    del relay[key]
            bot.save_config(cfg)
        except Exception as exc:
            logger.error("Relay notification error: %s", exc)


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.error:
        logger.error(
            "Unhandled Telegram error",
            exc_info=(type(context.error), context.error, context.error.__traceback__),
        )
        reason = escape_html(context.error)
    else:
        logger.error("Unhandled Telegram error")
        reason = "неизвестная ошибка"

    await bot.notify_system(
        context,
        "⚠️ <b>Системная ошибка бота</b>\n\n"
        f"Причина: <code>{reason}</code>\n"
        f"Время: {escape_html(bot.now_str())}",
    )

    effective_message = getattr(update, "effective_message", None) if update else None
    if effective_message:
        try:
            await effective_message.reply_text("Произошла ошибка. Менеджер уже уведомлен, попробуйте ещё раз.")
        except Exception:
            logger.exception("Failed to notify user about an error")


def install_patches() -> None:
    bot.user_tag = safe_user_tag
    bot.load_orders = load_orders
    bot.save_orders = save_orders
    bot.orders_by_period = orders_by_period
    bot.format_order_list = format_order_list
    bot.track_action = track_action
    bot.get_name = get_name
    bot.notify_admin = notify_admin
    bot.handle_admin_reply = handle_admin_reply
    bot.handle_unknown_message = handle_unknown_message
    bot.global_error_handler = global_error_handler


def main() -> None:
    install_patches()
    bot.main()


if __name__ == "__main__":
    main()
