"""Read-only Sheets preflight, then atomic import into an empty database."""
import argparse
import asyncio

from config import load_settings
from mini_app.backend.database import Database, encode
from mini_app.backend.errors import RepositoryError, RepositorySchemaError
from mini_app.backend.repositories import GoogleSheetsUserRepository
from mini_app.backend.sheets import SheetsGateway, GoogleSheetsCategoryRepository, GoogleSheetsTransactionRepository


async def read_source(settings, gateway):
    # One shared gateway serializes reads. Stop all writers during migration.
    users = await GoogleSheetsUserRepository(settings, gateway=gateway).list()
    categories = await GoogleSheetsCategoryRepository(settings, gateway=gateway).list()
    transactions = await GoogleSheetsTransactionRepository(settings, gateway=gateway).list()
    if not users or not any(user.active and user.role.value == 'admin' for user in users) or not categories:
        raise RepositorySchemaError()
    if any(not item.transaction_id for item in transactions):
        # Assign permanent IDs using the existing metadata migration first.
        raise RepositorySchemaError()
    return users, categories, transactions


def import_snapshot(database, snapshot):
    users, categories, transactions = snapshot
    if len({item.transaction_id for item in transactions}) != len(transactions):
        raise RepositorySchemaError()
    with database.connection(write=True) as conn:
        if any(conn.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone()
               for table in ('users', 'categories', 'transactions')) or conn.execute(
                   "SELECT 1 FROM metadata WHERE key='import_complete'").fetchone():
            raise ValueError('База уже содержит данные; повторный импорт запрещён')
        conn.executemany('INSERT INTO users VALUES (?, ?)', [(user.telegram_user_id, encode(user)) for user in users])
        conn.executemany('INSERT INTO categories VALUES (?, ?)', [(item.name, encode(item)) for item in categories])
        conn.executemany('INSERT INTO transactions VALUES (?, ?, ?, ?)', [
            (item.transaction_id, item.date.isoformat(), item.author_id, encode(item)) for item in transactions])
        conn.execute("INSERT INTO metadata VALUES ('import_complete', 'true')")


def main():
    parser = argparse.ArgumentParser(description='Импорт Google Sheets в SQLite; по умолчанию только проверка')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        settings = load_settings()
        snapshot = asyncio.run(read_source(settings, SheetsGateway(settings)))
        print(f'Пользователей: {len(snapshot[0])}; категорий: {len(snapshot[1])}; расходов: {len(snapshot[2])}')
        if args.apply:
            import_snapshot(Database(settings), snapshot)
        print('Импорт завершён.' if args.apply else 'Проверка завершена. База и таблица не изменены.')
    except (RepositoryError, ValueError):
        print('Импорт не выполнен: проверьте схему Sheets, постоянные ID, активного администратора и пустую базу.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
