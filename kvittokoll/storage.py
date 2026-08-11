"""Filhantering: atomiska skrivningar, backup och inläsning av JSON-filerna.

Ingen halvskriven ``transactions.json`` ska kunna uppstå, oavsett om processen
dör mitt i en skrivning eller disken tar slut. Därför skrivs allt till en
temporärfil i samma katalog som byts in med ``os.replace``, vilket är atomiskt
på både macOS, Linux och Windows.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .models import Source, Transaction
from .normalize import now_iso

DEFAULT_SETTINGS: Dict[str, Any] = {
    "recipient_email": "",
    "sender_email": "",
    "subject_template": "Verifikat {date} {source} {amount}",
    "body_template": "Verifikat för transaktion {date}, {source}, {amount} kr.",
    "filename_template": "{date}_{amount}_{tag}",
    "data_dir": "./data",
    "receipts_dir": "./data/receipts",
    "profiles_dir": "./profiles",
    "hide_not_required": True,
}


def write_json_atomic(path, data: Any) -> None:
    """Skriv JSON atomiskt: temporärfil, fsync, byt namn."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, str(path))
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)


def _fsync_dir(directory: Path) -> None:
    """Se till att namnbytet nått disken, inte bara filsystemets cache."""
    try:
        descriptor = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def read_json(path, default: Any = None) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


class Store:
    """Läser och skriver verktygets filer. En instans per körning."""

    def __init__(self, root, settings: Optional[Dict[str, Any]] = None) -> None:
        self.root = Path(root).resolve()
        self.settings_path = self.root / "settings.json"
        self.settings = dict(DEFAULT_SETTINGS)
        if settings is not None:
            self.settings.update(settings)
        else:
            stored = read_json(self.settings_path)
            if isinstance(stored, dict):
                self.settings.update(stored)

        self.data_dir = self._resolve(self.settings["data_dir"])
        self.receipts_dir = self._resolve(self.settings["receipts_dir"])
        self.profiles_dir = self._resolve(self.settings["profiles_dir"])
        self.backups_dir = self._resolve(self.settings.get("backups_dir") or "./data/backups")
        self.trash_dir = self._resolve(self.settings.get("trash_dir") or "./data/trash")
        self.transactions_path = self.data_dir / "transactions.json"
        self.sources_path = self.data_dir / "sources.json"

        for directory in (self.data_dir, self.receipts_dir, self.backups_dir):
            directory.mkdir(parents=True, exist_ok=True)

        self._transactions: Optional[List[Transaction]] = None
        self._sources: Optional[List[Source]] = None

    def _resolve(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else (self.root / path).resolve()

    # -- transaktioner ----------------------------------------------------

    def transactions(self) -> List[Transaction]:
        if self._transactions is None:
            raw = read_json(self.transactions_path, default=[]) or []
            self._transactions = [Transaction.from_dict(item) for item in raw]
        return self._transactions

    def transaction_by_id(self, transaction_id: str) -> Optional[Transaction]:
        for transaction in self.transactions():
            if transaction.id == transaction_id:
                return transaction
        return None

    def save_transactions(self, transactions: Optional[Iterable[Transaction]] = None) -> None:
        if transactions is not None:
            self._transactions = list(transactions)
        rows = self.transactions()
        rows.sort(key=lambda t: (t.date, t.id), reverse=True)
        write_json_atomic(self.transactions_path, [t.to_dict() for t in rows])

    # -- källor -----------------------------------------------------------

    def sources(self) -> List[Source]:
        if self._sources is None:
            raw = read_json(self.sources_path, default=[]) or []
            self._sources = [Source.from_dict(item) for item in raw]
        return self._sources

    def source_by_id(self, source_id: str) -> Optional[Source]:
        for source in self.sources():
            if source.id == source_id:
                return source
        return None

    def save_sources(self, sources: Optional[Iterable[Source]] = None) -> None:
        if sources is not None:
            self._sources = list(sources)
        rows = self.sources()
        rows.sort(key=lambda s: (s.company.lower(), s.name.lower()))
        write_json_atomic(self.sources_path, [s.to_dict() for s in rows])

    def save_settings(self, settings: Optional[Dict[str, Any]] = None) -> None:
        if settings is not None:
            self.settings.update(settings)
        write_json_atomic(self.settings_path, self.settings)

    # -- backup och papperskorg -------------------------------------------

    def backup_transactions(self) -> Optional[Path]:
        """Kopiera transactions.json till backups/ före en skrivning.

        Returnerar None om filen ännu inte finns — första importen har inget
        att säkerhetskopiera.
        """
        if not self.transactions_path.exists():
            return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.backups_dir / "transactions-{}.json".format(stamp)
        counter = 2
        while target.exists():
            target = self.backups_dir / "transactions-{}-{}.json".format(stamp, counter)
            counter += 1
        shutil.copy2(str(self.transactions_path), str(target))
        return target

    def move_to_trash(self, path) -> Optional[Path]:
        """Flytta en fil till papperskorgen istället för att radera den."""
        path = Path(path)
        if not path.exists():
            return None
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.trash_dir / "{}-{}".format(stamp, path.name)
        counter = 2
        while target.exists():
            target = self.trash_dir / "{}-{}-{}".format(stamp, counter, path.name)
            counter += 1
        shutil.move(str(path), str(target))
        return target

    # -- diverse ----------------------------------------------------------

    def stamp(self) -> str:
        return now_iso()
