"""API-lagret. Vet ingenting om HTTP — tar in dictar, ger ut dictar.

Att hålla det här skiktet fritt från HTTP gör det testbart utan server, och
gör det billigt att byta ut ``server.py`` mot Flask eller FastAPI senare.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

from . import importer, mail, receipts
from .importers import ImportError_
from .importers.profiles import load_profiles
from .models import (
    MATCH_CONTAINS,
    MATCH_MODES,
    RECEIPT_TYPE_DIGITAL,
    RECEIPT_TYPE_PHYSICAL,
    MatchPattern,
    Transaction,
)
from .normalize import normalize_text, slugify
from .sources import (
    MODE_LABELS,
    compile_pattern,
    explain_match,
    match_source,
    new_source,
    suggest_pattern,
)
from .storage import Store

# Fält i settings.json som webbgränssnittet får läsa och skriva.
PUBLIC_SETTINGS = (
    "recipient_email",
    "sender_email",
    "subject_template",
    "body_template",
    "filename_template",
    "hide_not_required",
)


def _normalize_url(value) -> str:
    """En länk utan schema blir relativ och leder fel. Antag https."""
    url = str(value or "").strip()
    if not url or "://" in url or url.startswith("mailto:"):
        return url
    return "https://" + url


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class Api:
    def __init__(self, store: Store, allow_open: bool = True) -> None:
        self.store = store
        # Att öppna en fil i användarens standardprogram är rimligt när servern
        # kör på loopback, men inte om den exponerats mot nätverket.
        self.allow_open = allow_open
        # Förhandsgranskningar väntar i minnet tills de bekräftas. Startas
        # servern om innan bekräftelse får användaren ladda upp filen igen —
        # vilket är rätt, eftersom ingenting hunnit skrivas.
        self._staged: Dict[str, Dict[str, Any]] = {}

    # -- läsning ----------------------------------------------------------

    def state(self) -> Dict[str, Any]:
        return {
            "settings": {key: self.store.settings.get(key) for key in PUBLIC_SETTINGS},
            "sources": [self._source_payload(s) for s in self.store.sources()],
            "profiles": [
                {"id": profile.id, "name": profile.name, "note": profile.note}
                for profile in load_profiles(self.store.profiles_dir)
            ],
            "match_modes": [{"id": mode, "label": MODE_LABELS[mode]} for mode in MATCH_MODES],
            "paths": {
                "data": str(self.store.data_dir),
                "receipts": str(self.store.receipts_dir),
                "outbox": str(self.store.outbox_dir),
                "profiles": str(self.store.profiles_dir),
                "trash": str(self.store.trash_dir),
                "settings": str(self.store.settings_path),
            },
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
            transaction.source_manual = source_id is not None
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
            text = str(changes.get("match_pattern") or "").strip()
            if not text:
                text = suggest_pattern(transaction.description)
            mode = str(changes.get("match_pattern_mode") or MATCH_CONTAINS).strip().lower()
            if mode not in MATCH_MODES:
                raise ApiError("Okänt matchningsläge: {}".format(mode))
            source = self.store.source_by_id(transaction.source_id)
            if source is not None and text:
                # Samma text med olika läge är två olika regler, inte en dubblett.
                known = {(normalize_text(p.pattern), p.mode) for p in source.match_patterns}
                if (normalize_text(text), mode) not in known:
                    source.match_patterns.append(MatchPattern(pattern=text, mode=mode))
                    self.store.save_sources()
                    pattern_added = True

        self.store.save_transactions()

        # Ett nytt mönster gäller alla rader, inte bara den man råkade stå på.
        # Utan det här kopplar en källa skapad från den här dialogen exakt en
        # rad, medan resten av förekomsterna blir kvar okopplade.
        coupled = self._rematch() if pattern_added else 0
        return {
            "transaction": self.store.transaction_by_id(transaction_id).to_dict(),
            "applied_to_source": applied_to_source,
            "pattern_added": pattern_added,
            "coupled": coupled,
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
                transaction.source_manual = source_id is not None
            transaction.refresh_status()
            updated.append(transaction.to_dict())
        if updated:
            self.store.save_transactions()
        return {"updated": updated}

    # -- verifikat --------------------------------------------------------

    def upload_receipt(self, transaction_id: str, filename: str, data: bytes) -> Dict[str, Any]:
        transaction = self.store.transaction_by_id(transaction_id)
        if transaction is None:
            raise ApiError("Transaktionen finns inte.", status=404)
        if transaction.receipt is not None:
            # Ett verifikat per rad i version 1 (§7.3). Att tyst skriva över
            # ett befintligt vore lätt att göra av misstag — särskilt när man
            # drar en fil på fel rad.
            raise ApiError(
                "Raden har redan verifikatet {}. Ta bort det först om du vill "
                "byta.".format(transaction.receipt.stored_filename)
            )
        try:
            receipt = receipts.store_receipt(self.store, transaction, filename, data)
        except receipts.ReceiptError as error:
            raise ApiError(str(error))
        self.store.save_transactions()
        return {"transaction": transaction.to_dict(), "receipt": receipt.to_dict()}

    def delete_receipt(self, transaction_id: str) -> Dict[str, Any]:
        transaction = self.store.transaction_by_id(transaction_id)
        if transaction is None:
            raise ApiError("Transaktionen finns inte.", status=404)
        if transaction.receipt is None:
            raise ApiError("Raden har inget verifikat.")
        moved = receipts.remove_receipt(self.store, transaction)
        self.store.save_transactions()
        return {"transaction": transaction.to_dict(), "trashed": str(moved) if moved else None}

    def receipt_file(self, transaction_id: str) -> Tuple[bytes, str, str]:
        """Returnerar ``(innehåll, mimetyp, filnamn)`` för visning i webbläsaren."""
        transaction = self.store.transaction_by_id(transaction_id)
        if transaction is None:
            raise ApiError("Transaktionen finns inte.", status=404)
        try:
            path, mimetype = receipts.receipt_file(self.store, transaction)
        except receipts.ReceiptError as error:
            raise ApiError(str(error), status=404)
        return path.read_bytes(), mimetype, transaction.receipt.stored_filename

    # -- utskick ----------------------------------------------------------

    def email_preview(self, transaction_id: str) -> Dict[str, Any]:
        transaction = self._require(transaction_id)
        try:
            details = mail.preview(self.store, transaction)
        except mail.MailError as error:
            raise ApiError(str(error))
        details["can_send"] = bool(transaction.receipt) and not details["missing"]
        details["sent_at"] = transaction.sent_at
        return details

    def create_email(self, transaction_id: str) -> Dict[str, Any]:
        """Skriv .eml-filen och öppna den i mejlklienten.

        Raden markeras *inte* som skickad här. Verktyget kan inte veta om
        mejlet faktiskt gick iväg — det bekräftar användaren själv (§8.3).
        """
        transaction = self._require(transaction_id)
        try:
            path = mail.write_eml(self.store, transaction)
        except mail.MailError as error:
            raise ApiError(str(error))

        if not self.allow_open:
            return {
                "path": str(path),
                "opened": False,
                "message": "Servern lyssnar inte på localhost, så filen öppnades inte "
                           "automatiskt. Den ligger på {}.".format(path),
            }
        opened, message = mail.open_file(path)
        return {"path": str(path), "opened": opened, "message": message}

    def mark_sent(self, transaction_id: str) -> Dict[str, Any]:
        transaction = self._require(transaction_id)
        if transaction.receipt is None:
            raise ApiError("Raden har inget verifikat och kan inte vara skickad.")
        mail.mark_sent(transaction)
        self.store.save_transactions()
        return {"transaction": transaction.to_dict()}

    def unmark_sent(self, transaction_id: str) -> Dict[str, Any]:
        transaction = self._require(transaction_id)
        mail.unmark_sent(transaction)
        self.store.save_transactions()
        return {"transaction": transaction.to_dict()}

    def _require(self, transaction_id: str) -> Transaction:
        transaction = self.store.transaction_by_id(transaction_id)
        if transaction is None:
            raise ApiError("Transaktionen finns inte.", status=404)
        return transaction

    # -- inställningar ----------------------------------------------------

    def update_settings(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Skriv de inställningar gränssnittet får röra."""
        changes: Dict[str, Any] = {}
        for field in ("recipient_email", "sender_email"):
            if field in data:
                value = str(data[field] or "").strip()
                if value and "@" not in value:
                    raise ApiError("{} ser inte ut som en mejladress.".format(value))
                changes[field] = value
        for field in ("subject_template", "body_template", "filename_template"):
            if field in data:
                changes[field] = str(data[field] or "").strip()
        if "hide_not_required" in data:
            changes["hide_not_required"] = bool(data["hide_not_required"])

        self.store.save_settings(changes)
        return {"settings": {key: self.store.settings.get(key) for key in PUBLIC_SETTINGS}}

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
            match_patterns=self._clean_patterns(data.get("match_patterns") or []),
            filename_tag=data.get("filename_tag"),
            note=data.get("note"),
        )
        sources = self.store.sources()
        sources.append(source)
        self.store.save_sources(sources)
        # En regel som inte kopplar några rader är bara en text. Matchningen
        # körs direkt i stället för att vänta på nästa import.
        coupled = self._rematch()
        return {"source": self._source_payload(source), "coupled": coupled}

    def test_pattern(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Prova ett mönster mot en rad och mot hela listan.

        Att välja mellan "innehåller" och "börjar med" är svårt att göra
        blint. Den här visar utfallet innan mönstret sparas.
        """
        mode = str(data.get("mode") or MATCH_CONTAINS).strip().lower()
        if mode not in MATCH_MODES:
            raise ApiError("Okänt matchningsläge: {}".format(mode))
        regex = compile_pattern(str(data.get("pattern") or ""), mode)
        description = str(data.get("description") or "")

        if regex is None:
            return {"matches": False, "total": 0, "samples": [], "normalized": normalize_text(description)}

        hits = [t for t in self.store.transactions() if regex.search(normalize_text(t.description))]
        return {
            "matches": bool(regex.search(normalize_text(description))),
            "total": len(hits),
            "samples": [t.description for t in hits[:5]],
            "normalized": normalize_text(description),
        }

    def update_source(self, source_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        source = self.store.source_by_id(source_id)
        if source is None:
            raise ApiError("Källan finns inte.", status=404)

        if "name" in data:
            name = str(data["name"] or "").strip()
            if not name:
                raise ApiError("Källan behöver ett namn.")
            source.name = name
        for field in ("company", "note"):
            if field in data:
                setattr(source, field, str(data[field] or "").strip())
        for field in ("receipt_url", "settings_url"):
            if field in data:
                setattr(source, field, _normalize_url(data[field]))
        if "receipt_type" in data:
            receipt_type = str(data["receipt_type"] or "").strip().lower()
            if receipt_type not in (RECEIPT_TYPE_DIGITAL, RECEIPT_TYPE_PHYSICAL):
                raise ApiError("Okänd verifikattyp: {}".format(receipt_type))
            source.receipt_type = receipt_type
        for flag in ("requires_receipt", "auto_send_configured"):
            if flag in data:
                setattr(source, flag, bool(data[flag]))
        if "filename_tag" in data:
            source.filename_tag = slugify(data["filename_tag"]) or slugify(source.name)
        if "match_patterns" in data:
            source.match_patterns = self._clean_patterns(data["match_patterns"])

        self.store.save_sources()
        coupled = self._rematch()
        return {"source": self._source_payload(source), "coupled": coupled}

    def delete_source(self, source_id: str) -> Dict[str, Any]:
        """Ta bort en källa och koppla loss raderna som pekade på den.

        Transaktionerna finns kvar — bara kopplingen försvinner. Att radera
        en källa får aldrig innebära att en rad försvinner ur avstämningen.
        """
        source = self.store.source_by_id(source_id)
        if source is None:
            raise ApiError("Källan finns inte.", status=404)

        uncoupled = 0
        for transaction in self.store.transactions():
            if transaction.source_id == source_id:
                transaction.source_id = None
                transaction.ambiguous_sources = []
                transaction.source_manual = False
                uncoupled += 1
        if uncoupled:
            self.store.save_transactions()

        self.store.save_sources([s for s in self.store.sources() if s.id != source_id])
        return {"deleted": source_id, "uncoupled": uncoupled}

    def _clean_patterns(self, values) -> List[MatchPattern]:
        if not isinstance(values, list):
            raise ApiError("match_patterns måste vara en lista.")
        cleaned = []
        for value in values:
            pattern = MatchPattern.from_any(value)
            if isinstance(value, dict):
                mode = str(value.get("mode") or MATCH_CONTAINS).strip().lower()
                if mode not in MATCH_MODES:
                    raise ApiError("Okänt matchningsläge: {}".format(mode))
            if pattern.pattern.strip():
                pattern.pattern = pattern.pattern.strip()
                cleaned.append(pattern)
        return cleaned

    def _source_payload(self, source) -> Dict[str, Any]:
        """Källan plus antal kopplade transaktioner (§9.3)."""
        data = source.to_dict()
        data["transaction_count"] = sum(
            1 for t in self.store.transactions() if t.source_id == source.id
        )
        return data

    def _rematch(self) -> int:
        """Kör källmatchningen på alla okopplade rader. Returnerar antalet.

        Rader som redan har en källa rörs aldrig — koppling är användarens
        beslut, och en ny källa får inte rycka rader från en befintlig.
        """
        sources = self.store.sources()
        changed = 0
        for transaction in self.store.transactions():
            if transaction.source_manual:
                continue
            source_id, ambiguous = match_source(transaction.description, sources)
            if source_id and source_id != transaction.source_id:
                transaction.source_id = source_id
                transaction.ambiguous_sources = []
                changed += 1
            elif not source_id and not transaction.source_id:
                # En koppling tas aldrig bort av matchningen. Att en regel
                # ändrats får inte tömma en rad som redan hittat hem.
                if ambiguous != transaction.ambiguous_sources:
                    transaction.ambiguous_sources = ambiguous
                    changed += 1
        if changed:
            self.store.save_transactions()
        return changed

    def rematch_sources(self) -> Dict[str, Any]:
        changed = self._rematch()
        return {
            "changed": changed,
            "transactions": [t.to_dict() for t in self._sorted_transactions()],
        }

    def explain_source_match(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Matchar den här källan redan den här texten, och i så fall hur?

        Används av kopplingsdialogen för att slippa föreslå ett mönster som
        inte behövs. En källa som redan träffar raden ska inte få ännu en
        regel bara för att man kopplar.
        """
        description = str(data.get("description") or "")
        source = self.store.source_by_id(str(data.get("source_id") or ""))
        if source is None:
            raise ApiError("Källan finns inte.", status=404)
        explanation = explain_match(description, source)
        return {
            "matches": explanation is not None,
            "explanation": explanation,
            "patterns": [p.to_json() for p in source.match_patterns],
        }
