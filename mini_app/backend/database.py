"""SQLite source of truth. Blocking work belongs in worker threads.

Each write uses BEGIN IMMEDIATE, including its version/idempotency check.
Amounts are decimal strings; never SQLite REAL values.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from mini_app.backend.errors import (RepositoryUnavailableError, StaleTransactionError,
                                     TransactionConflictError, UserAlreadyExistsError)
from mini_app.backend.models import Category, CurrentUser, Transaction, User, UserRole
from mini_app.backend.transaction_version import transaction_version


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS categories (name TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS transactions (
 id TEXT PRIMARY KEY, date TEXT NOT NULL, author_id INTEGER, payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS transactions_date ON transactions(date);
CREATE INDEX IF NOT EXISTS transactions_author ON transactions(author_id);
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def encode(value):
    return json.dumps(asdict(value), ensure_ascii=False, default=str)


def user_from_json(value):
    fields = json.loads(value)
    fields['role'] = UserRole(fields['role'])
    return User(**fields)


def transaction_from_json(value):
    fields = json.loads(value)
    fields['date'] = date.fromisoformat(fields['date'])
    fields['amount'] = Decimal(fields['amount'])
    for name in ('created_at', 'updated_at'):
        fields[name] = datetime.fromisoformat(fields[name]) if fields[name] else None
    return Transaction(**fields)


class Database:
    def __init__(self, settings):
        self.path = Path(settings.state_dir) / 'finance.sqlite3'

    @contextmanager
    def connection(self, *, write=False):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = None
        try:
            connection = sqlite3.connect(self.path, timeout=30)
            self.path.chmod(0o600)
            connection.execute('PRAGMA journal_mode=WAL')
            connection.executescript(SCHEMA)
            connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield connection
            connection.commit()
        except sqlite3.Error:
            raise RepositoryUnavailableError() from None
        finally:
            if connection is not None:
                connection.close()

    def snapshot(self):
        with self.connection() as conn:
            users = [user_from_json(row[0]) for row in conn.execute('SELECT payload FROM users ORDER BY id')]
            categories = [Category(**{**json.loads(row[0]), 'subcategories': tuple(json.loads(row[0])['subcategories'])})
                          for row in conn.execute('SELECT payload FROM categories ORDER BY rowid')]
            transactions = [transaction_from_json(row[0]) for row in conn.execute(
                'SELECT payload FROM transactions ORDER BY date DESC, rowid DESC')]
            return users, categories, transactions

    def get_metadata(self, key):
        with self.connection() as conn:
            row = conn.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            return row[0] if row else None

    def set_metadata(self, key, value):
        with self.connection(write=True) as conn:
            conn.execute('INSERT OR REPLACE INTO metadata VALUES (?, ?)', (key, value))


class SQLiteUserRepository:
    def __init__(self, settings):
        self.database = Database(settings)

    async def get(self, telegram_user_id):
        return await asyncio.to_thread(self._get_sync, telegram_user_id)

    def _get_sync(self, telegram_user_id):
        with self.database.connection() as conn:
            row = conn.execute('SELECT payload FROM users WHERE id=?', (telegram_user_id,)).fetchone()
            return user_from_json(row[0]) if row else None

    async def list(self):
        return await asyncio.to_thread(self._list_sync)

    def _list_sync(self):
        with self.database.connection() as conn:
            return [user_from_json(row[0]) for row in conn.execute('SELECT payload FROM users ORDER BY id')]

    async def create(self, user):
        return await asyncio.to_thread(self._create_sync, user)

    def _create_sync(self, user):
        with self.database.connection(write=True) as conn:
            if conn.execute('SELECT 1 FROM users WHERE id=?', (user.telegram_user_id,)).fetchone():
                raise UserAlreadyExistsError()
            conn.execute('INSERT INTO users VALUES (?, ?)', (user.telegram_user_id, encode(user)))
        return user

    async def update(self, telegram_user_id, changes):
        return await asyncio.to_thread(self._update_sync, telegram_user_id, changes)

    def _update_sync(self, telegram_user_id, changes):
        with self.database.connection(write=True) as conn:
            row = conn.execute('SELECT payload FROM users WHERE id=?', (telegram_user_id,)).fetchone()
            if row is None:
                return None
            updated = replace(user_from_json(row[0]), **changes)
            conn.execute('UPDATE users SET payload=? WHERE id=?', (encode(updated), telegram_user_id))
            return updated


class SQLiteCategoryRepository:
    def __init__(self, settings):
        self.database = Database(settings)

    async def list(self):
        return await asyncio.to_thread(self._list_sync)

    def _list_sync(self):
        with self.database.connection() as conn:
            return [Category(item['name'], tuple(item['subcategories'])) for item in
                    (json.loads(row[0]) for row in conn.execute('SELECT payload FROM categories ORDER BY rowid'))]


class SQLiteTransactionRepository:
    def __init__(self, settings):
        self.database = Database(settings)

    async def list(self):
        return await asyncio.to_thread(self._list_sync)

    def _list_sync(self):
        with self.database.connection() as conn:
            return [transaction_from_json(row[0]) for row in conn.execute(
                'SELECT payload FROM transactions ORDER BY date DESC, rowid DESC')]

    @staticmethod
    def _find(conn, identifier):
        row = conn.execute('SELECT payload FROM transactions WHERE id=?', (identifier,)).fetchone()
        return transaction_from_json(row[0]) if row else None

    async def get(self, transaction_id):
        return await asyncio.to_thread(self._get_sync, transaction_id)

    def _get_sync(self, transaction_id):
        with self.database.connection() as conn:
            return self._find(conn, transaction_id)

    @staticmethod
    def _validate(item):
        if (not isinstance(item.date, date) or not item.category.strip()
                or not item.amount.is_finite() or item.amount <= 0):
            raise ValueError('Invalid transaction')

    async def create(self, *, date, description, category, amount, author, transaction_id=None):
        return await asyncio.to_thread(self._create_sync, date, description, category, amount, author, transaction_id)

    def _create_sync(self, expense_date, description, category, amount, author, transaction_id=None):
        if not isinstance(author, CurrentUser) or author.telegram_user_id <= 0:
            raise ValueError('Invalid author')
        now = datetime.now(timezone.utc)
        item = Transaction(expense_date, description, category, Decimal(str(amount)),
                           author.telegram_user_id, author.display_name, transaction_id or str(uuid4()), now, now)
        self._validate(item)
        with self.database.connection(write=True) as conn:
            existing = self._find(conn, item.transaction_id)
            if existing:
                fields = ('date', 'description', 'category', 'amount', 'author_id')
                if any(getattr(existing, field) != getattr(item, field) for field in fields):
                    raise TransactionConflictError()
                return existing
            conn.execute('INSERT INTO transactions VALUES (?, ?, ?, ?)',
                         (item.transaction_id, item.date.isoformat(), item.author_id, encode(item)))
        return item

    async def update(self, transaction_id, changes, *, expected_version=None):
        return await asyncio.to_thread(self._update_sync, transaction_id, changes, expected_version)

    def _update_sync(self, transaction_id, changes, expected_version=None):
        if not changes or set(changes) - {'date', 'description', 'category', 'amount'}:
            raise ValueError('Invalid transaction fields')
        with self.database.connection(write=True) as conn:
            item = self._find(conn, transaction_id)
            if item is None:
                return None
            if expected_version is not None and transaction_version(item) != expected_version:
                raise StaleTransactionError()
            if 'amount' in changes:
                changes = {**changes, 'amount': Decimal(str(changes['amount']))}
            updated = replace(item, **changes, updated_at=datetime.now(timezone.utc))
            self._validate(updated)
            conn.execute('UPDATE transactions SET date=?, payload=? WHERE id=?',
                         (updated.date.isoformat(), encode(updated), transaction_id))
            return updated

    async def delete(self, transaction_id, *, expected_version=None):
        return await asyncio.to_thread(self._delete_sync, transaction_id, expected_version)

    def _delete_sync(self, transaction_id, expected_version=None):
        with self.database.connection(write=True) as conn:
            item = self._find(conn, transaction_id)
            if item is None:
                return False
            if expected_version is not None and transaction_version(item) != expected_version:
                raise StaleTransactionError()
            conn.execute('DELETE FROM transactions WHERE id=?', (transaction_id,))
            return True

    async def rotate(self, today):
        return False

    def _rotate_sync(self, today):
        # All months live in the same database; nothing is cleared or archived.
        return False
