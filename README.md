# SLIK Mobile Bot

Telegram-бот для ручного MVP продажи eSIM. Текущая версия принимает заявки, проверяет оплату через CryptoBot при настроенном токене, уведомляет админ-чат и позволяет менеджеру вручную выдать eSIM клиенту.

## Что важно знать

- Выдача eSIM в этой версии ручная: менеджер получает заявку в админ-чате и отправляет клиенту QR/данные eSIM самостоятельно.
- Рабочие файлы `bot/config.json` и `bot/orders.json` не хранятся в Git. На сервере они создаются из example-файлов.
- Для VPS рекомендуется запускать `bot/run_mvp.py`, а не напрямую `bot/bot.py`. Этот entrypoint сохраняет текущую логику бота и добавляет защиту для ручного MVP: глобальный обработчик ошибок, нормализацию старых заказов и экранирование пользовательского HTML в ключевых потоках.

## Переменные окружения

Создайте `.env` на сервере по примеру `.env.example`:

```env
TELEGRAM_BOT_TOKEN=1234567890:replace_me
ADMIN_CHAT_ID=-1001234567890
```

`TELEGRAM_BOT_TOKEN` берётся у `@BotFather`.
`ADMIN_CHAT_ID` — ID админ-группы или личного чата для уведомлений.

## Локальный запуск

```bash
cd bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
cp orders.example.json orders.json
export TELEGRAM_BOT_TOKEN="1234567890:replace_me"
export ADMIN_CHAT_ID="-1001234567890"
python run_mvp.py
```

## Настройка оплаты

После запуска админ может открыть `/payment_details` и задать реквизиты:

```text
/setpayment card 1234 5678 9012 3456 - Name
/setpayment crypto CRYPTOBOT_API_TOKEN
```

Оплата картой в MVP подтверждается вручную менеджером. CryptoBot создаёт счёт и проверяет статус по кнопке клиента.

## Установка на VPS через systemd

Пример ниже рассчитан на Ubuntu/Debian и директорию `/opt/slik-mobile`.

```bash
sudo adduser --system --group --home /opt/slik-mobile slik-mobile
sudo mkdir -p /opt/slik-mobile
sudo chown -R slik-mobile:slik-mobile /opt/slik-mobile
```

Загрузите проект на сервер в `/opt/slik-mobile`, затем:

```bash
cd /opt/slik-mobile
sudo -u slik-mobile python3 -m venv .venv
sudo -u slik-mobile .venv/bin/pip install -r bot/requirements.txt
sudo -u slik-mobile cp bot/config.example.json bot/config.json
sudo -u slik-mobile cp bot/orders.example.json bot/orders.json
sudo -u slik-mobile cp .env.example .env
sudo nano /opt/slik-mobile/.env
```

Установите unit:

```bash
sudo cp deploy/slik-mobile.service /etc/systemd/system/slik-mobile.service
sudo systemctl daemon-reload
sudo systemctl enable slik-mobile
sudo systemctl start slik-mobile
sudo systemctl status slik-mobile
```

Логи:

```bash
sudo journalctl -u slik-mobile -f
```

## Проверка перед запуском

1. `/start` открывает главное меню.
2. Покупка тарифа Россия создаёт заявку.
3. Админ-чат получает уведомление.
4. Кнопки `Выдано` и `Отменено` меняют статус заказа.
5. `/orders`, `/pending`, `/completed`, `/cancelled`, `/stats` не падают на пустом или старом `orders.json`.
6. Ответ менеджера reply-сообщением в админ-чате доставляется клиенту.

## Файлы данных

- `bot/config.json` — runtime-настройки, баннеры, админы, relay и платёжные реквизиты.
- `bot/orders.json` — заказы MVP.

Эти файлы нужно регулярно бэкапить на VPS и не коммитить в Git.
