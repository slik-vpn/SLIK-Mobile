# SLIK Mobile Bot

Telegram-бот для ручного MVP продажи eSIM. Текущая версия принимает заявки, проверяет оплату через CryptoBot при настроенном токене, уведомляет админ-чат и позволяет менеджеру вручную выдать eSIM клиенту.

## Что важно знать

- Выдача eSIM в этой версии ручная: менеджер получает заявку в админ-чате и отправляет клиенту QR/данные eSIM самостоятельно.
- Рабочие файлы `bot/config.json` и `bot/orders.json` не хранятся в Git. На сервере они создаются из example-файлов.
- Для запуска на VPS используйте `bot/run_mvp.py`, а не напрямую `bot/bot.py`. Этот entrypoint сохраняет текущую логику бота и добавляет защиту для ручного MVP.
- Docker-запуск хранит runtime-данные в папке `data/` рядом с `docker-compose.yml`.

## Переменные окружения

Создайте `.env` на сервере по примеру `.env.example`:

```env
TELEGRAM_BOT_TOKEN=1234567890:replace_me
ADMIN_CHAT_ID=-1001234567890
```

`TELEGRAM_BOT_TOKEN` берётся у `@BotFather`.
`ADMIN_CHAT_ID` — ID админ-группы или личного чата для уведомлений.

## Запуск через Docker Compose

Docker-вариант подходит для Debian 11 и Ubuntu. Контейнер автоматически запускает `python run_mvp.py`, читает `.env` через Compose и при первом старте создаёт `data/config.json` и `data/orders.json` из example-файлов.

### Debian 11

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release git
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

### Ubuntu

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release git
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

### Развёртывание проекта

```bash
sudo mkdir -p /opt/slik-mobile
sudo chown -R "$USER":"$USER" /opt/slik-mobile
cd /opt/slik-mobile
git clone https://github.com/slik-vpn/SLIK-Mobile.git .
cp .env.example .env
nano .env
mkdir -p data
docker compose up -d --build
```

Логи:

```bash
docker compose logs -f slik-mobile-bot
```

Остановка и перезапуск:

```bash
docker compose stop
docker compose up -d
```

Обновление после новых коммитов:

```bash
cd /opt/slik-mobile
git pull
docker compose up -d --build
```

Бэкап runtime-данных:

```bash
tar -czf slik-mobile-data-$(date +%F).tar.gz data/
```

## Локальный запуск без Docker

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

- `bot/config.json` при systemd-запуске или `data/config.json` при Docker-запуске — runtime-настройки, баннеры, админы, relay и платёжные реквизиты.
- `bot/orders.json` при systemd-запуске или `data/orders.json` при Docker-запуске — заказы MVP.

Эти файлы нужно регулярно бэкапить на VPS и не коммитить в Git.
