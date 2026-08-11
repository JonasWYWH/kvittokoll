"""API-lagret. Vet ingenting om HTTP — tar in dictar, ger ut dictar.

Att hålla det här skiktet fritt från HTTP gör det testbart utan server, och
gör det billigt att byta ut ``server.py`` mot Flask eller FastAPI senare.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

from . import importer
from .importers import ImportError_
from .importers.profiles import load_profiles
from .models import Transaction
from .normalize import normalize_text
from .sources import match_source, new_source, suggest_pattern
from .storage import Store

# Fält i settings.json som får läsas av webbgränssnittet. Mejladresser hör till
# steg 8; de skickas med redan nu eftersom vyn visar dem skrivskyddat.
PUBLIC_SETTINGS = (
    "recipient_email",
    "sender_email",
    "subject_template",
    "body_template",
    "filename_template",
    "hide_not_required",
)


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class Api:
    def __init__(self, store: Store) -> None:
        self.store = store
        # Förhandsgranskningar väntar i minnet tills de bekräftas. Startas
        # servern om innan bekräftelse får användaren ladda upp filen igen —
        # vilket är rätt, eftersom ingenting hunnit skrivas.
        self._staged: Dict[str, Dict[str, Any]] = {}

    # -- läsning ----------------------------------------------------------

    def state(self) -> Dict[str, Any]:
        return {
            "settings": {key: self.store.settings.get(key) for key in PUBLIC_SETTINGS},
            "sources": [source.to_dict() for source in self.store.sources()],
            "profiles": [
                {"id": profile.id, "name": profile.name, "note": profile.note}
                for profile in load_profiles(self.store.profiles_dir)
            ],
            "transactions": [t.to_dict() for t in self._sorted_transactions()],
        }

    def transactions(self) -> Dict[str, Any]:
        return {"transactions": [t.to_dict() for t in self._sorted_transactions()]}

    def _sorted_transactions(self) -> List[Transaction]:
        rows = list(self.store.transactions())
        rows.sort(key=lambda t: (t.date, t.id), reverse=True)
        return rows

    # -- import -----------------------------------------------------------

    def import_preview(
        self, filename: str, data: bytes, profile_id: Optional[str] = None
    ) -> Dict[str, Any]:
        if not data:
            raise ApiError("Ingen fil togs emot.")
        try:
            result = importer.preview(self.store, filename, data, profile_id=profile_id)
        except ImportError_ as error:
            raise ApiError(str(error))
        token = uuid.uuid4().hex
        self._staged[token] = result
        payload = dict(result)
        payload["token"] = token
        return payload

    def import_commit(self, token: str) -> Dict[str, Any]:
        staged = self._staged.pop(token, None)
        if staged is None:
            raise ApiError(
                "Förhandsgranskningen finns inte kvar. Ladda upp filen igen.", status=404
            )
        result = importer.commit(self.store, staged)
        result["transactions"] = [t.to_dict() for t in self._sorted_transactions()]
        return result

    def import_cancel(self, token: str) -> Dict[str, Any]:
        self._staged.pop(token, None)
        return {"cancelled": True}

    # -- transaktioner ----------------------------------------------------

    def update_transaction(self, transaction_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
        transaction = self.store.transaction_by_id(transaction_id)
        if transaction is None:
            raise ApiError("Transaktionen finns inte.", status=404)

        source_changed = False
        if "requires_receipt" in changes:
            transaction.requires_receipt = bool(changes["requires_receipt"])
        if "note" in changes:
            transaction.note = str(changes["note"] or "")
        if "source_id" in changes:
            source_id = changes["source_id"] or None
            if source_id and self.store.source_by_id(source_id) is None:
                raise ApiError("Okänd källa: {}".format(source_id))
            transaction.source_id = source_id
            transaction.ambiguous_sources = []
            source_changed = True

        transaction.refresh_status()

        # §5.3: en manuell ändring på en rad med kopplad källa kan göras till
        # källans nya standard.
        applied_to_source = False
        if changes.get("apply_to_source") and transaction.source_id:
            source = self.store.source_by_id(transaction.source_id)
            if source is not None and "requires_receipt" in changes:
                source.requires_receipt = transaction.requires_receipt
                self.store.save_sources()
                applied_to_source = True

        # §4.3: koppla om och lär källan radens text som nytt mönster.
        pattern_added = False
        if source_changed and changes.get("add_match_pattern") and transaction.source_id:
            pattern = str(changes.get("match_pattern") or "").strip()
            if not pattern:
                pattern = suggest_pattern(transaction.description)
            source = self.store.source_by_id(transaction.source_id)
            if source is not None and pattern:
                known = {normalize_text(p) for p in source.match_patterns}
                if normalize_text(pattern) not in known:
                    source.match_patterns.append(pattern)
                    self.store.save_sources()
                    pattern_added = True

        self.store.save_transactions()
        return {
            "transaction": transaction.to_dict(),
            "applied_to_source": applied_to_source,
            "pattern_added": pattern_added,
        }

    def update_transactions_bulk(
        self, ids: List[str], changes: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Samma ändring på flera rader. Ett filskrivning, inte en per rad."""
        updated = []
        for transaction_id in ids:
            transaction = self.store.transaction_by_id(transaction_id)
            if transaction is None:
                continue
            if "requires_receipt" in changes:
                transaction.requires_receipt = bool(changes["requires_receipt"])
            if "source_id" in changes:
                source_id = changes["source_id"] or None
                if source_id and self.store.source_by_id(source_id) is None:
                    raise ApiError("Okänd källa: {}".format(source_id))
                transaction.source_id = source_id
                transaction.ambiguous_sources = []
            transaction.refresh_status()
            updated.append(transaction.to_dict())
        if updated:
            self.store.save_transactions()
        return {"updated": updated}

    # -- källor -----------------------------------------------------------

    def create_source(self, data: Dict[str, Any]) -> Dict[str, Any]:
        name = str(data.get("name") or "").strip()
        if not name:
            raise ApiError("Källan behöver ett namn.")
        source = new_source(
            name,
            self.store.sources(),
            company=data.get("company"),
            receipt_url=data.get("receipt_url"),
            settings_url=data.get("settings_url"),
            receipt_type=data.get("receipt_type"),
            requires_receipt=data.get("requires_receipt"),
            match_patterns=list(data.get("match_patterns") or []),
            filename_tag=data.get("filename_tag"),
            note=data.get("note"),
        )
        sources = self.store.sources()
        sources.append(source)
        self.store.save_sources(sources)
        return {"source": source.to_dict()}

    def rematch_sources(self) -> Dict[str, Any]:
        """Kör om källmatchningen på alla okopplade rader.

        Behövs när användaren lagt till en källa efter en import. Rader som
        redan har en källa rörs inte — koppling är alltid användarens beslut.
        """
        sources = self.store.sources()
        changed = 0
        for transaction in self.store.transactions():
            if transaction.source_id:
                continue
            source_id, ambiguous = match_source(transaction.description, sources)
            if source_id:
                transaction.source_id = source_id
                transaction.ambiguous_sources = []
                changed += 1
            elif ambiguous != transaction.ambiguous_sources:
                transaction.ambiguous_sources = ambiguous
                changed += 1
        if changed:
            self.store.save_transactions()
        return {"changed": changed, "transactions": [t.to_dict() for t in self._sorted_transactions()]}
