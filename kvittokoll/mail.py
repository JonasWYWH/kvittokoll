"""Utskick via ``.eml`` (§8).

``mailto:`` kan inte bifoga filer, och SMTP kräver att användaren lägger ett
app-lösenord i en konfigfil. ``.eml`` löser båda: verktyget skriver en komplett
mejlfil till disk och öppnar den i systemets standardmejlklient med bilagan
redan på plats. Användaren trycker skicka.

Priset är att verktyget aldrig får veta om mejlet faktiskt skickades. Därför
markeras raden som skickad manuellt, i ett eget steg.
"""

from __future__ import annotations

import subprocess
import sys
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import receipts
from .models import Source, Transaction
from .normalize import format_amount, now_iso, slugify
from .storage import Store

DEFAULT_SUBJECT = "Verifikat {date} {source} {amount}"
DEFAULT_BODY = "Verifikat för transaktion {date}, {source}, {amount} kr."


class MailError(ValueError):
    """Mejlet kunde inte skapas. Meddelandet visas för användaren."""


def placeholders(transaction: Transaction, source: Optional[Source]) -> Dict[str, str]:
    return {
        "date": transaction.date,
        # Med tecken: en inbetalning och en utgift ska inte se likadana ut i
        # ämnesraden.
        "amount": format_amount(transaction.amount),
        "source": source.name if source else (transaction.description or "okänd källa"),
        "company": (source.company if source and source.company else ""),
        "account": transaction.account,
    }


def render(template: str, values: Dict[str, str], field: str) -> str:
    try:
        return template.format(**values).strip()
    except (KeyError, IndexError) as error:
        raise MailError(
            "Mallen för {} känner inte igen {}. Tillåtna platshållare: "
            "{{date}}, {{amount}}, {{source}}, {{company}}, {{account}}.".format(field, error)
        )


def missing_settings(store: Store) -> Dict[str, str]:
    """Vilka inställningar som saknas för att kunna skapa ett mejl."""
    missing = {}
    if not (store.settings.get("recipient_email") or "").strip():
        missing["recipient_email"] = "Adressen till bokföringens inkorg saknas."
    if not (store.settings.get("sender_email") or "").strip():
        missing["sender_email"] = "Din avsändaradress saknas."
    return missing


def preview(store: Store, transaction: Transaction) -> Dict[str, Any]:
    """Hur mejlet kommer att se ut. Skriver ingenting."""
    source = store.source_by_id(transaction.source_id) if transaction.source_id else None
    values = placeholders(transaction, source)
    return {
        "to": (store.settings.get("recipient_email") or "").strip(),
        "from": (store.settings.get("sender_email") or "").strip(),
        "subject": render(
            store.settings.get("subject_template") or DEFAULT_SUBJECT, values, "ämnesraden"
        ),
        "body": render(store.settings.get("body_template") or DEFAULT_BODY, values, "brödtexten"),
        "attachment": transaction.receipt.stored_filename if transaction.receipt else None,
        "missing": missing_settings(store),
    }


def build_message(store: Store, transaction: Transaction) -> EmailMessage:
    if transaction.receipt is None:
        raise MailError("Raden har inget verifikat att bifoga.")
    missing = missing_settings(store)
    if missing:
        raise MailError(" ".join(missing.values()))

    try:
        path, mimetype = receipts.receipt_file(store, transaction)
    except receipts.ReceiptError as error:
        raise MailError(str(error))

    details = preview(store, transaction)
    message = EmailMessage()
    message["To"] = details["to"]
    message["From"] = details["from"]
    message["Subject"] = details["subject"]
    message["Date"] = formatdate(localtime=True)
    message.set_content(details["body"] + "\n")

    maintype, _, subtype = mimetype.partition("/")
    message.add_attachment(
        path.read_bytes(),
        maintype=maintype or "application",
        subtype=subtype or "octet-stream",
        filename=transaction.receipt.stored_filename,
    )
    return message


def write_eml(store: Store, transaction: Transaction) -> Path:
    """Skriv mejlfilen till data/outbox/ och returnera sökvägen."""
    message = build_message(store, transaction)
    outbox = store.outbox_dir
    outbox.mkdir(parents=True, exist_ok=True)

    stem = slugify(
        "{}-{}".format(transaction.date, Path(transaction.receipt.stored_filename).stem), 80
    ) or "verifikat"
    target = outbox / "{}.eml".format(stem)
    counter = 2
    while target.exists():
        target = outbox / "{}-{}.eml".format(stem, counter)
        counter += 1

    # policy.SMTP ger CRLF, vilket är vad mejlklienter förväntar sig i en .eml.
    from email import policy

    target.write_bytes(message.as_bytes(policy=policy.SMTP))
    return target


def open_file(path: Path) -> Tuple[bool, str]:
    """Öppna filen i systemets standardprogram.

    Returnerar ``(lyckades, meddelande)``. Att det misslyckas är inte
    allvarligt — filen ligger kvar på disk och kan öppnas för hand.
    """
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=True)
        elif sys.platform.startswith("win"):
            import os

            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(path)], check=True)
    except Exception as error:
        return False, "Kunde inte öppna mejlklienten ({}). Filen ligger kvar: {}".format(
            error, path
        )
    return True, "Mejlet öppnades i din mejlklient."


def mark_sent(transaction: Transaction, when: Optional[str] = None) -> str:
    """§8.3 — användaren bekräftar själv att mejlet gick iväg."""
    transaction.sent_at = when or now_iso()
    transaction.refresh_status()
    return transaction.sent_at


def unmark_sent(transaction: Transaction) -> None:
    transaction.sent_at = None
    transaction.refresh_status()
