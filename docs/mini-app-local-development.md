# Mini App: локальная разработка и проверка

Этап 4 добавляет основу frontend; этап 5 — форму расходов, месячную сводку,
диаграмму и последние операции на главной. Остальные разделы остаются каркасом.
Контракт API и поведение при ошибках описаны в [документации этапа 5](mini-app-stage5.md).

## Локальный запуск через Docker

Готовый frontend и backend доступны через один контейнер. Compose публикует
порт только на `127.0.0.1:8000`, credentials монтируются read-only,
напоминания и резервные копии сохраняются в named volume `finance-data`.
Рабочие секреты читаются из существующего `.env`; они не включены в образ.
Dev-авторизация в Compose явно выключена: для входа нужен Telegram.

```sh
docker --context desktop-linux compose up -d --build
docker --context desktop-linux compose ps
docker --context desktop-linux compose stop
docker --context desktop-linux compose start
```

`http://127.0.0.1:8000/health` и готовый frontend доступны локально. Открытие
frontend в обычном браузере показывает отказ без initData — это ожидаемо.
Для Telegram требуется согласованный внешний HTTPS-туннель к порту 8000.
Публичный URL можно сохранить как `MINI_APP_URL` в `.env.local-docker`:
Compose опционально подхватывает этот игнорируемый файл после `.env`.
Не включайте dev-авторизацию при использовании туннеля.

Для готовой Docker-сборки туннель направляется прямо на backend (Vite не нужен):

```sh
ssh -T -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes \
  -R 80:127.0.0.1:8000 nokey@localhost.run
```

Использование внешнего сервиса туннеля требует согласия владельца приложения:
через него проходит HTTP-трафик. После получения нового HTTPS URL обновите
`.env.local-docker`, выполните `compose up -d` и обновите кнопку меню Telegram.
Откройте Mini App именно кнопкой бота — обычный браузер не передаёт initData.
SSH-соединение и Docker Desktop должны оставаться запущенными; после сна или
перезагрузки проверьте доступность туннеля. Адрес временный и может измениться.


Не запускайте одновременно `python main.py` и Compose с тем же токеном.
Сигналами завершения управляет Uvicorn; aiogram polling запускается с
`handle_signals=False`. Проверено штатное завершение контейнера с exit code 0.
Не используйте `compose down -v`, если нужно сохранить отметки и резервные копии.

## Запуск в обычном браузере

Для работы только с UI включите `VITE_LOCAL_PREVIEW=true` в
`frontend/.env.local` и запустите `npm run dev` из `frontend`.
На `http://127.0.0.1:5173` приложение откроется без Telegram и backend,
с демонстрационными расходами. Все изменения остаются в памяти и сбрасываются
при перезагрузке страницы. Режим действует только на localhost/127.0.0.1,
в Vite development, без Telegram initData; production и туннели используют
обычную авторизацию. Для работы с реальной таблицей отключите этот флаг.

Нужны Python 3.11 и Node.js 22.12+ (рекомендуется актуальный Node.js 22 LTS).
Команды выполняются из корня репозитория, если не указано другое.

1. Установите backend-зависимости в виртуальное окружение:

   ```sh
   python3.11 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   ```

2. Создайте локальный `.env` по `.env.example`, заполните backend-секреты,
   подключите Google credentials согласно существующей инструкции миграции.
   Пользователь должен присутствовать и быть активным в листе `Users`.
   Для проверки в браузере задайте:

   ```dotenv
   APP_ENV=development
   API_HOST=127.0.0.1
   API_PORT=8000
   DEV_AUTH_ENABLED=true
   ```

3. Запустите backend в отдельном терминале:

   ```sh
   python main.py
   ```

   Это также запускает существующего Telegram-бота. Не запускайте параллельно
   другой polling-процесс с тем же токеном.

4. В другом терминале установите frontend и создайте его локальные настройки:

   ```sh
   cd frontend
   npm ci
   cp .env.example .env.local
   ```

   В `frontend/.env.local` задайте:

   ```dotenv
   VITE_DEV_AUTH_ENABLED=true
   VITE_DEV_TELEGRAM_USER_ID=123456789
   ```

   Используйте Telegram ID активного участника из `Users`. Это публичная
   настройка разработки, а не средство авторизации production. Не помещайте
   сюда `BOT_TOKEN`, Google credentials, ID таблицы или Telegram `initData`.

5. Запустите `npm run dev` и откройте `http://127.0.0.1:5173`.
   Vite проксирует `/api` на `http://127.0.0.1:8000`. По этой схеме CORS не
   требуется, backend остаётся на loopback. При изменении `.env.local`
   перезапустите Vite.

Frontend отправляет dev-заголовок только на `localhost`/`127.0.0.1`, только в
режиме Vite development и только при явном включении. Backend отдельно проверяет
свою настройку, роль и активность пользователя. В production dev-авторизация
запрещена существующей конфигурацией backend; сборка frontend также её отключает.

## Проверка внутри Telegram через временный HTTPS-туннель

Используется [официальный Telegram Web App SDK](https://core.telegram.org/bots/webapps#initializing-mini-apps).
SDK загружается в `index.html`, а исходный `initData` передаётся в заголовке
`Authorization: tma …` каждого защищённого запроса. ID и роль не берутся из
`initDataUnsafe`. Подпись и срок действия проверяет backend.

1. Отключите dev-авторизацию в обоих файлах:
   `DEV_AUTH_ENABLED=false` в корневом `.env` и
   `VITE_DEV_AUTH_ENABLED=false` в `frontend/.env.local`. Перезапустите backend.
   Оставьте `API_HOST=127.0.0.1` и `APP_ENV=development`.
2. Установите [Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
   и в отдельном терминале выполните:

   ```sh
   cloudflared tunnel --url http://127.0.0.1:5173
   ```

   Альтернативы:

   - `ngrok http http://127.0.0.1:5173` после настройки ngrok.
   - SSH-туннель [localhost.run](https://localhost.run/docs/http-tunnels/),
     без отдельной установки клиента и настройки сертификатов:

     ```sh
     ssh -T -o ServerAliveInterval=60 -o ExitOnForwardFailure=yes -R 80:127.0.0.1:5173 nokey@localhost.run
     ```

     Сервис выводит HTTPS URL, обычно с hostname вида `example.lhr.life`.
     `nokey` используется для бесплатного подключения без SSH-ключа.
     Адрес может измениться; при изменении обновите hostname в Vite и URL
     кнопки бота. SSH-соединение должно оставаться открытым.
3. Из выданного адреса вида `https://example.trycloudflare.com` скопируйте
   только hostname в `frontend/.env.local`:

   ```dotenv
   VITE_TUNNEL_HOST=example.trycloudflare.com
   ```

   Запустите/перезапустите Vite: `npm run dev`. Не используйте
   `allowedHosts: true`: разрешён только указанный hostname.
4. В BotFather выберите своего бота, задайте этот HTTPS URL через
   `/setmenubutton` (или настройку Main Mini App). Откройте Mini App кнопкой
   внутри Telegram, а не обычной ссылкой в браузере.
5. Vite передаст API-запросы на локальный backend. Второй туннель и публичный
   порт backend не нужны. Для нелокального Host прокси удаляет dev-заголовок.
   Компьютер, backend, Vite и туннель должны оставаться запущенными.
6. Проверьте разрешённого участника, неизвестного/отключённого пользователя,
   переключение темы, четыре раздела, отступы около элементов Telegram и
   отсутствие горизонтальной прокрутки. Повторите на Android, iOS и Desktop.
   При ошибке сети должно появляться действие «Повторить».
7. После проверки остановите туннель и верните прежний URL кнопки в BotFather.
   При новом адресе туннеля обновите hostname и URL кнопки.

## Автоматические проверки без внешних сервисов

```sh
python -m unittest discover -s tests -v
cd frontend
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

Вместо загрузки Chromium можно использовать установленный Chrome:

```sh
CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" npm run test:e2e
```

Unit-тесты проверяют dev/Telegram-авторизацию, каждый запрос, ошибки, отмену,
навигацию, состояния доступа, тему и события safe areas. Браузерные тесты
подменяют SDK и API, блокируют загрузку Telegram SDK из сети и проверяют
мобильную ширину, обе темы, отказ и повторную загрузку. Реальные Telegram и
Google Sheets в тестах не вызываются. Скриншоты находятся в игнорируемой
`frontend/test-results/`.

Браузерные проверки также запускают fake HTTP backend на `127.0.0.1:8000`
для проверки настоящего Vite-прокси и удаления dev-заголовка на хосте туннеля.
Перед `npm run test:e2e` остановите локальные backend и Vite: порты 8000 и 5173
должны быть свободны.

`npm run build` проверяет TypeScript и создаёт `frontend/dist`. Production
выдача frontend и маршрутизация `/api` относятся к этапу публикации;
`npm run preview` предназначен только для просмотра сборки и не проксирует API.

Открытие в реальных клиентах Telegram через настоящий HTTPS-туннель требует
настроенного бота и allowlist. Оно является отдельной ручной проверкой и не
подменяется тестами с mock SDK.
