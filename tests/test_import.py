"""Import: CSV med profil, camt.053, samt hela flödet förhandsgranska→bekräfta."""

import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, fixture_bytes, temp_store  # noqa: F401

from kvittokoll import importer
from kvittokoll.importers import ImportError_, camt053, csv_import, detect_format
from kvittokoll.importers.profiles import find_profile, load_profiles


class CsvImportTest(unittest.TestCase):
    def setUp(self):
        self.data = fixture_bytes("swedbank_sample.csv")
        self.profile = find_profile(load_profiles(ROOT / "profiles"), "swedbank")
        self.assertIsNotNone(self.profile, "profiles/swedbank.json saknas")

    def test_kodning_upptacks(self):
        text, encoding = csv_import.decode(self.data, self.profile.encoding)
        self.assertEqual(encoding, "cp1252")
        self.assertIn("Företagskonto", text)

    def test_rader_tolkas(self):
        result = csv_import.parse(self.data, self.profile)
        self.assertEqual(len(result.rows), 8)
        first = result.rows[0]
        self.assertEqual(first["date"], "2026-08-11")
        self.assertEqual(first["amount"], -199.00)
        self.assertEqual(first["currency"], "SEK")
        self.assertEqual(first["description"], "ANTHROPIC IRELAND     DUBLIN")
        self.assertEqual(first["transaction_type"], "Kortköp/uttag")
        self.assertEqual(first["balance"], 471341.60)

    def test_kontokolumnen_byggs_av_mall(self):
        result = csv_import.parse(self.data, self.profile)
        self.assertEqual(result.rows[0]["account"], "Företagskonto 8000-0012345678")

    def test_inbetalning_forblir_positiv(self):
        result = csv_import.parse(self.data, self.profile)
        incoming = [r for r in result.rows if r["description"] == "12345678"]
        self.assertEqual(len(incoming), 1)
        self.assertEqual(incoming[0]["amount"], 50000.00)

    def test_trasiga_rader_listas_med_radnummer_och_orsak(self):
        result = csv_import.parse(self.data, self.profile)
        self.assertEqual(len(result.errors), 2)
        lines = sorted(error.line for error in result.errors)
        # Radnumren pekar i originalfilen: rubrikrad + 1 skippad rad.
        self.assertEqual(lines, [11, 12])
        reasons = " ".join(error.reason for error in result.errors)
        self.assertIn("datum", reasons)
        self.assertIn("belopp", reasons)

    def test_fel_profil_ger_tydligt_fel(self):
        wrong = find_profile(load_profiles(ROOT / "profiles"), "swedbank")
        wrong.columns["date"] = "FinnsInte"
        with self.assertRaises(ImportError_) as caught:
            csv_import.parse(self.data, wrong)
        self.assertIn("FinnsInte", str(caught.exception))


class Camt053Test(unittest.TestCase):
    def setUp(self):
        self.data = fixture_bytes("camt053_sample.xml")

    def test_format_upptacks(self):
        self.assertEqual(detect_format("utdrag.xml", self.data), "camt053")

    def test_debet_blir_negativt_kredit_positivt(self):
        result = camt053.parse(self.data)
        by_date = {row["date"]: row for row in result.rows}
        self.assertEqual(by_date["2026-03-14"]["amount"], -449.00)
        self.assertEqual(by_date["2026-03-15"]["amount"], 12500.00)

    def test_referenstext_i_prioriteringsordning(self):
        result = camt053.parse(self.data)
        by_date = {row["date"]: row for row in result.rows}
        self.assertEqual(by_date["2026-03-14"]["description"], "GOOGLE *WORKSPACE_ABC")
        self.assertEqual(
            by_date["2026-03-15"]["description"], "Bankgiro inbetalning 12345678"
        )
        self.assertEqual(by_date["2026-03-16"]["description"], "Netlify Inc")

    def test_kontonummer_hamtas_fran_iban(self):
        result = camt053.parse(self.data)
        self.assertEqual(result.rows[0]["account"], "SE0000000000000000000000")

    def test_acctsvcrref_blir_bank_id(self):
        result = camt053.parse(self.data)
        self.assertEqual(result.rows[0]["bank_id"], "SWD-2026-0001")

    def test_post_utan_cdtdbtind_hamnar_bland_felen(self):
        result = camt053.parse(self.data)
        self.assertEqual(len(result.rows), 3)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("CdtDbtInd", result.errors[0].reason)

    def test_icke_xml_ger_importfel(self):
        with self.assertRaises(ImportError_):
            camt053.parse(b"<Document><nope/></Document>")


class ImportFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.store = temp_store(
            self.tmp,
            sources=[
                {
                    "id": "google-workspace",
                    "name": "Google Workspace",
                    "company": "Google",
                    "match_patterns": ["GOOGLE WORKSPACE"],
                    "requires_receipt": True,
                },
                {
                    "id": "google-cloud",
                    "name": "Google Cloud",
                    "company": "Google",
                    "match_patterns": ["GOOGLE CLOUD"],
                    "requires_receipt": True,
                },
                {
                    "id": "egna-overforingar",
                    "name": "Egna överföringar",
                    "match_patterns": ["UTDELNING"],
                    "requires_receipt": False,
                },
            ],
        )
        self.data = fixture_bytes("swedbank_sample.csv")

    def preview(self):
        return importer.preview(self.store, "swedbank_sample.csv", self.data)

    def test_forhandsgranskning_skriver_ingenting(self):
        self.preview()
        self.assertFalse(self.store.transactions_path.exists())

    def test_sammanfattningens_siffror(self):
        summary = self.preview()["summary"]
        self.assertEqual(summary["parsed"], 8)
        self.assertEqual(summary["new"], 8)
        self.assertEqual(summary["known"], 0)
        self.assertEqual(summary["failed"], 2)
        self.assertEqual(summary["matched"], 3)

    def test_kallor_kopplas_och_kravet_arvs(self):
        rows = {row["description"]: row for row in self.preview()["rows"]}
        self.assertEqual(rows["Google Workspace_ab Dublin"]["source_id"], "google-workspace")
        self.assertEqual(rows["Google CLOUD 46DG53 K8326"]["source_id"], "google-cloud")
        self.assertEqual(rows["Utdelning"]["source_id"], "egna-overforingar")
        self.assertFalse(rows["Utdelning"]["requires_receipt"])
        self.assertEqual(rows["Utdelning"]["status"], "not_required")

    def test_okopplad_rad_kraver_verifikat_som_standard(self):
        rows = {row["description"]: row for row in self.preview()["rows"]}
        netlify = rows["NETLIFY               SAN FRANCISCO"]
        self.assertIsNone(netlify["source_id"])
        self.assertTrue(netlify["requires_receipt"])
        self.assertEqual(netlify["status"], "missing")

    def test_bekraftelse_skriver_och_omimport_ger_noll_nya(self):
        result = importer.commit(self.store, self.preview())
        self.assertEqual(result["added"], 8)
        self.assertTrue(self.store.transactions_path.exists())

        again = self.preview()
        self.assertEqual(again["summary"]["new"], 0)
        self.assertEqual(again["summary"]["known"], 8)
        self.assertEqual(importer.commit(self.store, again)["added"], 0)
        self.assertEqual(len(self.store.transactions()), 8)

    def test_import_tar_backup_men_inte_forsta_gangen(self):
        self.assertIsNone(importer.commit(self.store, self.preview())["backup"])
        second = importer.commit(self.store, self.preview())
        self.assertIsNotNone(second["backup"])
        self.assertTrue(Path(second["backup"]).exists())

    def test_import_andrar_aldrig_befintlig_status(self):
        importer.commit(self.store, self.preview())
        transaction = self.store.transactions()[0]
        transaction.requires_receipt = False
        transaction.note = "hanterad manuellt"
        self.store.save_transactions()

        importer.commit(self.store, self.preview())
        after = self.store.transaction_by_id(transaction.id)
        self.assertFalse(after.requires_receipt)
        self.assertEqual(after.note, "hanterad manuellt")

    def test_profil_gissas_nar_ingen_anges(self):
        result = self.preview()
        self.assertEqual(result["profile_id"], "swedbank")
        self.assertEqual(result["format"], "csv")


if __name__ == "__main__":
    unittest.main()
