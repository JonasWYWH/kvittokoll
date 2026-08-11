"""Importflödet: förhandsgranska, bekräfta, skriv.

Två steg med avsikt. Först tolkas filen och användaren får se exakt vad som
kommer att hända — *X nya, Y redan kända, Z ej tolkbara, varav W automatiskt
kopplade till källa*. Först vid bekräftelse rörs disken, och då tas alltid en
backup först.

Importen är additiv. Den kan bara lägga till rader — aldrig ta bort en rad,
aldrig ändra en status, aldrig röra ett uppladdat verifikat.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .dedupe import assign_ids
from .importers import FORMAT_CAMT053, FORMAT_CSV, ImportError_, ImportResult, detect_format
from .importers import camt053, csv_import
from .importers.profiles import Profile, find_profile, load_profiles
from .models import Transaction
from .normalize import month_of, now_iso
from .sources import match_source
from .storage import Store


def parse_file(
    store: Store,
    filename: str,
    data: bytes,
    profile_id: Optional[str] = None,
    fmt: Optional[str] = None,
) -> ImportResult:
    """Tolka en uppladdad fil till råa rader."""
    fmt = fmt or detect_format(filename, data)
    if fmt == FORMAT_CAMT053:
        return camt053.parse(data)

    profiles = load_profiles(store.profiles_dir)
    if not profiles:
        raise ImportError_(
            "Ingen importprofil hittades i {}. CSV kräver en profil.".format(store.profiles_dir)
        )
    profile = find_profile(profiles, profile_id) if profile_id else None
    if profile is None:
        profile = _guess_profile(data, profiles)
    if profile is None:
        raise ImportError_(
            "Ingen av profilerna passar filens kolumner. Välj profil manuellt "
            "eller skapa en ny."
        )
    return csv_import.parse(data, profile)


def _guess_profile(data: bytes, profiles: List[Profile]) -> Optional[Profile]:
    """Välj den profil vars obligatoriska kolumner alla finns i filen."""
    for profile in profiles:
        try:
            header, _ = csv_import.read_header(data, profile)
        except ImportError_:
            continue
        if header and not profile.missing_columns(header):
            return profile
    return None


def preview(
    store: Store,
    filename: str,
    data: bytes,
    profile_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Tolka filen och beskriv vad en import skulle göra. Skriver ingenting."""
    parsed = parse_file(store, filename, data, profile_id=profile_id)

    existing = store.transactions()
    new_rows, known_rows = assign_ids(parsed.rows, [t.id for t in existing])

    sources = store.sources()
    stamp = now_iso()
    staged = []  # type: List[Dict[str, Any]]
    matched = 0
    ambiguous = 0

    for row in new_rows:
        source_id, ambiguous_ids = match_source(row["description"], sources)
        requires_receipt = True
        if source_id:
            matched += 1
            source = store.source_by_id(source_id)
            if source is not None:
                requires_receipt = source.requires_receipt
        elif ambiguous_ids:
            ambiguous += 1

        transaction = Transaction(
            id=row["id"],
            date=row["date"],
            amount=row["amount"],
            currency=row.get("currency") or "SEK",
            description=row.get("description") or "",
            transaction_type=row.get("transaction_type") or "",
            account=row.get("account") or "",
            balance=row.get("balance"),
            source_id=source_id,
            ambiguous_sources=ambiguous_ids,
            requires_receipt=requires_receipt,
            imported_at=stamp,
            import_file=filename,
        )
        staged.append(transaction.to_dict())

    months = sorted({month_of(row["date"]) for row in new_rows})
    return {
        "filename": filename,
        "format": parsed.format,
        "profile_id": parsed.profile_id,
        "encoding": parsed.encoding,
        "rows": staged,
        "errors": [error.to_dict() for error in parsed.errors],
        "summary": {
            "parsed": len(parsed.rows),
            "new": len(new_rows),
            "known": len(known_rows),
            "failed": len(parsed.errors),
            "matched": matched,
            "ambiguous": ambiguous,
            "months": months,
        },
    }


def commit(store: Store, staged: Dict[str, Any]) -> Dict[str, Any]:
    """Skriv de förhandsgranskade raderna. Tar backup först."""
    rows = staged.get("rows") or []
    existing = store.transactions()
    existing_ids = {transaction.id for transaction in existing}

    # Skyddsnät: en rad kan ha hunnit importeras via en annan flik sedan
    # förhandsgranskningen gjordes.
    to_add = [Transaction.from_dict(row) for row in rows if row["id"] not in existing_ids]

    backup = store.backup_transactions()
    if to_add:
        existing.extend(to_add)
        store.save_transactions(existing)

    return {
        "added": len(to_add),
        "skipped": len(rows) - len(to_add),
        "backup": str(backup) if backup else None,
    }
