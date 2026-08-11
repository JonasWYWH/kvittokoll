"""Datamodellen: transaktion, verifikat, underlagskälla.

Modellerna är tunna omslag runt JSON. ``from_dict`` är avsiktligt förlåtande —
en fil som skrivits av en äldre version ska gå att läsa — medan ``to_dict``
alltid skriver fullständiga poster.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .normalize import normalize_text, slugify

STATUS_MISSING = "missing"
STATUS_HAS_RECEIPT = "has_receipt"
STATUS_SENT = "sent"
STATUS_NOT_REQUIRED = "not_required"

RECEIPT_TYPE_DIGITAL = "digital"
RECEIPT_TYPE_PHYSICAL = "physical"

MATCH_CONTAINS = "contains"
MATCH_STARTS_WITH = "starts_with"
MATCH_ENDS_WITH = "ends_with"
MATCH_MODES = (MATCH_CONTAINS, MATCH_STARTS_WITH, MATCH_ENDS_WITH)


def _as_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "ja", "yes", "on")
    return bool(value)


def _as_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class MatchPattern:
    """Ett matchningsmönster med läge.

    ``contains`` räcker för de flesta handlare, men inte för texter som
    "HYRA KONTORSGATAN 5" — där vill man fånga allt som *börjar* med HYRA
    utan att samtidigt dra in "SLUTHYRA" eller "BILHYRA".
    """

    pattern: str
    mode: str = MATCH_CONTAINS

    @classmethod
    def from_any(cls, value) -> "MatchPattern":
        """Läser både den korta strängformen och objektformen."""
        if isinstance(value, MatchPattern):
            return value
        if isinstance(value, dict):
            mode = str(value.get("mode") or MATCH_CONTAINS).strip().lower()
            return cls(
                pattern=str(value.get("pattern") or ""),
                mode=mode if mode in MATCH_MODES else MATCH_CONTAINS,
            )
        return cls(pattern=str(value or ""))

    def to_json(self):
        """Sträng när läget är contains, objekt annars.

        Håller sources.json läsbar och handredigerbar i normalfallet, och
        gör att filer skrivna före lägena fortfarande går att läsa.
        """
        if self.mode == MATCH_CONTAINS:
            return self.pattern
        return {"pattern": self.pattern, "mode": self.mode}


@dataclass
class Receipt:
    """Ett uppladdat verifikat. Filen ligger under receipts_dir."""

    original_filename: str = ""
    stored_filename: str = ""
    stored_path: str = ""
    uploaded_at: str = ""

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["Receipt"]:
        if not data:
            return None
        return cls(
            original_filename=data.get("original_filename") or "",
            stored_filename=data.get("stored_filename") or "",
            stored_path=data.get("stored_path") or "",
            uploaded_at=data.get("uploaded_at") or "",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_filename": self.original_filename,
            "stored_filename": self.stored_filename,
            "stored_path": self.stored_path,
            "uploaded_at": self.uploaded_at,
        }


@dataclass
class Transaction:
    id: str
    date: str
    amount: float
    currency: str = "SEK"
    description: str = ""
    transaction_type: str = ""
    account: str = ""
    balance: Optional[float] = None
    source_id: Optional[str] = None
    # Sätts när flera källor matchar lika starkt. Raden kopplas då inte
    # automatiskt utan väntar på manuell koppling (§4.3).
    ambiguous_sources: List[str] = field(default_factory=list)
    requires_receipt: bool = True
    receipt: Optional[Receipt] = None
    sent_at: Optional[str] = None
    status: str = STATUS_MISSING
    note: str = ""
    imported_at: str = ""
    import_file: str = ""

    @property
    def base_key(self) -> str:
        """Dubblettnyckeln utan löpnummer."""
        return self.id.rsplit("|", 1)[0]

    def compute_status(self) -> str:
        if not self.requires_receipt:
            return STATUS_NOT_REQUIRED
        if self.sent_at:
            return STATUS_SENT
        if self.receipt:
            return STATUS_HAS_RECEIPT
        return STATUS_MISSING

    def refresh_status(self) -> str:
        self.status = self.compute_status()
        return self.status

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Transaction":
        transaction = cls(
            id=data["id"],
            date=data["date"],
            amount=float(data["amount"]),
            currency=data.get("currency") or "SEK",
            description=data.get("description") or "",
            transaction_type=data.get("transaction_type") or "",
            account=data.get("account") or "",
            balance=_as_float(data.get("balance")),
            source_id=data.get("source_id") or None,
            ambiguous_sources=list(data.get("ambiguous_sources") or []),
            requires_receipt=_as_bool(data.get("requires_receipt"), True),
            receipt=Receipt.from_dict(data.get("receipt")),
            sent_at=data.get("sent_at") or None,
            note=data.get("note") or "",
            imported_at=data.get("imported_at") or "",
            import_file=data.get("import_file") or "",
        )
        transaction.refresh_status()
        return transaction

    def to_dict(self) -> Dict[str, Any]:
        self.refresh_status()
        return {
            "id": self.id,
            "date": self.date,
            "amount": self.amount,
            "currency": self.currency,
            "description": self.description,
            "transaction_type": self.transaction_type,
            "account": self.account,
            "balance": self.balance,
            "source_id": self.source_id,
            "ambiguous_sources": self.ambiguous_sources,
            "requires_receipt": self.requires_receipt,
            "receipt": self.receipt.to_dict() if self.receipt else None,
            "sent_at": self.sent_at,
            "status": self.status,
            "note": self.note,
            "imported_at": self.imported_at,
            "import_file": self.import_file,
        }


@dataclass
class Source:
    """En underlagskälla — en specifik tjänst, inte ett bolag (§4.1)."""

    id: str
    name: str
    company: str = ""
    receipt_url: str = ""
    settings_url: str = ""
    receipt_type: str = RECEIPT_TYPE_DIGITAL
    requires_receipt: bool = True
    auto_send_configured: bool = False
    match_patterns: List[str] = field(default_factory=list)
    filename_tag: str = ""
    note: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.filename_tag:
            self.filename_tag = slugify(self.name)
        # Mönstren får komma in som strängar, dictar eller MatchPattern —
        # inuti Source är de alltid MatchPattern.
        self.match_patterns = [MatchPattern.from_any(p) for p in self.match_patterns]

    def pattern_texts(self) -> List[str]:
        """Bara mönstertexterna, normaliserade. Används för dubblettkoll."""
        return [normalize_text(p.pattern) for p in self.match_patterns if p.pattern]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Source":
        return cls(
            id=data["id"],
            name=data.get("name") or data["id"],
            company=data.get("company") or "",
            receipt_url=data.get("receipt_url") or "",
            settings_url=data.get("settings_url") or "",
            receipt_type=data.get("receipt_type") or RECEIPT_TYPE_DIGITAL,
            requires_receipt=_as_bool(data.get("requires_receipt"), True),
            auto_send_configured=_as_bool(data.get("auto_send_configured"), False),
            match_patterns=[
                MatchPattern.from_any(p) for p in (data.get("match_patterns") or [])
            ],
            filename_tag=data.get("filename_tag") or "",
            note=data.get("note") or "",
            created_at=data.get("created_at") or "",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "company": self.company,
            "receipt_url": self.receipt_url,
            "settings_url": self.settings_url,
            "receipt_type": self.receipt_type,
            "requires_receipt": self.requires_receipt,
            "auto_send_configured": self.auto_send_configured,
            "match_patterns": [p.to_json() for p in self.match_patterns],
            "filename_tag": self.filename_tag,
            "note": self.note,
            "created_at": self.created_at,
        }
