# auctioneer-bot

Telegram-бот, который планирует и рассылает уведомления об аукционах
Sunflower Land: напоминание за час до старта, сообщение о начале аукциона
и итоги (топ-3 и последнее место) после завершения. Работает на aiogram 3,
использует APScheduler для планирования уведомлений и asyncpg для доступа
к PostgreSQL.

## Стек

- Python 3.13
- aiogram 3
- APScheduler
- asyncpg (PostgreSQL)
- httpx (клиент к api.sunflower-land.com)

## Переменные окружения

Скопируйте `.env.example` в `.env` и заполните:

| Переменная | Назначение |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен Telegram-бота (от [@BotFather](https://t.me/BotFather)) |
| `DATABASE_URL` | Строка подключения к PostgreSQL, например `postgresql://user:password@host:5432/auctioneer` |
| `SFL_AUTH_TOKEN` | Bearer-токен для авторизации в api.sunflower-land.com |
| `SFL_FARM_ID` | ID фермы, от имени которой опрашиваются результаты аукционов |
| `ALERT_CHAT_ID` | Чат для технических алертов (например, истёкший `SFL_AUTH_TOKEN`) |
| `NOTIFY_CHAT_ID` | Чат, куда шлются уведомления об аукционах (напоминания, старт, результаты) |
| `ADMIN_IDS` | Telegram user id админов через запятую — им доступны `/status`, `/update_auctions`, `/backfill_results`, `/test_notification` |
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

При старте бот сам применяет миграции из `migrations/` и сразу запускает
`refresh_auctions_job`, чтобы подтянуть текущие аукционы и восстановить
расписание уведомлений.

## Команды бота

- `/ping` — проверка живости.
- `/status` — сводка по job'ам в шедулере (доступно админам).
- `/update_auctions` — вручную обновить список аукционов и пересобрать расписание (админам).
- `/backfill_results` — дозагрузить результаты для завершённых аукционов, у которых их ещё нет (админам).
- `/test_notification [reminder|started|results]` — отправить тестовое уведомление в `NOTIFY_CHAT_ID` для проверки формата (админам).

## Docker / Portainer

Собирается стандартным `Dockerfile`, подключается к сети `shared-net`
вместе с остальными ботами инфраструктуры. Деплой через Portainer (stack
из образа, переменные окружения задаются в конфиге стека).

Образ публикуется в GHCR при пуше git-тега вида `vX.Y.Z`
(`.github/workflows/deploy.yml`) как
`ghcr.io/dionis404/auctioneer-bot:vX.Y.Z` и `:latest`.
