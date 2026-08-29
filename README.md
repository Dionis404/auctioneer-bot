# auctioneer-bot

Telegram-бот, который планирует и рассылает уведомления об аукционах
Sunflower Land по данным, уже накопленным в базе: напоминание за час до
старта и сообщение о начале аукциона. Работает на aiogram 3, использует
APScheduler для планирования уведомлений и asyncpg для доступа к
PostgreSQL.

Список аукционов и их результаты запрашиваются через официальный
Community API (`GET /community/data?type=auctions` и
`?type=auctionResults`, авторизация — `x-api-key`). Список обновляется
раз в неделю фоновой задачей и вручную через `/update_auctions`.

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
| `SFL_API_KEY` | Официальный API-ключ Sunflower Land (Settings → Developer Options → API Key в игре) для запроса списка аукционов и их результатов |
| `ROUTERAI_API_KEY` | Ключ [RouterAI](https://routerai.ru) для генерации живой фразы-комментария в уведомлениях (модель `google/gemini-2.5-flash-lite`). Необязателен — без него уведомления шлются обычным шаблонным текстом |
| `ALERT_CHAT_ID` | Чат для `/next_auction` |
| `NOTIFY_CHAT_ID` | Чат, куда шлются уведомления об аукционах (напоминания, старт, результаты) |
| `ADMIN_IDS` | Telegram user id админов через запятую — им доступны `/status`, `/update_auctions`, `/next_auction`, `/backfill_results`, `/test_notification`, а также технические алерты об ошибках API в личку |
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
- `/next_auction` — отправить в текущий чат информацию о ближайшем предстоящем аукционе (админам).
- `/backfill_results` — вручную дозагрузить результаты завершённых аукционов, у которых их ещё нет (админам).
- `/test_notification [reminder|started]` — отправить тестовое уведомление в `NOTIFY_CHAT_ID` для проверки формата (админам).

## Docker / Portainer

Собирается стандартным `Dockerfile`, подключается к сети `shared-net`
вместе с остальными ботами инфраструктуры. Деплой через Portainer (stack
из образа, переменные окружения задаются в конфиге стека).

Образ публикуется в GHCR при пуше git-тега вида `vX.Y.Z`
(`.github/workflows/deploy.yml`) как
`ghcr.io/dionis404/auctioneer-bot:vX.Y.Z` и `:latest`.
