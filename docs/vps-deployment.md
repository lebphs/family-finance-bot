# VPS deployment

Приложение размещено на `root@46.62.234.101` в `/opt/family-finance`.
Mini App: https://finance.46.62.234.101.sslip.io

Используется отдельный `compose.production.yaml`: один процесс бота/API,
Caddy с автоматическим HTTPS и постоянными томами для состояния и сертификатов.
API-порт 8000 доступен на сервере только через loopback; Caddy обращается к
контейнеру по внутренней сети Docker. Dev-авторизация выключена.

## Управление

```sh
ssh root@46.62.234.101
cd /opt/family-finance
docker compose -f compose.production.yaml ps
docker compose -f compose.production.yaml config --quiet
docker compose -f compose.production.yaml restart bot
```

После передачи обновлённых исходников (без `.env`, credentials, node_modules,
локальных данных и метаданных macOS):

```sh
docker compose -f compose.production.yaml build bot
docker compose -f compose.production.yaml up -d --wait --wait-timeout 120
```

Не использовать `down -v`: том `family-finance_finance-data` хранит отметки
напоминаний и ежедневные резервные копии таблицы. Том сохраняется при redeploy.
Автоперезапуск контейнеров настроен через `restart: unless-stopped`.

## Конфигурация

На VPS `.env` содержит `BOT_TOKEN`, `GOOGLE_SHEET_ID`,
`MINI_APP_HOST=finance.46.62.234.101.sslip.io`,
`MINI_APP_URL=https://finance.46.62.234.101.sslip.io` и production-настройки.
Файл доступен только root. Google credentials монтируются read-only;
файл принадлежит `root:10001`, права `0640`, процесс приложения работает с UID 10001.
Секреты не включены в Docker-образ и исходный архив.
Не публиковать содержимое `.env`, credentials или вывод `compose config`
без `--quiet`.

Адрес зависит от внешнего DNS-сервиса sslip.io и остаётся привязанным к IP VPS.
При смене адреса обновить `MINI_APP_HOST`, `MINI_APP_URL` и меню Telegram.
Не запускать второй polling-процесс с тем же токеном.

## Проверка

```sh
curl --fail https://finance.46.62.234.101.sslip.io/health
```

При выпуске 10 октября 2026 года проверены сборка linux/amd64, 128 backend-тестов,
91 frontend-тест и offline smoke production-образа. Публичные HTTPS frontend и
healthcheck отвечают 200; API без Telegram-авторизации отвечает 401; секретные
пути отвечают 404. Проверки не выводят финансовые данные.

Авторизованные `me`, `categories`, `home`, `transactions`, `statistics` и
`reminders` проверены чтением с подписью Telegram без вывода ответов.
Общее меню бота и персональное меню подключённого участника обновлены и проверены
через Telegram API. Предыдущие настройки сохранены приватным JSON-файлом
`telegram-menu-before-vps-*.json` в постоянном томе приложения.

При первых циклах записаны две ошибки фоновой задачи. Исходные исключения
намеренно скрываются приложением; точная причина не сохранилась в логах.
Последующие циклы прошли, ежедневная резервная копия создана.

Проверка интерфейса в реальных клиентах Telegram выполняется пользователем:
открыть бота и нажать кнопку меню либо отправить `/start` и открыть Mini App.
