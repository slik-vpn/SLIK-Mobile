# SLIK Mobile Bot

Telegram-бот для ручного MVP продажи eSIM. Текущая версия принимает заявки, проверяет оплату через CryptoBot при настроенном токене, уведомляет админ-чат и позволяет менеджеру вручную выдать eSIM клиенту.

## Что важно знать

- Выдача eSIM в этой версии ручная: менеджер получает заявку в админ-чате и отправляет клиенту QR/данные eSIM самостоятельно.
- Рабочие файлы `bot/config.json`, `bot/orders.json` и `bot/users.json` не хранятся в Git. На сервере они создаются из example-файлов.
- Для запуска на VPS используйте `bot/run_mvp.py`, а не напрямую `bot/bot.py`. Этот entrypoint сохраняет текущую логику бота и добавляет защиту для ручного MVP.
- Docker-запуск хранит runtime-данные в папке `data/` рядом с `docker-compose.yml`.

## Переменные окружения

Создайте `.env` на сервере по примеру `.env.example`:

```env
TELEGRAM_BOT_TOKEN=1234567890:replace_me
ADMIN_CHAT_ID=-1001234567890
USD_RUB_FALLBACK_RATE=90
USD_RUB_MARKUP_PERCENT=3
```

`TELEGRAM_BOT_TOKEN` берётся у `@BotFather`.
`ADMIN_CHAT_ID` — ID админ-группы или личного чата для уведомлений.
`USD_RUB_FALLBACK_RATE` — запасной курс USD/RUB для оплаты переводом на РФ карту, если публичные источники курса временно недоступны.
`USD_RUB_MARKUP_PERCENT` — наценка/буфер в процентах, который добавляется к полученному или fallback-курсу перед расчётом суммы в рублях.

## Запуск через Docker Compose

Docker-вариант подходит для Debian 11 и Ubuntu. Контейнер автоматически запускает `python run_mvp.py`, читает `.env` через Compose и при первом старте создаёт `data/config.json`, `data/orders.json` и `data/users.json` из example-файлов.

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
cp users.example.json users.json
export TELEGRAM_BOT_TOKEN="1234567890:replace_me"
export ADMIN_CHAT_ID="-1001234567890"
python run_mvp.py
```

## Личный кабинет клиента

Личный кабинет открывается кнопкой `👤 Личный кабинет` в главном меню. При первом `/start` бот автоматически создаёт профиль клиента в `users.json` и сохраняет Telegram ID, username, имя, дату создания, статус `Traveller`, счётчики активных заявок, сумму покупок, SLIK Balance в USD и реферальные поля.

В кабинете клиент видит имя, Telegram ID, текущий статус с иконкой, сколько он уже потратил в USD, прогресс до следующего статуса, количество активных заявок, `SLIK Balance` в USD и количество приглашённых. Статус пересчитывается по `total_spent` после каждой заявки:

| Статус | Порог `total_spent` | Cashback на SLIK Balance | Бонус пригласившему |
| --- | ---: | ---: | ---: |
| 🧳 Traveller | от $0 | 1% | $1 |
| ✈️ Explorer | от $50 | 2% | $2 |
| 🌎 Nomad | от $150 | 3% | $3 |
| 💎 Premium | от $300 | 5% | $5 |
| 👑 Ambassador | от $1000 | 7% | $10 |

Если до следующего статуса ещё есть прогресс, личный кабинет показывает, какой статус следующий и сколько осталось потратить, например `✈️ Explorer — осталось $18.00`. Для максимального статуса отображается `Максимальный статус достигнут 👑`. Если после заявки статус пользователя повышается, бот отправляет уведомление с новым статусом и актуальным бонусом за приглашённого друга.

Кнопка `📦 Мои заказы` показывает аккуратную историю заказов текущего пользователя из `orders.json`: сверху выводятся общее количество заказов и потраченная сумма в USD, ниже — последние 10 заказов с разделителями, страной, тарифом, суммой, датой и понятным статусом (`Новый`, `В работе`, `Выдан`, `Отменён`). Если заказов больше 10, бот добавляет подпись `Показаны последние 10 заказов.`; если заказов нет, отвечает: `📦 У вас пока нет заказов.`

После новой успешной заявки бот начисляет cashback на `SLIK Balance` в USD по текущему статусу клиента: 1% для Traveller, 2% для Explorer, 3% для Nomad, 5% для Premium и 7% для Ambassador. Cashback начисляется один раз за заказ: в `orders.json` сохраняются `cashback_awarded: true`, сумма `cashback_amount` и процент `cashback_percent`. Если у заказа уже стоит `cashback_awarded: true`, сумма заказа неизвестна или равна нулю, либо заказ отменён, повторного начисления нет. После начисления клиент получает сообщение с номером заказа, суммой cashback и новым балансом.

Кнопка `👥 Пригласить друга` показывает текущий статус пользователя, сколько он получит за первую заявку друга, фиксированный бонус друга `$1` и персональную ссылку вида `https://t.me/<bot>?start=ref_<telegram_id>`. При входе по `/start ref_<id>` бот сохраняет пригласившего, а после первой заявки приглашённого начисляет другу фиксированно `$1` на SLIK Balance в USD, а пригласившему — бонус по его текущему статусу. Один приглашённый может принести бонус только один раз. Кнопка `💰 SLIK Balance` показывает текущий баланс в USD, текущий статус, процент cashback, текущий бонус за друга, количество приглашённых друзей и сколько друзей уже принесли бонус.

`users.json` — runtime-файл: при systemd-запуске хранится в `bot/users.json`, при Docker-запуске — в `data/users.json`. Файл не коммитится в Git; пустой шаблон хранится в `bot/users.example.json`, а рабочий `users.json` создаётся автоматически, если его нет.

## Автоматические бэкапы

Бот автоматически создаёт ZIP-архив runtime-данных через 60 секунд после старта, затем каждые 5 часов. Для планировщика используется `python-telegram-bot` `JobQueue`, поэтому задача запускается вместе с polling и не требует отдельного cron.

Архивы сохраняются в папку `backups/` в корне проекта, например `/opt/SLIK-Mobile/backups/`. Если папки нет, бот создаёт её автоматически. Имя архива имеет формат `backup_YYYY-MM-DD_HH-MM.zip`, например `backup_2026-06-10_15-00.zip`.

В архив добавляются runtime-файлы, если они существуют:

- `bot/users.json`
- `bot/orders.json`
- `bot/config.json`

Если какой-то файл отсутствует, бот не падает: он пропускает файл и пишет warning в лог. После создания архива бот хранит только последние 50 ZIP-файлов, а самые старые удаляет автоматически.

После успешного автоматического создания бот отправляет ZIP в Telegram на `ADMIN_CHAT_ID` из `.env`. Если `ADMIN_CHAT_ID` не задан или некорректен, архив всё равно остаётся в `backups/`, в лог пишется warning, polling продолжает работать.

### Ручное создание и просмотр

Команды доступны только владельцу или администратору:

```text
/backup
/backups
```

`/backup` создаёт ZIP прямо сейчас, отправляет его в чат, где была вызвана команда, и отвечает `Бэкап создан и отправлен.`. При ошибке пользователь получает сообщение `Не удалось создать бэкап. Ошибка записана в лог.`, а подробности сохраняются через `logger.exception`.

`/backups` показывает последние 10 архивов из папки `backups/`, начиная с самого нового.

### Восстановление из ZIP

1. Остановите сервис, чтобы бот не писал в runtime-файлы во время восстановления:

```bash
sudo systemctl stop slik-mobile
```

2. Перейдите в корень проекта и распакуйте нужный архив поверх текущих файлов:

```bash
cd /opt/SLIK-Mobile
unzip -o backups/backup_2026-06-10_15-00.zip
```

3. Проверьте права на восстановленные файлы, если сервис запускается от отдельного пользователя:

```bash
sudo chown slik-mobile:slik-mobile bot/users.json bot/orders.json bot/config.json
```

4. Запустите сервис снова:

```bash
sudo systemctl start slik-mobile
```

## Настройка оплаты

После запуска админ может открыть `/payment_details` и задать реквизиты:

```text
/setpayment card 1234 5678 9012 3456 - Name
/setpayment crypto CRYPTOBOT_API_TOKEN
```

Оплата картой в MVP подтверждается вручную менеджером. На экране перевода бот показывает цену тарифа в USD и сумму к оплате в рублях. Для расчёта USD/RUB бот сначала запрашивает публичный курс из CBR daily JSON, затем использует fallback-источник `open.er-api.com`; если оба источника недоступны, бот не падает, пишет warning в лог и берёт `USD_RUB_FALLBACK_RATE` из окружения.

Перед показом клиенту к курсу применяется буфер `USD_RUB_MARKUP_PERCENT`. Например, при `USD_RUB_FALLBACK_RATE=90` и `USD_RUB_MARKUP_PERCENT=3` итоговый курс будет `92.70 ₽`. Итоговая сумма в рублях всегда округляется вверх до целого рубля.

CryptoBot создаёт счёт и проверяет статус по кнопке клиента.

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
sudo -u slik-mobile cp bot/users.example.json bot/users.json
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
3. Кнопка `👤 Личный кабинет` открывает профиль клиента.
4. `📦 Мои заказы` показывает только заказы текущего пользователя или сообщение `У вас пока нет заказов.`
5. Админ-чат получает уведомление.
6. Кнопки `Выдано` и `Отменено` меняют статус заказа.
7. `/orders`, `/pending`, `/completed`, `/cancelled`, `/stats` не падают на пустом или старом `orders.json`.
8. Ответ менеджера reply-сообщением в админ-чате доставляется клиенту.

## Файлы данных

- `bot/config.json` при systemd-запуске или `data/config.json` при Docker-запуске — runtime-настройки, баннеры, админы, relay и платёжные реквизиты.
- `bot/orders.json` при systemd-запуске или `data/orders.json` при Docker-запуске — заказы MVP.
- `bot/users.json` при systemd-запуске или `data/users.json` при Docker-запуске — профили клиентов для личного кабинета.

Эти файлы нужно регулярно бэкапить на VPS и не коммитить в Git.
