"""API-lagret: arbetslistans åtgärder."""

import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, fixture_bytes, temp_store  # noqa: F401

from kvittokoll.api import Api, ApiError


class ApiTest(unittest.TestCase):
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
                }
            ],
        )
        self.api = Api(self.store)
        preview = self.api.import_preview(
            "swedbank_sample.csv", fixture_bytes("swedbank_sample.csv")
        )
        self.api.import_commit(preview["token"])

    def transaction(self, description):
        for row in self.api.transactions()["transactions"]:
            if row["description"] == description:
                return row
        raise AssertionError("hittade inte {!r}".format(description))

    # -- import -----------------------------------------------------------

    def test_preview_utan_bekraftelse_skriver_inte(self):
        store = temp_store(Path(tempfile.mkdtemp()))
        api = Api(store)
        api.import_preview("s.csv", fixture_bytes("swedbank_sample.csv"))
        self.assertEqual(api.transactions()["transactions"], [])

    def test_okand_token_ger_404(self):
        with self.assertRaises(ApiError) as caught:
            self.api.import_commit("finns-inte")
        self.assertEqual(caught.exception.status, 404)

    def test_token_kan_bara_anvandas_en_gang(self):
        preview = self.api.import_preview("s.csv", fixture_bytes("swedbank_sample.csv"))
        self.api.import_commit(preview["token"])
        with self.assertRaises(ApiError):
            self.api.import_commit(preview["token"])

    def test_avbruten_import_skriver_inget(self):
        before = len(self.api.transactions()["transactions"])
        preview = self.api.import_preview("s.csv", fixture_bytes("swedbank_sample.csv"))
        self.api.import_cancel(preview["token"])
        self.assertEqual(len(self.api.transactions()["transactions"]), before)

    def test_tom_fil_ger_fel(self):
        with self.assertRaises(ApiError):
            self.api.import_preview("tom.csv", b"")

    # -- kräver verifikat -------------------------------------------------

    def test_vaxla_kraver_verifikat(self):
        row = self.transaction("Utdelning")
        self.assertTrue(row["requires_receipt"])
        result = self.api.update_transaction(row["id"], {"requires_receipt": False})
        self.assertEqual(result["transaction"]["status"], "not_required")
        self.assertFalse(self.transaction("Utdelning")["requires_receipt"])

    def test_andringen_overlever_omlasning_fran_disk(self):
        row = self.transaction("Utdelning")
        self.api.update_transaction(row["id"], {"requires_receipt": False, "note": "eget uttag"})
        fresh = Api(temp_store_like(self.store))
        reloaded = [t for t in fresh.transactions()["transactions"] if t["id"] == row["id"]][0]
        self.assertFalse(reloaded["requires_receipt"])
        self.assertEqual(reloaded["note"], "eget uttag")

    def test_andring_kan_gora_om_kallans_standard(self):
        row = self.transaction("Google Workspace_ab Dublin")
        self.assertEqual(row["source_id"], "google-workspace")
        result = self.api.update_transaction(
            row["id"], {"requires_receipt": False, "apply_to_source": True}
        )
        self.assertTrue(result["applied_to_source"])
        self.assertFalse(self.store.source_by_id("google-workspace").requires_receipt)

    def test_utan_apply_to_source_rors_inte_kallan(self):
        row = self.transaction("Google Workspace_ab Dublin")
        self.api.update_transaction(row["id"], {"requires_receipt": False})
        self.assertTrue(self.store.source_by_id("google-workspace").requires_receipt)

    # -- koppling ---------------------------------------------------------

    def test_koppla_om_och_lar_kallan_monstret(self):
        row = self.transaction("NETLIFY               SAN FRANCISCO")
        self.assertIsNone(row["source_id"])
        created = self.api.create_source({"name": "Netlify", "company": "Netlify"})["source"]
        result = self.api.update_transaction(
            row["id"], {"source_id": created["id"], "add_match_pattern": True}
        )
        self.assertTrue(result["pattern_added"])
        self.assertIn(
            "NETLIFY SAN FRANCISCO",
            self.store.source_by_id(created["id"]).match_patterns,
        )

    def test_okand_kalla_avvisas(self):
        row = self.transaction("Utdelning")
        with self.assertRaises(ApiError):
            self.api.update_transaction(row["id"], {"source_id": "finns-inte"})

    def test_rematch_kopplar_rader_efter_ny_kalla(self):
        self.api.create_source({"name": "Netlify", "match_patterns": ["NETLIFY"]})
        result = self.api.rematch_sources()
        self.assertEqual(result["changed"], 1)
        self.assertEqual(
            self.transaction("NETLIFY               SAN FRANCISCO")["source_id"], "netlify"
        )

    def test_rematch_ror_inte_redan_kopplade_rader(self):
        """En manuell koppling ska överleva att en bättre matchande källa
        läggs till efteråt. Koppling är alltid användarens beslut."""
        netlify = self.api.create_source({"name": "Netlify"})["source"]
        row = self.transaction("Google Workspace_ab Dublin")
        self.api.update_transaction(row["id"], {"source_id": netlify["id"]})

        self.api.create_source(
            {"name": "Google Workspace exakt", "match_patterns": ["GOOGLE WORKSPACE AB DUBLIN"]}
        )
        self.api.rematch_sources()
        self.assertEqual(self.transaction("Google Workspace_ab Dublin")["source_id"], "netlify")

    def test_rematch_valjer_langsta_monstret_for_okopplade_rader(self):
        row = self.transaction("NETLIFY               SAN FRANCISCO")
        self.api.create_source({"name": "Kort", "match_patterns": ["NETLIFY"]})
        self.api.create_source({"name": "Lang", "match_patterns": ["NETLIFY SAN FRANCISCO"]})
        self.api.rematch_sources()
        self.assertEqual(self.transaction(row["description"])["source_id"], "lang")

    # -- massändring ------------------------------------------------------

    def test_massandring_av_flera_rader(self):
        ids = [
            self.transaction("Utdelning")["id"],
            self.transaction("12345678")["id"],
        ]
        result = self.api.update_transactions_bulk(ids, {"requires_receipt": False})
        self.assertEqual(len(result["updated"]), 2)
        self.assertFalse(self.transaction("Utdelning")["requires_receipt"])
        self.assertFalse(self.transaction("12345678")["requires_receipt"])

    def test_okand_transaktion_ger_404(self):
        with self.assertRaises(ApiError) as caught:
            self.api.update_transaction("finns|inte|alls|1", {"note": "x"})
        self.assertEqual(caught.exception.status, 404)

    # -- state ------------------------------------------------------------

    def test_state_innehaller_det_granssnittet_behover(self):
        state = self.api.state()
        self.assertIn("settings", state)
        self.assertIn("sources", state)
        self.assertIn("transactions", state)
        self.assertTrue(any(p["id"] == "swedbank" for p in state["profiles"]))

    def test_transaktioner_kommer_nyast_forst(self):
        dates = [row["date"] for row in self.api.transactions()["transactions"]]
        self.assertEqual(dates, sorted(dates, reverse=True))


def temp_store_like(store):
    """Ett nytt Store mot samma katalog — tvingar omläsning från disk."""
    from kvittokoll.storage import Store

    return Store(store.root)


if __name__ == "__main__":
    unittest.main()
