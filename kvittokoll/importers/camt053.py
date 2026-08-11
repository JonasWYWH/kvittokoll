"""ISO 20022 camt.053 — kontoutdrag i XML.

Standardiserat och därför profilfritt. Namnrymden varierar mellan versioner
(``camt.053.001.02`` … ``.08``) så all elementmatchning görs på lokalnamn.

Referenstexten hämtas i tur och ordning från ``RmtInf/Ustrd``,
``AddtlNtryInf`` och motpartens namn, beroende på vad banken faktiskt fyller i.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from typing import Any, Dict, List, Optional

from ..normalize import ParseError, parse_date
from . import FORMAT_CAMT053, ImportError_, ImportResult, RowError


def _tag(element) -> str:
    """Lokalnamnet, utan namnrymd."""
    tag = element.tag
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _find(element, *path) -> Optional[Any]:
    current = element
    for name in path:
        found = None
        for child in list(current):
            if _tag(child) == name:
                found = child
                break
        if found is None:
            return None
        current = found
    return current


def _text(element, *path) -> str:
    found = _find(element, *path) if path else element
    if found is None or found.text is None:
        return ""
    return found.text.strip()


def _iter(element, name):
    for child in element.iter():
        if _tag(child) == name:
            yield child


def parse(data: bytes) -> ImportResult:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise ImportError_("Filen är inte giltig XML: {}".format(error))

    statements = list(_iter(root, "Stmt"))
    if not statements:
        raise ImportError_(
            "Ingen <Stmt> hittades. Filen ser inte ut som ett camt.053-kontoutdrag."
        )

    result = ImportResult(format=FORMAT_CAMT053, encoding="utf-8")
    entry_number = 0

    for statement in statements:
        account = _account_label(statement)
        for entry in _iter(statement, "Ntry"):
            entry_number += 1
            try:
                result.rows.append(_build_row(entry, account))
            except ParseError as error:
                result.errors.append(
                    RowError(line=entry_number, reason=str(error), raw=_preview(entry))
                )
            except Exception as error:
                result.errors.append(
                    RowError(
                        line=entry_number,
                        reason="oväntat fel: {}".format(error),
                        raw=_preview(entry),
                    )
                )
    return result


def _account_label(statement) -> str:
    account = _find(statement, "Acct")
    if account is None:
        return ""
    iban = _text(account, "Id", "IBAN")
    if iban:
        return iban
    other = _text(account, "Id", "Othr", "Id")
    name = _text(account, "Nm")
    parts = [part for part in (name, other) if part]
    return " ".join(parts)


def _build_row(entry, account: str) -> Dict[str, Any]:
    amount_element = _find(entry, "Amt")
    if amount_element is None or not (amount_element.text or "").strip():
        raise ParseError("belopp saknas i posten")
    try:
        amount = float(amount_element.text.strip().replace(",", "."))
    except ValueError:
        raise ParseError("otolkbart belopp: {!r}".format(amount_element.text))
    currency = (amount_element.get("Ccy") or "SEK").upper()

    indicator = _text(entry, "CdtDbtInd").upper()
    if indicator == "DBIT":
        amount = -abs(amount)
    elif indicator == "CRDT":
        amount = abs(amount)
    else:
        raise ParseError("CdtDbtInd saknas — vet inte om posten är in eller ut")

    booking_date = _text(entry, "BookgDt", "Dt") or _text(entry, "BookgDt", "DtTm")
    if not booking_date:
        booking_date = _text(entry, "ValDt", "Dt") or _text(entry, "ValDt", "DtTm")
    date = parse_date(booking_date[:10] if booking_date else "")

    return {
        "date": date,
        "amount": amount,
        "currency": currency,
        "description": _description(entry),
        "transaction_type": _text(entry, "BkTxCd", "Prtry", "Cd"),
        "account": account,
        "balance": None,  # camt.053 anger saldo per utdrag, inte per post
        "bank_id": _text(entry, "AcctSvcrRef"),
    }


def _description(entry) -> str:
    """Referenstext i den ordning banker brukar fylla i den."""
    unstructured = [
        (element.text or "").strip()
        for element in _iter(entry, "Ustrd")
        if (element.text or "").strip()
    ]
    if unstructured:
        return " ".join(unstructured)

    additional = _text(entry, "AddtlNtryInf")
    if additional:
        return additional

    parties = _find(entry, "NtryDtls", "TxDtls", "RltdPties")
    if parties is not None:
        for role in ("Cdtr", "Dbtr"):
            party = _find(parties, role)
            if party is not None:
                name = _text(party, "Nm") or _text(party, "Pty", "Nm")
                if name:
                    return name

    reference = _find(entry, "NtryDtls", "TxDtls", "Refs")
    if reference is not None:
        for name in ("EndToEndId", "InstrId", "TxId"):
            value = _text(reference, name)
            if value and value.upper() != "NOTPROVIDED":
                return value
    return ""


def _preview(entry, limit: int = 160) -> str:
    parts = []  # type: List[str]
    for child in entry.iter():
        text = (child.text or "").strip()
        if text:
            parts.append("{}={}".format(_tag(child), text))
    return " ".join(parts)[:limit]
