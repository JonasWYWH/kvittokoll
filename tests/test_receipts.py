"""Uppladdning, namngivning och borttagning av verifikat (§7)."""

import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, temp_store  # noqa: F401

from kvittokoll import receipts
from kvittokoll.models import Source, Transaction
from kvittokoll.receipts import ReceiptError

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 40
HTML = b"<!DOCTYPE html>\n<html><body>Logga in</body></html>"


def transaction(**overrides):
    data = dict(
        id="2026-03-14|-449.00|GOOGLE WORKSPACE|1",
        date="2026-03-14",
        amount=-449.00,
        description="GOOGLE *WORKSPACE_ABC",
        account="Företagskonto 8000-0012345678",
    )
    data.update(overrides)
    return Transaction(**data)


class ValidateTest(unittest.TestCase):
    def test_tillatna_typer(self):
        self.assertEqual(receipts.validate("faktura.pdf", PDF), "pdf")
        self.assertEqual(receipts.validate("kvitto.png", PNG), "png")
        self.assertEqual(receipts.validate("kvitto.jpg", JPG), "jpg")
        self.assertEqual(receipts.validate("kvitto.heic", HEIC), "heic")

    def test_jpeg_och_heif_ar_samma_sak(self):
        self.assertEqual(receipts.validate("kvitto.JPEG", JPG), "jpg")
        self.assertEqual(receipts.validate("kvitto.heif", HEIC), "heic")

    def test_inloggningssida_som_pdf_fangas(self):
        """Det vanligaste misslyckandet: man var inte inloggad och fick en
        HTML-sida som heter faktura.pdf."""
        with self.assertRaises(ReceiptError) as caught:
            receipts.validate("faktura.pdf", HTML)
        self.assertIn("webbsida", str(caught.exception))

    def test_fel_filandelse_mot_innehall(self):
        with self.assertRaises(ReceiptError) as caught:
            receipts.validate("kvitto.png", PDF)
        self.assertIn("PDF", str(caught.exception))

    def test_ostodd_filtyp(self):
        with self.assertRaises(ReceiptError) as caught:
            receipts.validate("kvitto.docx", PDF)
        self.assertIn("stöds inte", str(caught.exception))

    def test_tom_fil(self):
        with self.assertRaises(ReceiptError):
            receipts.validate("kvitto.pdf", b"")


class FilenameTest(unittest.TestCase):
    def setUp(self):
        self.source = Source(
            id="google-workspace",
            name="Google Workspace",
            company="Google",
            filename_tag="google-workspace",
        )

    def test_standardmallen(self):
        stem = receipts.build_stem(transaction(), self.source, "{date}_{amount}_{tag}")
        self.assertEqual(stem, "2026-03-14_449-00_google-workspace")

    def test_beloppet_ar_absolut_utan_minustecken(self):
        stem = receipts.build_stem(transaction(amount=-1256.09), self.source, "{amount}")
        self.assertEqual(stem, "1256-09")

    def test_filnamnet_innehaller_ingen_punkt_utom_filandelsen(self):
        """En punkt mitt i namnet läser som en filändelse, och är dessutom
        fel decimaltecken på svenska."""
        stem = receipts.build_stem(transaction(), self.source, "{date}_{amount}_{tag}")
        self.assertNotIn(".", stem)

    def test_utan_kalla_anvands_transaktionstexten(self):
        stem = receipts.build_stem(transaction(), None, "{date}_{amount}_{tag}")
        self.assertEqual(stem, "2026-03-14_449-00_google-workspace-abc")

    def test_taggen_utan_kalla_kortas_och_tappar_omljud(self):
        stem = receipts.build_stem(
            transaction(description="Försäkring Länsförsäkringar Sak AB Stockholm"),
            None,
            "{tag}",
        )
        self.assertEqual(stem, "forsakring-lansforsakringar-sak-ab-stock")
        self.assertEqual(len(stem), 40)

    def test_ovriga_platshallare(self):
        stem = receipts.build_stem(transaction(), self.source, "{company}_{account}")
        self.assertEqual(stem, "google_foretagskonto-8000-0012345678")

    def test_tom_platshallare_ger_inte_dubbla_avgransare(self):
        stem = receipts.build_stem(transaction(), None, "{date}_{company}_{tag}")
        self.assertEqual(stem, "2026-03-14_google-workspace-abc")

    def test_okand_platshallare_ger_begripligt_fel(self):
        with self.assertRaises(ReceiptError) as caught:
            receipts.build_stem(transaction(), self.source, "{datum}_{tag}")
        self.assertIn("{date}", str(caught.exception))

    def test_sokvagstecken_kan_inte_smita_in(self):
        source = Source(id="x", name="X", filename_tag="../../etc/passwd")
        stem = receipts.build_stem(transaction(), source, "{tag}")
        self.assertNotIn("/", stem)
        self.assertNotIn("..", stem)


class StoreReceiptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.store = temp_store(self.tmp)
        self.store._sources = [
            Source(id="google-workspace", name="Google Workspace", company="Google")
        ]
        self.transaction = transaction(source_id="google-workspace")
        self.store._transactions = [self.transaction]

    def test_filen_kopieras_in_under_manadskatalog(self):
        receipt = receipts.store_receipt(self.store, self.transaction, "invoice_5273829.pdf", PDF)
        path = self.store.receipts_dir / "2026-03" / "2026-03-14_449-00_google-workspace.pdf"
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_bytes(), PDF)
        self.assertEqual(receipt.stored_filename, path.name)

    def test_originalnamnet_sparas(self):
        receipt = receipts.store_receipt(self.store, self.transaction, "invoice_5273829.pdf", PDF)
        self.assertEqual(receipt.original_filename, "invoice_5273829.pdf")

    def test_sokvagen_lagras_relativt_datakatalogen(self):
        receipt = receipts.store_receipt(self.store, self.transaction, "f.pdf", PDF)
        self.assertEqual(
            receipt.stored_path, "receipts/2026-03/2026-03-14_449-00_google-workspace.pdf"
        )
        self.assertTrue(receipts.resolve_path(self.store, receipt.stored_path).is_file())

    def test_statusen_blir_has_receipt(self):
        receipts.store_receipt(self.store, self.transaction, "f.pdf", PDF)
        self.assertEqual(self.transaction.status, "has_receipt")

    def test_namnkrock_ger_suffix(self):
        other = transaction(id="annat|1", source_id="google-workspace")
        self.store._transactions.append(other)
        first = receipts.store_receipt(self.store, self.transaction, "a.pdf", PDF)
        second = receipts.store_receipt(self.store, other, "b.pdf", PDF)
        self.assertEqual(first.stored_filename, "2026-03-14_449-00_google-workspace.pdf")
        self.assertEqual(second.stored_filename, "2026-03-14_449-00_google-workspace-2.pdf")

    def test_mallen_kan_bytas_i_installningarna(self):
        self.store.settings["filename_template"] = "{company}-{date}-{amount}"
        receipt = receipts.store_receipt(self.store, self.transaction, "f.pdf", PDF)
        self.assertEqual(receipt.stored_filename, "google-2026-03-14-449-00.pdf")

    def test_borttagning_flyttar_till_papperskorgen(self):
        receipt = receipts.store_receipt(self.store, self.transaction, "f.pdf", PDF)
        path = receipts.resolve_path(self.store, receipt.stored_path)
        moved = receipts.remove_receipt(self.store, self.transaction)

        self.assertFalse(path.exists())
        self.assertTrue(Path(moved).is_file())
        self.assertEqual(Path(moved).read_bytes(), PDF)
        self.assertIsNone(self.transaction.receipt)
        self.assertEqual(self.transaction.status, "missing")

    def test_borttagning_nollstaller_aven_skickat(self):
        receipts.store_receipt(self.store, self.transaction, "f.pdf", PDF)
        self.transaction.sent_at = "2026-04-02T09:15:00+02:00"
        receipts.remove_receipt(self.store, self.transaction)
        self.assertIsNone(self.transaction.sent_at)
        self.assertEqual(self.transaction.status, "missing")

    def test_filen_och_mimetypen_kan_hamtas(self):
        receipts.store_receipt(self.store, self.transaction, "f.pdf", PDF)
        path, mimetype = receipts.receipt_file(self.store, self.transaction)
        self.assertEqual(mimetype, "application/pdf")
        self.assertEqual(path.read_bytes(), PDF)

    def test_saknad_fil_pa_disk_ger_begripligt_fel(self):
        receipt = receipts.store_receipt(self.store, self.transaction, "f.pdf", PDF)
        receipts.resolve_path(self.store, receipt.stored_path).unlink()
        with self.assertRaises(ReceiptError) as caught:
            receipts.receipt_file(self.store, self.transaction)
        self.assertIn("saknas", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
