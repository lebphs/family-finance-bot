"""Daily private snapshots, including formulas, without exporting credentials."""
import asyncio
from datetime import date
import json
import os
from pathlib import Path
import tempfile


class SheetsBackup:
    def __init__(self, gateway, state_dir: str, *, retention: int = 30):
        self.gateway = gateway
        self.directory = Path(state_dir) / "backups"
        self.retention = retention

    async def run(self, today: date):
        await asyncio.to_thread(self._run, today)

    def _run(self, today):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = self.directory / f"sheets-{today.isoformat()}.json"
        if target.exists():
            return
        def snapshot():
            return {"format_version": 1, "date": today.isoformat(), "worksheets": [
                {"title": ws.title, "values": ws.get_all_values(),
                 "formulas": ws.get_all_values(value_render_option="FORMULA")}
                for ws in self.gateway.spreadsheet.worksheets()
            ]}
        data = self.gateway.run(snapshot, read_only=True)
        # Never leave a partial backup marked as complete.
        fd, name = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, target)
        finally:
            Path(name).unlink(missing_ok=True)
        for expired in sorted(self.directory.glob("sheets-*.json"))[:-self.retention]:
            expired.unlink()
