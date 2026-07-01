# AI Управляющий SLIK Place

Foundation-проект внутренней Telegram-first операционной системы для управления площадкой мероприятий SLIK Place.
MVP v1.0 закладывает модульную основу, на которую далее будут добавляться смены, зарплаты, интеграции, инциденты, задачи и лента событий.

В этом PR нет интеграций YClients, OpenAI, Авито/ВК, веб-панели и реализации смен.

## Стек

- Node.js
- TypeScript
- Telegraf
- Prisma
- SQLite
- Docker

## Настройка окружения

Скопируйте пример переменных окружения:

```bash
cp .env.example .env
```

Заполните `.env`:

```dotenv
BOT_TOKEN=1234567890:replace_me
OWNER_TELEGRAM_ID=123456789
DATABASE_URL="file:./dev.db"
```

- `BOT_TOKEN` — токен бота из @BotFather.
- `OWNER_TELEGRAM_ID` — Telegram ID владельца; этот пользователь автоматически получает роль `OWNER` и статус `ACTIVE` при `/start`.
- `DATABASE_URL` — строка подключения Prisma к SQLite.

## Локальный запуск

```bash
npm install
npm run prisma:generate
npm run prisma:migrate
npm run dev
```

## Docker

```bash
docker compose up --build
```

## npm scripts

- `npm run dev` — запуск бота в watch-режиме через `tsx`.
- `npm run build` — компиляция TypeScript в `dist/`.
- `npm run start` — запуск скомпилированного приложения.
- `npm run prisma:generate` — генерация Prisma Client.
- `npm run prisma:migrate` — локальное создание/применение миграций Prisma.

## Telegram-команды

- `/start` — регистрация пользователя и выдача owner-доступа, если Telegram ID совпадает с `OWNER_TELEGRAM_ID`.
- `/me` — показывает Telegram ID, имя, роль и статус пользователя.
