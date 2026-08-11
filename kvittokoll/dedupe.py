"""Dubblettlogik.

Bankexporter saknar oftast stabilt transaktions-ID. Swedbanks ``Radnr`` är
till exempel bara radens plats i just den exportfilen och ändras nästa gång.
Nyckeln byggs därför av innehållet:

    datum | belopp | normaliserad text | löpnummer

Löpnumret finns för att samma belopp kan dras hos samma källa två gånger samma
dag. Algoritmen räknar förekomster i den nya filen, räknar hur många som redan
finns lagrade, och importerar differensen. Två identiska köp samma dag ger
alltså två rader, medan en omimport av samma fil ger noll nya.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Sequence, Tuple

from .normalize import format_amount, normalize_text


def base_key(date: str, amount: float, description: str) -> str:
    """Dubblettnyckeln utan löpnummer."""
    return "{}|{}|{}".format(date, format_amount(amount), normalize_text(description))


def make_id(key: str, sequence: int) -> str:
    return "{}|{}".format(key, sequence)


def key_of_id(transaction_id: str) -> str:
    return transaction_id.rsplit("|", 1)[0]


def count_existing(existing_ids: Iterable[str]) -> Dict[str, int]:
    """Antal redan lagrade rader per basnyckel."""
    counts = Counter()  # type: Counter
    for transaction_id in existing_ids:
        counts[key_of_id(transaction_id)] += 1
    return dict(counts)


def assign_ids(
    rows: Sequence[dict], existing_ids: Iterable[str]
) -> Tuple[List[dict], List[dict]]:
    """Dela upp inlästa rader i nya och redan kända.

    ``rows`` är dictar från en importerare, var och en med minst ``date``,
    ``amount`` och ``description``, och valfritt ``bank_id`` när banken
    levererar ett eget unikt ID.

    Returnerar ``(nya, kända)``. De nya har fått ``id`` satt. Ordningen inom
    varje basnyckel bevaras: vid en delvis överlappande export är det de
    *sista* raderna i gruppen som räknas som nya, vilket ger stabila id:n när
    samma period exporteras om med några rader till.
    """
    existing = set(existing_ids)
    existing_counts = count_existing(existing)

    grouped = defaultdict(list)  # type: Dict[str, List[dict]]
    ordered_keys = []  # type: List[str]
    bank_id_rows = []  # type: List[dict]

    for position, original in enumerate(rows):
        row = dict(original, _order=position)
        bank_id = (row.get("bank_id") or "").strip()
        if bank_id:
            bank_id_rows.append(row)
            continue
        key = base_key(row["date"], row["amount"], row["description"])
        if key not in grouped:
            ordered_keys.append(key)
        grouped[key].append(row)

    new_rows = []  # type: List[dict]
    known_rows = []  # type: List[dict]

    # Banken levererade ett eget ID — då används det istället för nyckeln.
    seen_bank_ids = set()
    for row in bank_id_rows:
        bank_id = row["bank_id"].strip()
        if bank_id in existing or bank_id in seen_bank_ids:
            known_rows.append(dict(row, id=bank_id))
            continue
        seen_bank_ids.add(bank_id)
        new_rows.append(dict(row, id=bank_id))

    for key in ordered_keys:
        group = grouped[key]
        already = existing_counts.get(key, 0)
        for index, row in enumerate(group, start=1):
            if index <= already:
                known_rows.append(dict(row, id=make_id(key, index)))
            else:
                new_rows.append(dict(row, id=make_id(key, index)))

    # Behåll filens läsordning i utdata.
    new_rows.sort(key=lambda r: r["_order"])
    known_rows.sort(key=lambda r: r["_order"])
    for row in new_rows + known_rows:
        row.pop("_order", None)
    return new_rows, known_rows
