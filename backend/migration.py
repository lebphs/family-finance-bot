"""Explicit, metadata-only migration. Default invocation never writes."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from uuid import uuid4

from backend.errors import RepositoryError, RepositorySchemaError
from backend.repositories import USERS_HEADERS
from backend.sheets import SheetsGateway, TRANSACTION_HEADERS, expanded, has_transaction, transaction_worksheets
from config import load_settings


@dataclass(frozen=True)
class MigrationReport:
    worksheets: int
    missing_ids: int
    headers_to_extend: int
    create_users: bool  # Create or initialize an empty Users sheet.


def migrate_sync(gateway, apply=False):
    book = gateway.spreadsheet
    # Preflight the complete workbook before the first write.
    titles = {ws.title for ws in book.worksheets()}
    if not {"Main", "Preferences", "Transactions"} <= titles:
        raise RepositorySchemaError()
    book.worksheet("Preferences").get("B4:C43")
    create_users = "Users" not in titles
    initialize_users = create_users
    if not create_users:
        user_rows = book.worksheet("Users").get_all_values()
        # Resume if creation succeeded but writing the Users header failed.
        empty_users = not any(any(cell != "" for cell in row) for row in user_rows)
        initialize_users = empty_users
        if not empty_users and tuple(book.worksheet("Users").row_values(1)) != USERS_HEADERS:
            raise RepositorySchemaError()
    plans = []
    seen_ids = set()
    missing = 0
    header_count = 0
    for ws in transaction_worksheets(book):
        rows = ws.get_all_values(value_render_option="FORMULA")
        if not rows or not all(expanded(rows[0])[:4]):
            raise RepositorySchemaError()
        header = expanded(rows[0])
        if any(existing and existing != expected
               for existing, expected in zip(header[4:9], TRANSACTION_HEADERS)):
            raise RepositorySchemaError()
        extend = tuple(header[4:9]) != TRANSACTION_HEADERS
        header_count += int(extend)
        id_rows = []
        for index, row in enumerate(rows[1:], 2):
            if not has_transaction(row):
                continue
            identifier = str(expanded(row)[6]).strip()
            if identifier:
                if identifier.startswith("=") or identifier in seen_ids:
                    raise RepositorySchemaError()
                seen_ids.add(identifier)
            else:
                id_rows.append(index)
                missing += 1
        plans.append((ws, extend, id_rows))
    report = MigrationReport(len(plans), missing, header_count, initialize_users)
    if not apply:
        return report
    if initialize_users:
        ws = (book.add_worksheet(title="Users", rows=1000, cols=9)
              if create_users else book.worksheet("Users"))
        if ws.col_count < 9:
            ws.resize(cols=9)
        ws.update("A1:I1", [list(USERS_HEADERS)], value_input_option="RAW")
    for ws, extend, id_rows in plans:
        if ws.col_count < 9:
            ws.resize(cols=9)
        updates = []
        if extend:
            updates.append({"range": "E1:I1", "values": [list(TRANSACTION_HEADERS)]})
        for index in id_rows:
            identifier = str(uuid4())
            while identifier in seen_ids:
                identifier = str(uuid4())
            seen_ids.add(identifier)
            updates.append({"range": f"G{index}", "values": [[identifier]]})
        # Each chunk is atomic; re-running resumes from already assigned IDs.
        for offset in range(0, len(updates), 500):
            ws.batch_update(updates[offset:offset + 500], value_input_option="RAW")
    return report


async def migrate(gateway, *, apply=False):
    return await asyncio.to_thread(gateway.run, migrate_sync, gateway, apply, read_only=not apply)


def main():
    parser = argparse.ArgumentParser(description="Миграция структуры Google Sheets (по умолчанию dry run)")
    parser.add_argument("--apply", action="store_true", help="Записать метаданные после резервного копирования")
    args = parser.parse_args()
    try:
        report = asyncio.run(migrate(SheetsGateway(load_settings()), apply=args.apply))
    except RepositoryError as error:
        print(str(error))
        return 1
    print(f"Листов транзакций: {report.worksheets}; строк без ID: {report.missing_ids}; "
          f"заголовков для расширения: {report.headers_to_extend}; создать Users: {report.create_users}")
    print("Миграция выполнена." if args.apply else "Dry run: изменений нет.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
