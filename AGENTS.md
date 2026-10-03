# Family Finance Bot — project context

## Purpose

This repository contains a Telegram bot for recording family expenses in a
Google Spreadsheet. The user-facing language is Russian.

## Architecture

- `main.py` loads `.env` and starts `AsyncSchedulerBot`.
- `scheduler_bot.py` configures aiogram, runs polling, sends daily reminders,
  and rotates the `Transactions` worksheet at the start of a new month.
- `handlers/expenses.py` implements the expense-entry FSM: category, amount,
  then description/subcategory.
- `handlers/user.py` handles statistics, chart generation, and deletion of the
  latest transaction.
- `keyboards/user.py` builds reply and inline keyboards from spreadsheet data.
- `sheet.py` is the Google Sheets gateway and contains chart generation.

## External configuration

- Required environment variables: `BOT_TOKEN`, `GOOGLE_SHEET_ID`.
- Google authentication currently uses `google-credentials.json` next to
  `sheet.py`.
- Never print, commit, or expose values from `.env` or Google credentials.
- The spreadsheet is expected to contain `Main`, `Preferences`, and
  `Transactions` worksheets.
- Categories/subcategories come from `Preferences!B4:C43`.
- Statistics come from `Main!J11:K23`.
- New transactions are inserted into row 2 of `Transactions`.

## Development commands

```powershell
python -m unittest discover -s tests -v
python main.py
docker compose up --build
```

There are currently no automated tests, so add focused tests when changing
business logic. Avoid connecting to the real Telegram bot or spreadsheet in
tests; mock those boundaries.

## Implementation conventions

- The project uses Python and aiogram 3.x.
- Keep Telegram handlers asynchronous. Run blocking gspread and matplotlib
  work through `asyncio.to_thread` or isolate it behind an async service.
- Preserve the spreadsheet schema unless a requested migration explicitly
  changes it.
- Validate Telegram command arguments and numeric input before changing FSM
  state or spreadsheet data.
- Do not silently broaden access to financial data or destructive actions.
- Use UTF-8 for source files and Russian user-facing messages.
- Do not overwrite unrelated local changes. In particular, check `git status`
  before editing.

## Known issues to account for

- The final category handler in `handlers/expenses.py` uses an incorrect
  lambda filter that currently accepts arbitrary unhandled messages.
- Spreadsheet and chart operations block the event loop.
- Subscription/registration state and FSM storage are in memory and disappear
  after restart; notification time is shared across chats.
- The bot has no user authorization, while deletion affects the shared latest
  transaction.
- Monthly rotation can be missed if the bot is offline on the first day.
- Chart generation uses the shared `temp_chart.png` path and is unsafe under
  concurrent requests.
- `.dockerignore` is absent, so secrets can be copied into Docker images.
- `.env` existed in Git history. Never assume removing it from the current tree
  invalidated exposed credentials.
- Docker uses Python 3.10 while `runtime.txt` specifies Python 3.11.

## Current repository caveats

At the time this context file was created, `Procfile` was deleted in the
working tree and `google-credentials.json` was untracked. Treat both as
user-owned state and do not restore, delete, or commit them without an explicit
request.
