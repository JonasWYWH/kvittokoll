"""Uppladdning, namngivning och borttagning av verifikat (§7).

Filen kopieras in i verktygets katalog under ``receipts/ÅÅÅÅ-MM/`` så att den
överlever att nedladdningsmappen töms. Originalfilen lämnas orörd, och
originalnamnet sparas så att ingenting går förlorat.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Dict, Optional, Tuple

from .models import Receipt, Source, Transaction
from .normalize import format_amount, now_iso, slugify
from .storage import Store, _fsync_dir

# Vad som accepteras (§7.1), och vilken MIME-typ filen får när den serveras
# eller bifogas ett mejl.
ALLOWED_TYPES: Dict[str, str] = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "png": "image/png",
    "heic": "image/heic",
}

# Skrivsätt som betyder samma sak.
EXTENSION_ALIASES = {"jpeg": "jpg", "jpe": "jpg", "heif": "heic"}

_HEIC_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevm", b"hevs", b"mif1", b"msf1"}
_SEPARATOR_RUN = re.compile(r"([_-])[_-]+")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

MAX_RECEIPT_BYTES = 32 * 1024 * 1024


class ReceiptError(ValueError):
    """Uppladdningen kunde inte genomföras. Meddelandet visas för användaren."""


def extension_of(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    return EXTENSION_ALIASES.get(suffix, suffix)


def sniff(data: bytes) -> Optional[str]:
    """Gissa filtypen från innehållet, inte från filändelsen."""
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in _HEIC_BRANDS:
        return "heic"
    return None


def validate(filename: str, data: bytes) -> str:
    """Kontrollera filen och returnera dess filändelse.

    Innehållet kontrolleras, inte bara filändelsen. Det vanligaste
    misslyckandet när man hämtar verifikat bakom inloggning är att man inte
    var inloggad och fick en HTML-sida som heter ``faktura.pdf``. Den ska
    fångas här och inte upptäckas av bokföraren en månad senare.
    """
    if not data:
        raise ReceiptError("Filen är tom.")
    if len(data) > MAX_RECEIPT_BYTES:
        raise ReceiptError("Filen är större än 32 MB.")

    extension = extension_of(filename)
    if extension not in ALLOWED_TYPES:
        raise ReceiptError(
            "Filtypen {} stöds inte. Ladda upp PDF, JPG, PNG eller HEIC.".format(
                "." + extension if extension else "(okänd)"
            )
        )

    actual = sniff(data)
    if actual is None:
        head = data[:512].lstrip()[:15].lower()
        if head.startswith(b"<!doctype") or head.startswith(b"<html"):
            raise ReceiptError(
                "Filen är en webbsida, inte ett verifikat. Troligen laddades en "
                "inloggningssida ner istället för fakturan — logga in hos "
                "leverantören och hämta filen igen."
            )
        raise ReceiptError("Filen ser inte ut att vara en PDF eller en bild.")
    if actual != extension:
        raise ReceiptError(
            "Filen heter .{} men innehåller {}. Byt filändelse eller ladda upp rätt fil.".format(
                extension, actual.upper()
            )
        )
    return extension


def build_stem(
    transaction: Transaction, source: Optional[Source], template: str
) -> str:
    """Bygg filnamnet utan filändelse enligt mallen (§7.2)."""
    tag = (source.filename_tag if source else "") or slugify(transaction.description, 40)
    values = {
        "date": transaction.date,
        # Absolutbelopp: minustecken fungerar dåligt i filnamn på vissa system.
        "amount": format_amount(abs(transaction.amount)),
        "tag": tag or "verifikat",
        "company": slugify(source.company, 40) if source and source.company else "",
        "account": slugify(transaction.account, 40),
    }
    try:
        stem = template.format(**values)
    except (KeyError, IndexError) as error:
        raise ReceiptError(
            "Filnamnsmallen känner inte igen {}. Tillåtna platshållare: "
            "{{date}}, {{amount}}, {{tag}}, {{company}}, {{account}}.".format(error)
        )
    return sanitize_stem(stem) or "verifikat"


def sanitize_stem(stem: str) -> str:
    """Gör strängen säker som filnamn.

    Tar bort sökvägstecken, och drar ihop de dubbla avgränsare som uppstår
    när en platshållare är tom — ``{date}_{company}_{tag}`` utan bolag ska
    inte ge ``2026-08-11__google``.
    """
    cleaned = _UNSAFE.sub("-", stem.replace("/", "-").replace("\\", "-"))
    cleaned = _SEPARATOR_RUN.sub(r"\1", cleaned)
    return cleaned.strip("._-")


def target_path(store: Store, transaction: Transaction, stem: str, extension: str) -> Path:
    """Ledig sökväg under receipts/ÅÅÅÅ-MM/. Vid krock läggs -2, -3 till."""
    directory = store.receipts_dir / transaction.date[:7]
    candidate = directory / "{}.{}".format(stem, extension)
    counter = 2
    while candidate.exists():
        candidate = directory / "{}-{}.{}".format(stem, counter, extension)
        counter += 1
    return candidate


def relative_path(store: Store, path: Path) -> str:
    """Sökvägen som den lagras i JSON — relativ till data_dir när det går."""
    try:
        return path.relative_to(store.data_dir).as_posix()
    except ValueError:
        return path.as_posix()


def resolve_path(store: Store, stored_path: str) -> Path:
    path = Path(stored_path)
    return path if path.is_absolute() else (store.data_dir / path)


def store_receipt(
    store: Store, transaction: Transaction, filename: str, data: bytes
) -> Receipt:
    """Kopiera in filen, döp om den och koppla den till transaktionen."""
    extension = validate(filename, data)
    source = store.source_by_id(transaction.source_id) if transaction.source_id else None
    template = store.settings.get("filename_template") or "{date}_{amount}_{tag}"

    stem = build_stem(transaction, source, template)
    target = target_path(store, transaction, stem, extension)
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(target, data)

    receipt = Receipt(
        original_filename=Path(filename).name,
        stored_filename=target.name,
        stored_path=relative_path(store, target),
        uploaded_at=now_iso(),
    )
    transaction.receipt = receipt
    transaction.refresh_status()
    return receipt


def remove_receipt(store: Store, transaction: Transaction) -> Optional[Path]:
    """Nollställ raden till missing. Filen flyttas till papperskorgen (§9.2)."""
    if transaction.receipt is None:
        return None
    moved = store.move_to_trash(resolve_path(store, transaction.receipt.stored_path))
    transaction.receipt = None
    transaction.sent_at = None
    transaction.refresh_status()
    return moved


def receipt_file(store: Store, transaction: Transaction) -> Tuple[Path, str]:
    """Sökväg och MIME-typ för ett uppladdat verifikat."""
    if transaction.receipt is None:
        raise ReceiptError("Raden har inget verifikat.")
    path = resolve_path(store, transaction.receipt.stored_path)
    if not path.is_file():
        raise ReceiptError(
            "Verifikatfilen saknas på disk: {}".format(transaction.receipt.stored_path)
        )
    extension = extension_of(path.name)
    return path, ALLOWED_TYPES.get(extension, "application/octet-stream")


def _write_atomic(path: Path, data: bytes) -> None:
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, str(path))
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)
