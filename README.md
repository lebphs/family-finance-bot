# Family Finance

Telegram-бот и Mini App для учёта семейных расходов в SQLite с ежедневной выгрузкой в Google Sheets.

## Структура

- `bot/` — Telegram-команды, обработчики расходов, клавиатуры, планировщик
  напоминаний и адаптер таблицы для бота.
- `mini_app/backend/` — HTTP API, авторизация Telegram, сервисы, репозитории
  SQLite, импорт Google Sheets, ежедневная выгрузка и резервное копирование. Бот использует эти же
  репозитории и правила доступа.
- `mini_app/frontend/` — интерфейс React, TypeScript и Vite.
- `config.py` — общая конфигурация из переменных окружения.
- `tests/` — Python-тесты с подменой внешних сервисов.
- `docs/` — требования, план реализации, инструкции запуска и деплоя.
- `deploy/` — конфигурация HTTPS-прокси для VPS.

Бот и Mini App разделены по пакетам, но запускаются одним процессом:
Uvicorn обслуживает API и собранный интерфейс, polling бота работает фоном.
База хранится в постоянном томе; записи и проверки версий выполняются атомарно. Не запускайте второй
экземпляр с тем же токеном.

Расходы, категории, пользователи и настройки напоминаний хранятся в
`STATE_DIR/finance.sqlite3`. API и бот читают базу без обращения к Google.
Права пользователя проверяются по актуальной записи базы на каждом запросе.
Раз в календарный день по времени Минска база выгружается в отдельные листы
`DB Transactions`, `DB Categories`, `DB Sync`. Правки в Google Sheets
не импортируются обратно. Настройки доступа и напоминаний остаются только в базе.
Резервные копии SQLite хранятся 30 дней в `STATE_DIR/backups`.

Перед первым запуском необходимо импортировать существующую таблицу:
[переход на SQLite](docs/database-migration.md). Пустая база не выгружается.

## Локальный запуск

Требуются Python 3.11 и Node.js 22.12+ либо Docker Compose.
Создайте `.env` по `.env.example` и разместите `google-credentials.json`
в корне проекта. Значения секретов не добавляйте в Git.

```sh
python -m pip install -r requirements.txt
python -m mini_app
```

Для разработки интерфейса в другом терминале:

```sh
cd mini_app/frontend
npm ci
npm run dev
```

Vite проксирует `/api` на `127.0.0.1:8000`. Для выдачи интерфейса самим API
сначала выполните `npm run build` в `mini_app/frontend`, затем запустите API.
`FRONTEND_DIR` по умолчанию — `mini_app/frontend/dist`; обновите этот путь,
если в существующем `.env` явно указан прежний `frontend/dist`.

Сборка и запуск в Docker:

```sh
docker compose up --build -d
```

Приложение доступно на `http://127.0.0.1:8000`, проверка — `/health`.
Настройки Telegram и локального тестирования описаны в
[инструкции разработки](docs/mini-app-local-development.md).
Деплой: [инструкция VPS](docs/vps-deployment.md).

## Проверки

```sh
python -m unittest discover -s tests -v
cd mini_app/frontend
npm test
npm run build
npm run test:e2e
```

Python-тесты не обращаются к рабочему боту и таблице. Миграция запускается
отдельно: `python -m mini_app.backend.migration`; порядок безопасного
применения описан в [инструкции миграции](docs/google-sheets-migration.md).
