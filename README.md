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
sudo mkdir -p /opt/SLIK-Mobile
sudo chown -R "$USER":"$USER" /opt/SLIK-Mobile
cd /opt/SLIK-Mobile
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
cd /opt/SLIK-Mobile
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


## Telegram Mini App (TMA)

В проект добавлен базовый Telegram Mini App foundation без переноса бизнес-логики заказов, оплат, CRM, бэкапов, аналитики или рассылок. TMA находится в `frontend/tma` и содержит статические foundation-экраны: `Главная`, `Заказы`, `Баланс`, `Рефералка`, `Профиль`.

### Переменная `TMA_URL`

Чтобы бот показал кнопку `🚀 Открыть приложение` в главном меню пользователя, задайте публичный HTTPS URL Mini App:

```env
TMA_URL=https://your-domain.example/slik-tma
```

Если `TMA_URL` не задан или пустой, бот продолжит работать как раньше и не покажет кнопку Mini App. Админ-панель не меняется.

### Локальный запуск TMA

```bash
pnpm install
pnpm --filter @workspace/tma dev
```

Для production-сборки:

```bash
pnpm --filter @workspace/tma build
```

Собранные статические файлы появятся в `frontend/tma/dist/`. Их можно разместить на любом HTTPS-хостинге, который подходит для Telegram Mini Apps.

### Подключение Web App URL в BotFather

1. Откройте `@BotFather` в Telegram.
2. Выберите вашего бота через `/mybots`.
3. Откройте `Bot Settings` → `Menu Button` или `Configure Mini App` / `Web App` в зависимости от интерфейса BotFather.
4. Укажите тот же публичный HTTPS URL, что и в `TMA_URL`.
5. Перезапустите бота с обновлённой переменной окружения.

В этом PR TMA не содержит backend API, сложной авторизации и покупки eSIM внутри приложения. Telegram WebApp SDK используется только для `ready()`, `expand()` и чтения `initDataUnsafe.user`, если Telegram передал эти данные.

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
- `bot/balance_changes.json`

Если `bot/balance_changes.json` отсутствует, бот создаёт пустой файл `[]`, добавляет его в архив и выводит предупреждение. Если отсутствует другой runtime-файл, бот не падает: он пропускает файл и пишет warning в лог. После создания архива бот хранит только последние 50 ZIP-файлов, а самые старые удаляет автоматически.

После успешного автоматического создания бот отправляет ZIP в Telegram на `ADMIN_CHAT_ID` из `.env`. Если `ADMIN_CHAT_ID` не задан или некорректен, архив всё равно остаётся в `backups/`, в лог пишется warning, polling продолжает работать.

### Ручное создание и просмотр

Команды доступны только владельцу или администратору:

```text
/backup
/backups
```

`/backup` создаёт ZIP прямо сейчас, отправляет его в чат, где была вызвана команда, и отвечает `Бэкап создан и отправлен.`. При ошибке пользователь получает сообщение `Не удалось создать бэкап. Ошибка записана в лог.`, а подробности сохраняются через `logger.exception`.

`/backups` показывает последние 10 архивов из папки `backups/`, начиная с самого нового, и прикладывает кнопки управления бэкапами.

Кнопка `💾 Бэкапы` в админ-панели доступна только ролям `OWNER` и `ADMIN` и открывает кнопочный интерфейс: дата последнего бэкапа, общее число архивов и размер последнего архива. Кнопка `📥 Скачать последний` отправляет самый новый ZIP или отвечает `Архивы не найдены.`, если папка пуста. Кнопка `🆕 Создать бэкап` создаёт архив сразу, показывает имя файла и отправляет ZIP администратору. Кнопка `📋 Список архивов` выводит последние 10 ZIP-файлов с размером. Кнопка `♻️ Восстановить последний` спрашивает подтверждение и восстанавливает runtime-файлы из самого нового архива. Кнопка `🗑 Очистить старые` сначала спрашивает подтверждение, затем удаляет всё кроме последних 10 архивов и отвечает `✅ Старые архивы удалены.`.

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

3. Старые архивы без `bot/balance_changes.json` остаются совместимыми: при ручном или кнопочном восстановлении отсутствующий файл не вызывает падения, а в интерфейсе бота показывается предупреждение.

4. Проверьте права на восстановленные файлы, если сервис запускается от отдельного пользователя:

```bash
sudo chown <service-user>:<service-group> bot/users.json bot/orders.json bot/config.json bot/balance_changes.json
```

5. Запустите сервис снова:

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

После выбора оплаты картой сумма фиксируется в активной платёжной сессии пользователя на 5 минут вместе с USD-ценой, курсом, источником курса, комиссией, итоговой суммой в ₽ и временем окончания фиксации. Если клиент нажал «✅ Я оплатил» в течение этих 5 минут, оформление заявки продолжается как раньше. Если фиксация истекла, бот получает новый курс, пересчитывает сумму, фиксирует её ещё на 5 минут и показывает клиенту новый экран оплаты. Если внешние источники курса недоступны, используется fallback-курс и в лог пишется warning; бот продолжает работу.

Abandoned checkout reminder — мягкое напоминание пользователю, который создал заказ eSIM, но не завершил оплату. Интервал задаётся переменной `.env` `ABANDONED_CHECKOUT_REMINDER_MINUTES`; если переменная не задана, используется 30 минут. Напоминание отправляется только один раз на заказ, только для свежих неоплаченных заказов за последние 24 часа и содержит кнопку продолжения оплаты текущего заказа без массовой рассылки всем пользователям.

CryptoBot создаёт счёт и проверяет статус по кнопке клиента без изменений.

## Установка на VPS через systemd

Пример ниже рассчитан на Ubuntu/Debian и фактическую production-директорию `/opt/SLIK-Mobile`. Unit-файлы из `deploy/` не задают `User=`/`Group=`, поэтому сервис запускается от системного пользователя systemd по умолчанию. Если нужен отдельный пользователь, сначала создайте его явно и отдельно обновите unit-файлы и права на директорию.

```bash
sudo mkdir -p /opt/SLIK-Mobile
sudo chown -R "$USER":"$USER" /opt/SLIK-Mobile
```

Загрузите проект на сервер в `/opt/SLIK-Mobile`, затем:

```bash
cd /opt/SLIK-Mobile
python3 -m venv venv
venv/bin/pip install -r bot/requirements.txt
cp bot/config.example.json bot/config.json
cp bot/orders.example.json bot/orders.json
cp bot/users.example.json bot/users.json
cp .env.example .env
nano /opt/SLIK-Mobile/.env
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

## Smoke test перед deploy

Перед deploy или после merge запустите read-only smoke-test из корня проекта:

```bash
python scripts/smoke_check.py
```

Скрипт выполняет только статические проверки: проверяет синтаксис `bot/bot.py` и `bot/bot_healthcheck.py`, проверяет безопасные пути в systemd unit-файлах, отсутствие неявного `User=slik-mobile`/`Group=slik-mobile` без документированного создания пользователя, а также наличие ключевых callback/data identifiers для основных меню/хендлеров и abandoned checkout. Smoke-test не пишет в `users.json` или `orders.json`, не отправляет Telegram-сообщения, не создаёт платежи и не меняет `.env` или production-файлы.

Ручной чек-лист после deploy:

1. `/start`
2. `Купить eSIM`
3. `Личный кабинет`
4. `Мои заказы`
5. `Реферальная программа`
6. `SLIK Balance`
7. `Поддержка`
8. `Админ-панель`
9. `Методы оплаты`
10. `CRM заказов`
11. `CRM клиентов`
12. `systemctl status slik-mobile`
13. `systemctl status slik-mobile-healthcheck.timer`
14. `journalctl -u slik-mobile-healthcheck.service`

## Файлы данных

- `bot/config.json` при systemd-запуске или `data/config.json` при Docker-запуске — runtime-настройки, баннеры, админы, relay и платёжные реквизиты.
- `bot/orders.json` при systemd-запуске или `data/orders.json` при Docker-запуске — заказы MVP.
- `bot/users.json` при systemd-запуске или `data/users.json` при Docker-запуске — профили клиентов для личного кабинета.

Эти файлы нужно регулярно бэкапить на VPS и не коммитить в Git.

## Clients CRM

Раздел `👥 Клиенты` доступен из админ-панели и команды `/clients` для ролей `OWNER`, `ADMIN` и `MANAGER`. Клиентом считается любой пользователь, который хотя бы один раз открыл бота и попал в `users.json`; статистика покупок дополнительно считается по `orders.json`.

### Категории клиентов

- `🆕 Без покупок` — пользователи с `orders_count == 0`.
- `💰 Покупатели` — пользователи с `orders_count > 0`.
- `🔄 Вернуть клиентов` — покупатели, у которых последний заказ был более 30 дней назад. Пока нет реальных активных eSIM, поэтому используется возраст последнего заказа.
- `💎 Топ клиенты` — ТОП-20 клиентов по `total_spent`.

На главном экране CRM показываются общее число клиентов, количество клиентов без покупок, покупателей, клиентов для возврата и Premium/VIP-клиентов. В категориях отображаются последние 20 клиентов, а каждый клиент открывается отдельной кнопкой.

### Карточка клиента

Карточка клиента показывает имя, Telegram ID, username, количество заказов, сумму покупок, `SLIK Balance`, статус, число приглашённых друзей и дату последнего заказа в формате «N дней назад». Из карточки доступны:

- `📦 Заказы клиента` — список заказов конкретного клиента с переходом в существующие карточки заказов.
- `💰 Изменить баланс` — ручная корректировка баланса.
- `✉️ Написать клиенту` — личное сообщение клиенту от админа.

### Изменение баланса

Менять `slik_balance` могут только роли `OWNER` и `ADMIN`; `MANAGER` может смотреть клиентов и заказы, но не может менять баланс. После нажатия `💰 Изменить баланс` бот принимает сумму в формате `+5`, `-3` или `+10.5`, обновляет `slik_balance` и синхронизирует `bonus_balance` в `users.json`.

Каждое изменение пишется в `bot/balance_changes.json` объектом с `admin_id`, `user_id`, `amount` и `created_at`. Этот файл включён в runtime-бэкапы.

### Поиск клиента

Кнопка `🔍 Найти клиента` просит администратора ввести Telegram ID, username или имя клиента. Бот показывает до 20 найденных совпадений кнопками, из которых можно открыть карточку клиента.

## Bot Reliability & Auto Recovery

Systemd-запуск бота усилен автоматическим восстановлением. Основной unit `slik-mobile.service` настроен с `Restart=always`, задержкой `RestartSec=5`, корректным завершением `TimeoutStopSec=10` и `KillMode=mixed`, поэтому systemd перезапускает процесс при аварийном выходе.

Дополнительно добавлен watchdog `bot/bot_healthcheck.py`, который запускается через `slik-mobile-healthcheck.timer` каждую минуту и проверяет:

- состояние `systemctl is-active slik-mobile`;
- доступность Telegram API через `getMe`;
- наличие основного PID и состояние процесса;
- серии `httpx.ConnectTimeout` и `telegram.error.TimedOut` в журнале systemd за последние 3 минуты;
- количество подряд неудачных проверок.

Если несколько проверок подряд завершаются ошибкой, watchdog выполняет `systemctl restart slik-mobile`, пишет причину и время восстановления в `/var/log/slik-mobile-healthcheck.log`, сохраняет состояние в `/var/lib/slik-mobile/healthcheck-state.json` и отправляет администратору Telegram-уведомление:

```text
⚠️ SLIK Mobile Bot Recovery

Причина:
<ошибка>

Сервис автоматически перезапущен.

Время: <timestamp>
```

Для уведомления используются `TELEGRAM_BOT_TOKEN` и `ADMIN_CHAT_ID` из `/opt/SLIK-Mobile/.env`. Если переменные не заданы, restart всё равно выполняется, а отправка уведомления пропускается с записью в лог.

Telegram HTTP client в боте имеет отдельные таймауты без бесконечного ожидания. Их можно переопределить в `.env`:

```env
TELEGRAM_CONNECT_TIMEOUT=10
TELEGRAM_READ_TIMEOUT=20
TELEGRAM_WRITE_TIMEOUT=10
TELEGRAM_POOL_TIMEOUT=10
TELEGRAM_BOOTSTRAP_RETRIES=-1
```

Сетевые ошибки Telegram API (`TimedOut`, `NetworkError`, `ConnectTimeout`) логируются и не должны останавливать процесс бота во время регистрации команд или polling; при аварийном выходе systemd и watchdog восстановят сервис.

### Установка watchdog на сервере

```bash
sudo cp deploy/slik-mobile.service /etc/systemd/system/slik-mobile.service
sudo cp deploy/slik-mobile-healthcheck.service /etc/systemd/system/slik-mobile-healthcheck.service
sudo cp deploy/slik-mobile-healthcheck.timer /etc/systemd/system/slik-mobile-healthcheck.timer
sudo systemctl daemon-reload
sudo systemctl enable --now slik-mobile.service
sudo systemctl enable --now slik-mobile-healthcheck.timer
```

### Как проверить сервис

```bash
systemctl status slik-mobile
```

### Как посмотреть таймер

```bash
systemctl list-timers
systemctl status slik-mobile-healthcheck.timer
```

### Как посмотреть логи

```bash
journalctl -u slik-mobile
journalctl -u slik-mobile-healthcheck.service
sudo tail -f /var/log/slik-mobile-healthcheck.log
```

### Как отключить watchdog

```bash
sudo systemctl disable --now slik-mobile-healthcheck.timer
```

Основной autorestart `slik-mobile.service` при этом останется включённым. Чтобы вернуть watchdog, выполните:

```bash
sudo systemctl enable --now slik-mobile-healthcheck.timer
```
