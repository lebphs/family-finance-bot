"""Stable content version, including legacy rows without updated_at."""
from dataclasses import asdict
from hashlib import sha256
import json

from mini_app.backend.models import Transaction


def transaction_version(transaction: Transaction) -> str:
    values = asdict(transaction)
    # Numeric Google cells may round-trip 1.00 as 1.0.
    values['amount'] = format(transaction.amount.normalize(), 'f')
    return sha256(json.dumps(values, default=str, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
