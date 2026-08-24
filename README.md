# auctioneer-bot

Telegram-бот, который планирует и рассылает уведомления об аукционах
Sunflower Land по данным, уже накопленным в базе: напоминание за час до
старта и сообщение о начале аукциона. Работает на aiogram 3, использует
APScheduler для планирования уведомлений и asyncpg для доступа к
PostgreSQL.

Интеграция с api.sunflower-land.com отключена (нет доступного
SFL_AUTH_TOKEN) — бот больше не загружает новые аукционы и не запрашивает
их результаты по API. Планирование работает только по аукционам, уже
записанным в таблицу `auctions`.

## Стек

- Python 3.13
- aiogram 3
- APScheduler
- asyncpg (PostgreSQL)
- Pillow (композитинг картинок предметов на фон)

## Переменные окружения

Скопируйте `.env.example` в `.env` и заполните:

| Переменная | Назначение |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен Telegram-бота (от [@BotFather](https://t.me/BotFather)) |
| `DATABASE_URL` | Строка подключения к PostgreSQL, например `postgresql://user:password@host:5432/auctioneer` |
| `ALERT_CHAT_ID` | Чат для `/next_auction` |
| `NOTIFY_CHAT_ID` | Чат, куда шлются уведомления об аукционах (напоминания, старт) |
| `ADMIN_IDS` | Telegram user id админов через запятую — им доступны `/status`, `/next_auction`, `/test_notification` |
| `SITE_IMAGE_BASE_URL` | База для картинок предметов, по умолчанию `https://goblincodex.fun/sprites/` |

## Локальный запуск

1. Поднимите SSH-туннель к боевому `postgres-main`, если работаете с общей БД:

   ```bash
   ssh -L 5432:localhost:5432 user@postgres-main-host
   ```

2. Скопируйте `.env.example` в `.env` и укажите `DATABASE_URL=postgresql://user:password@localhost:5432/<db>`
   (порт туннеля) и остальные переменные.

3. Установите зависимости и запустите бота:

   ```bash
   pip install -r requirements.txt
   python -m app.main
   ```

При старте бот сам применяет миграции из `migrations/` и сразу вызывает
`schedule_all_pending`, чтобы восстановить расписание уведомлений по
аукционам, уже находящимся в БД.

## Команды бота

- `/ping` — проверка живости.
- `/status` — сводка по job'ам в шедулере (доступно админам).
- `/next_auction` — отправить в `ALERT_CHAT_ID` информацию о ближайшем предстоящем аукционе (админам).
- `/test_notification [reminder|started]` — отправить тестовое уведомление в `NOTIFY_CHAT_ID` для проверки формата (админам).

## Docker / Portainer

Собирается стандартным `Dockerfile`, подключается к сети `shared-net`
вместе с остальными ботами инфраструктуры. Деплой через Portainer (stack
из образа, переменные окружения задаются в конфиге стека).

Образ публикуется в GHCR при пуше git-тега вида `vX.Y.Z`
(`.github/workflows/deploy.yml`) как
`ghcr.io/dionis404/auctioneer-bot:vX.Y.Z` и `:latest`.
