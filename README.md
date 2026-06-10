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
```

`TELEGRAM_BOT_TOKEN` берётся у `@BotFather`.
`ADMIN_CHAT_ID` — ID админ-группы или личного чата для уведомлений.

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


## Разделение ролей

Бот разделяет интерфейс обычных пользователей и сотрудников. При `/start` обычный пользователь видит только клиентское меню: `🌍 Купить eSIM`, `📦 Мои заказы`, `👥 Реферальная программа`, `👤 Личный кабинет`. Пользователи с правами `OWNER`, `ADMIN` или `MANAGER` дополнительно видят кнопку `🛠 Админ-панель`.

Если обычный пользователь вручную вызовет административные команды `/admin`, `/clients`, `/news`, `/backup`, `/backups` или административный callback, бот отвечает: `⛔ У вас нет доступа.`.

Роли подготовлены для будущей CRM:

| Роль | Доступные функции |
| --- | --- |
| `USER` | Покупка eSIM, просмотр своих заказов, реферальная программа, личный кабинет, SLIK Balance, cashback и статусы путешественника. |
| `MANAGER` | Все функции `USER` плюс доступ к админ-панели, CRM заказов и CRM-заготовкам клиентов/новостей. Список менеджеров подготовлен в `config.json` через поле `managers`. |
| `ADMIN` | Все функции `MANAGER` плюс текущие административные команды из списка `admins` в `config.json` и доступ к разделу бэкапов. |
| `OWNER` | Полный доступ владельца. Владелец определяется текущей логикой `OWNER_USERNAME` и может управлять администраторами. |

Текущая авторизация администраторов сохранена: владелец задаётся в коде через `OWNER_USERNAME`, дополнительные администраторы — в `config.json` в массиве `admins`. Для будущего разделения CRM в шаблон конфигурации добавлено поле `managers`.


## CRM заказов

Команда `/orders` и кнопка `📋 Заказы` в админ-панели открывают полноценный CRM-дашборд для ролей `OWNER`, `ADMIN` и `MANAGER`. На главном экране показываются счётчики за сегодня по статусам, а также количество заказов и сумма продаж за 7 и 30 дней. Если заказов нет, все показатели отображаются нулями.

CRM использует статусы заявок:

- `new` — новая заявка;
- `in_progress` — заявка взята в работу;
- `issued` — eSIM выдана клиенту;
- `cancelled` — заявка отменена.

Старые заявки без поля `status` считаются новыми (`new`), а старые значения `done` / `completed` отображаются как `issued`. Быстрые кнопки `🟡 Новые`, `🔵 В работе`, `🟢 Выданные`, `🔴 Отменённые` открывают последние 10 заявок в категории в формате `#123 — Турция 10 GB — $12.50`; если заявок нет, бот пишет `Заявок в этой категории нет.`. Команды `/pending`, `/completed` и `/cancelled` ведут в те же списки: `/pending` показывает `new` + `in_progress`, `/completed` — `issued`, `/cancelled` — `cancelled`.

Карточка заказа показывает номер, клиента, Telegram ID, username, страну, тариф, цену, способ оплаты, статус и дату. Для оплаты картой дополнительно выводятся RUB-сумма к оплате, зафиксированный курс и комиссия. Кнопки карточки меняют статус: `✅ В работу` → `in_progress`, `📤 Выдано` → `issued`, `❌ Отменить` → `cancelled`. При смене статуса бот сохраняет `orders.json`, обновляет карточку, записывает `updated_at` и `status_updated_by` с Telegram ID сотрудника.

После смены статуса клиент получает уведомление: о взятии заказа в работу, выдаче eSIM или отмене. Если Telegram не смог доставить сообщение клиенту, бот не падает и пишет warning в лог.

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

Кнопка `💾 Бэкапы` в админ-панели доступна только ролям `OWNER` и `ADMIN` и открывает кнопочный интерфейс: дата последнего бэкапа, общее число архивов и размер последнего архива. Кнопка `📥 Скачать последний` отправляет самый новый ZIP или отвечает `Архивы не найдены.`, если папка пуста. Кнопка `🆕 Создать бэкап` создаёт архив сразу, показывает имя файла и отправляет ZIP администратору. Кнопка `📋 Список архивов` выводит последние 10 ZIP-файлов с размером. Кнопка `🗑 Очистить старые` сначала спрашивает подтверждение, затем удаляет всё кроме последних 10 архивов и отвечает `✅ Старые архивы удалены.`.

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

Оплата картой в MVP подтверждается вручную менеджером. Для перевода на карту бот автоматически считает рублёвую сумму от USD-цены тарифа, добавляет комиссию `1.5%` и округляет итог вверх до целого рубля. Клиент видит только цену в USD, итоговую сумму в ₽, срок фиксации и карту; курс, комиссия и формула клиенту не показываются.

Курс USD/RUB запрашивается по цепочке источников:

1. Яндекс;
2. ЦБ РФ;
3. `open.er-api.com`;
4. `exchangerate.host`;
5. fallback `USD_RUB_FALLBACK_RATE` (по умолчанию `90`).

После выбора оплаты картой сумма фиксируется в активной платёжной сессии пользователя на 5 минут вместе с USD-ценой, курсом, источником курса, комиссией, итоговой суммой в ₽ и временем окончания фиксации. Если клиент нажал «✅ Я оплатил» в течение этих 5 минут, оформление заявки продолжается как раньше. Если фиксация истекла, заявка не создаётся, админ не уведомляется, cashback и запись в `orders.json` не начисляются/не создаются: бот получает новый курс, пересчитывает сумму, фиксирует её ещё на 5 минут и показывает клиенту новый экран оплаты. Если внешние источники курса недоступны, используется fallback-курс и в лог пишется warning; бот продолжает работу.

CryptoBot создаёт счёт и проверяет статус по кнопке клиента без изменений.

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
