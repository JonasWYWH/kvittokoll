"""Utskick via .eml (§8)."""

import email
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, temp_store  # noqa: F401

from kvittokoll import mail, receipts
from kvittokoll.mail import MailError
from kvittokoll.models import Source, Transaction

PDF = b"%PDF-1.4\ntrailer\n%%EOF\n"

SETTINGS = {
    "recipient_email": "inkorg@bokforing.example.se",
    "sender_email": "mig@mittforetag.se",
}


def transaction(**overrides):
    data = dict(
        id="2026-03-14|-449.00|GOOGLE WORKSPACE|1",
        date="2026-03-14",
        amount=-449.00,
        description="GOOGLE *WORKSPACE_ABC",
        account="Företagskonto 8000-0012345678",
        source_id="google-workspace",
    )
    data.update(overrides)
    return Transaction(**data)


class MailTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.store = temp_store(self.tmp, settings=dict(SETTINGS))
        self.store._sources = [
            Source(id="google-workspace", name="Google Workspace", company="Google")
        ]
        self.transaction = transaction()
        self.store._transactions = [self.transaction]

    def with_receipt(self):
        receipts.store_receipt(self.store, self.transaction, "invoice.pdf", PDF)
        return self.transaction

    # -- förhandsgranskning ------------------------------------------------

    def test_amnesrad_och_brodtext_fylls_i(self):
        details = mail.preview(self.store, self.transaction)
        self.assertEqual(details["subject"], "Verifikat 2026-03-14 Google Workspace -449.00")
        self.assertEqual(
            details["body"],
            "Verifikat för transaktion 2026-03-14, Google Workspace, -449.00 kr.",
        )

    def test_beloppet_behaller_tecknet(self):
        """En inbetalning och en utgift ska inte se likadana ut i ämnesraden."""
        incoming = transaction(id="a|1", amount=12500.0, source_id=None)
        details = mail.preview(self.store, incoming)
        self.assertIn("12500.00", details["subject"])
        self.assertNotIn("-12500.00", details["subject"])

    def test_utan_kalla_anvands_transaktionstexten(self):
        loose = transaction(id="b|1", source_id=None)
        self.assertIn("GOOGLE *WORKSPACE_ABC", mail.preview(self.store, loose)["subject"])

    def test_mallarna_kan_bytas(self):
        self.store.settings["subject_template"] = "{company} {date} ({account})"
        details = mail.preview(self.store, self.transaction)
        self.assertEqual(
            details["subject"], "Google 2026-03-14 (Företagskonto 8000-0012345678)"
        )

    def test_okand_platshallare_ger_begripligt_fel(self):
        self.store.settings["subject_template"] = "{datum}"
        with self.assertRaises(MailError) as caught:
            mail.preview(self.store, self.transaction)
        self.assertIn("{date}", str(caught.exception))

    def test_saknade_adresser_listas(self):
        self.store.settings["recipient_email"] = ""
        missing = mail.preview(self.store, self.transaction)["missing"]
        self.assertIn("recipient_email", missing)
        self.assertNotIn("sender_email", missing)

    # -- mejlet -------------------------------------------------------------

    def test_utan_verifikat_gar_det_inte_att_skicka(self):
        with self.assertRaises(MailError) as caught:
            mail.build_message(self.store, self.transaction)
        self.assertIn("inget verifikat", str(caught.exception))

    def test_utan_mottagaradress_gar_det_inte_att_skicka(self):
        self.with_receipt()
        self.store.settings["recipient_email"] = ""
        with self.assertRaises(MailError):
            mail.build_message(self.store, self.transaction)

    def test_eml_filen_ar_ett_lasbart_mejl_med_bilagan(self):
        self.with_receipt()
        path = mail.write_eml(self.store, self.transaction)
        self.assertTrue(path.is_file())
        self.assertEqual(path.suffix, ".eml")

        message = email.message_from_bytes(path.read_bytes())
        self.assertEqual(message["To"], SETTINGS["recipient_email"])
        self.assertEqual(message["From"], SETTINGS["sender_email"])
        self.assertEqual(message["Subject"], "Verifikat 2026-03-14 Google Workspace -449.00")
        self.assertTrue(message["Date"])

        attachments = [
            part for part in message.walk() if part.get_filename()
        ]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].get_filename(), "2026-03-14_449.00_google-workspace.pdf")
        self.assertEqual(attachments[0].get_content_type(), "application/pdf")
        self.assertEqual(attachments[0].get_payload(decode=True), PDF)

    def test_utan_avsandare_utelamnas_from_huvudet(self):
        """Avsändaren är valfri — mejlet skickas ändå från kontot i
        mejlklienten. Ett tomt From-huvud vore värre än inget."""
        self.with_receipt()
        self.store.settings["sender_email"] = ""
        message = email.message_from_bytes(
            mail.write_eml(self.store, self.transaction).read_bytes()
        )
        self.assertIsNone(message["From"])
        self.assertEqual(message["To"], SETTINGS["recipient_email"])
        attachments = [p for p in message.walk() if p.get_filename()]
        self.assertEqual(len(attachments), 1)

    def test_utan_avsandare_gar_det_fortfarande_att_skicka(self):
        self.with_receipt()
        self.store.settings["sender_email"] = ""
        self.assertEqual(mail.preview(self.store, self.transaction)["missing"], {})

    def test_brodtexten_finns_i_mejlet(self):
        self.with_receipt()
        message = email.message_from_bytes(
            mail.write_eml(self.store, self.transaction).read_bytes()
        )
        body = [p for p in message.walk() if p.get_content_type() == "text/plain"][0]
        self.assertIn("Verifikat för transaktion 2026-03-14", body.get_payload(decode=True).decode("utf-8"))

    def test_eml_hamnar_i_outbox_och_krockar_inte(self):
        self.with_receipt()
        first = mail.write_eml(self.store, self.transaction)
        second = mail.write_eml(self.store, self.transaction)
        self.assertEqual(first.parent, self.store.outbox_dir)
        self.assertNotEqual(first, second)
        self.assertTrue(second.name.endswith("-2.eml"))

    def test_verifikat_som_forsvunnit_fran_disk_ger_begripligt_fel(self):
        receipt = self.with_receipt().receipt
        receipts.resolve_path(self.store, receipt.stored_path).unlink()
        with self.assertRaises(MailError) as caught:
            mail.build_message(self.store, self.transaction)
        self.assertIn("saknas", str(caught.exception))

    # -- markering ----------------------------------------------------------

    def test_markera_som_skickad(self):
        self.with_receipt()
        stamp = mail.mark_sent(self.transaction)
        self.assertEqual(self.transaction.sent_at, stamp)
        self.assertEqual(self.transaction.status, "sent")

    def test_angra_skickat(self):
        self.with_receipt()
        mail.mark_sent(self.transaction)
        mail.unmark_sent(self.transaction)
        self.assertIsNone(self.transaction.sent_at)
        self.assertEqual(self.transaction.status, "has_receipt")


if __name__ == "__main__":
    unittest.main()
