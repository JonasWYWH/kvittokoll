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
        patterns = self.store.source_by_id(created["id"]).match_patterns
        self.assertEqual([(p.pattern, p.mode) for p in patterns],
                         [("NETLIFY SAN FRANCISCO", "contains")])

    def test_nytt_monster_fran_dialogen_kopplar_alla_forekomster(self):
        """En källa som skapas från kopplingsdialogen ska koppla alla rader
        mönstret träffar, inte bara den man råkade stå på."""
        rows = [r for r in self.api.transactions()["transactions"]
                if r["description"].startswith("ANTHROPIC")]
        self.assertGreater(len(rows), 1, "fixturen behöver flera ANTHROPIC-rader")

        created = self.api.create_source({"name": "Anthropic"})["source"]
        result = self.api.update_transaction(rows[0]["id"], {
            "source_id": created["id"],
            "add_match_pattern": True,
            "match_pattern": "ANTHROPIC",
            "match_pattern_mode": "starts_with",
        })
        self.assertTrue(result["pattern_added"])
        self.assertEqual(result["coupled"], len(rows) - 1)

        for row in self.api.transactions()["transactions"]:
            if row["description"].startswith("ANTHROPIC"):
                self.assertEqual(row["source_id"], created["id"], row["description"])

    def test_koppling_utan_nytt_monster_ror_inga_andra_rader(self):
        row = self.transaction("Utdelning")
        created = self.api.create_source({"name": "Eget"})["source"]
        result = self.api.update_transaction(row["id"], {"source_id": created["id"]})
        self.assertEqual(result["coupled"], 0)

    def test_monster_kan_sparas_med_lage(self):
        row = self.transaction("NETLIFY               SAN FRANCISCO")
        created = self.api.create_source({"name": "Netlify"})["source"]
        self.api.update_transaction(row["id"], {
            "source_id": created["id"],
            "add_match_pattern": True,
            "match_pattern": "NETLIFY",
            "match_pattern_mode": "starts_with",
        })
        patterns = self.store.source_by_id(created["id"]).match_patterns
        self.assertEqual([(p.pattern, p.mode) for p in patterns], [("NETLIFY", "starts_with")])

    def test_samma_text_med_olika_lage_ar_tva_regler(self):
        row = self.transaction("NETLIFY               SAN FRANCISCO")
        created = self.api.create_source({"name": "Netlify"})["source"]
        for mode in ("contains", "starts_with"):
            self.api.update_transaction(row["id"], {
                "source_id": created["id"], "add_match_pattern": True,
                "match_pattern": "NETLIFY", "match_pattern_mode": mode,
            })
        self.assertEqual(len(self.store.source_by_id(created["id"]).match_patterns), 2)

    def test_samma_text_och_lage_laggs_inte_till_tva_ganger(self):
        row = self.transaction("NETLIFY               SAN FRANCISCO")
        created = self.api.create_source({"name": "Netlify"})["source"]
        first = self.api.update_transaction(row["id"], {
            "source_id": created["id"], "add_match_pattern": True, "match_pattern": "NETLIFY",
        })
        second = self.api.update_transaction(row["id"], {
            "source_id": created["id"], "add_match_pattern": True, "match_pattern": "NETLIFY",
        })
        self.assertTrue(first["pattern_added"])
        self.assertFalse(second["pattern_added"])

    def test_okant_lage_avvisas(self):
        row = self.transaction("NETLIFY               SAN FRANCISCO")
        created = self.api.create_source({"name": "Netlify"})["source"]
        with self.assertRaises(ApiError):
            self.api.update_transaction(row["id"], {
                "source_id": created["id"], "add_match_pattern": True,
                "match_pattern": "NETLIFY", "match_pattern_mode": "kanske",
            })

    # -- redigera källor --------------------------------------------------

    def test_kallan_kan_redigeras(self):
        created = self.api.create_source({"name": "Netlify"})["source"]
        result = self.api.update_source(created["id"], {
            "name": "Netlify Inc",
            "company": "Netlify",
            "receipt_url": "https://app.netlify.com/billing",
            "settings_url": "https://app.netlify.com/settings",
            "receipt_type": "physical",
            "requires_receipt": False,
            "auto_send_configured": True,
            "note": "Under Billing → Receipts",
        })["source"]
        self.assertEqual(result["name"], "Netlify Inc")
        self.assertEqual(result["receipt_type"], "physical")
        self.assertFalse(result["requires_receipt"])
        self.assertTrue(result["auto_send_configured"])

        source = self.store.source_by_id(created["id"])
        self.assertEqual(source.receipt_url, "https://app.netlify.com/billing")
        self.assertEqual(source.note, "Under Billing → Receipts")

    def test_monster_kan_bytas_ut_med_lagen(self):
        created = self.api.create_source({"name": "Hyra"})["source"]
        self.api.update_source(created["id"], {"match_patterns": [
            {"pattern": "HYRA", "mode": "starts_with"},
            "KONTORSHYRA",
        ]})
        patterns = self.store.source_by_id(created["id"]).match_patterns
        self.assertEqual([(p.pattern, p.mode) for p in patterns],
                         [("HYRA", "starts_with"), ("KONTORSHYRA", "contains")])

    def test_tomma_monster_faller_bort(self):
        created = self.api.create_source({"name": "Hyra"})["source"]
        self.api.update_source(created["id"], {"match_patterns": ["HYRA", "", "   "]})
        self.assertEqual(len(self.store.source_by_id(created["id"]).match_patterns), 1)

    def test_okant_lage_i_monsterlistan_avvisas(self):
        created = self.api.create_source({"name": "Hyra"})["source"]
        with self.assertRaises(ApiError):
            self.api.update_source(created["id"], {
                "match_patterns": [{"pattern": "HYRA", "mode": "nastan"}]})

    def test_lank_utan_schema_far_https(self):
        """En länk utan schema blir relativ i webbläsaren och leder fel."""
        created = self.api.create_source({"name": "Google Workspace"})["source"]
        result = self.api.update_source(created["id"], {
            "receipt_url": "admin.google.com/ac/billing/history",
            "settings_url": "https://admin.google.com/settings",
        })["source"]
        self.assertEqual(result["receipt_url"], "https://admin.google.com/ac/billing/history")
        self.assertEqual(result["settings_url"], "https://admin.google.com/settings")

    def test_tom_lank_far_forbli_tom(self):
        created = self.api.create_source({"name": "X", "receipt_url": "https://exempel.se"})["source"]
        result = self.api.update_source(created["id"], {"receipt_url": ""})["source"]
        self.assertEqual(result["receipt_url"], "")

    def test_okand_verifikattyp_avvisas(self):
        created = self.api.create_source({"name": "Netlify"})["source"]
        with self.assertRaises(ApiError):
            self.api.update_source(created["id"], {"receipt_type": "papper"})

    def test_tomt_namn_avvisas(self):
        created = self.api.create_source({"name": "Netlify"})["source"]
        with self.assertRaises(ApiError):
            self.api.update_source(created["id"], {"name": "   "})

    def test_filnamnstaggen_slugifieras(self):
        created = self.api.create_source({"name": "Netlify"})["source"]
        result = self.api.update_source(created["id"], {"filename_tag": "Försäkring AB"})["source"]
        self.assertEqual(result["filename_tag"], "forsakring-ab")

    def test_redigering_av_okand_kalla_ger_404(self):
        with self.assertRaises(ApiError) as caught:
            self.api.update_source("finns-inte", {"name": "X"})
        self.assertEqual(caught.exception.status, 404)

    def test_kallan_bar_antal_kopplade_transaktioner(self):
        source = [s for s in self.api.state()["sources"] if s["id"] == "google-workspace"][0]
        self.assertEqual(source["transaction_count"], 1)

    # -- verifikatkrav från källan ----------------------------------------

    def test_kallans_krav_slar_igenom_pa_kopplade_rader(self):
        """Moms, skatt och löner ska kunna slås av en gång — inte rad för rad."""
        created = self.api.create_source(
            {"name": "Moms", "match_patterns": [{"pattern": "ANTHROPIC", "mode": "starts_with"}]}
        )["source"]
        rader = [r for r in self.api.transactions()["transactions"]
                 if r["source_id"] == created["id"]]
        self.assertGreater(len(rader), 1)
        self.assertTrue(all(r["requires_receipt"] for r in rader))

        result = self.api.update_source(created["id"], {"requires_receipt": False})
        self.assertEqual(result["applied"], len(rader))
        for row in self.api.transactions()["transactions"]:
            if row["source_id"] == created["id"]:
                self.assertFalse(row["requires_receipt"])
                self.assertEqual(row["status"], "not_required")

    def test_krav_pa_igen_tar_tillbaka_raderna(self):
        created = self.api.create_source(
            {"name": "Moms", "match_patterns": [{"pattern": "ANTHROPIC", "mode": "starts_with"}]}
        )["source"]
        self.api.update_source(created["id"], {"requires_receipt": False})
        result = self.api.update_source(created["id"], {"requires_receipt": True})
        self.assertGreater(result["applied"], 0)
        for row in self.api.transactions()["transactions"]:
            if row["source_id"] == created["id"]:
                self.assertEqual(row["status"], "missing")

    def test_oforandrat_krav_ror_inga_rader(self):
        """Att spara ett annat fält får inte nollställa manuella val."""
        created = self.api.create_source(
            {"name": "Moms", "match_patterns": [{"pattern": "ANTHROPIC", "mode": "starts_with"}]}
        )["source"]
        rad = [r for r in self.api.transactions()["transactions"]
               if r["source_id"] == created["id"]][0]
        self.api.update_transaction(rad["id"], {"requires_receipt": False})

        result = self.api.update_source(created["id"], {"company": "Skatteverket"})
        self.assertEqual(result["applied"], 0)
        kvar = [r for r in self.api.transactions()["transactions"] if r["id"] == rad["id"]][0]
        self.assertFalse(kvar["requires_receipt"])

    def test_nykopplad_rad_arver_kallans_krav(self):
        created = self.api.create_source({"name": "Moms", "requires_receipt": False})["source"]
        self.api.update_source(
            created["id"], {"match_patterns": [{"pattern": "ANTHROPIC", "mode": "starts_with"}]}
        )
        rader = [r for r in self.api.transactions()["transactions"]
                 if r["source_id"] == created["id"]]
        self.assertGreater(len(rader), 0)
        self.assertTrue(all(r["status"] == "not_required" for r in rader))

    def test_manuell_koppling_arver_ocksa(self):
        created = self.api.create_source({"name": "Moms", "requires_receipt": False})["source"]
        rad = self.transaction("Utdelning")
        self.assertTrue(rad["requires_receipt"])
        result = self.api.update_transaction(rad["id"], {"source_id": created["id"]})
        self.assertFalse(result["transaction"]["requires_receipt"])
        self.assertEqual(result["transaction"]["status"], "not_required")

    def test_uttryckligt_krav_i_samma_anrop_vinner_over_arvet(self):
        created = self.api.create_source({"name": "Moms", "requires_receipt": False})["source"]
        rad = self.transaction("Utdelning")
        result = self.api.update_transaction(
            rad["id"], {"source_id": created["id"], "requires_receipt": True}
        )
        self.assertTrue(result["transaction"]["requires_receipt"])

    # -- ta bort källor ---------------------------------------------------

    def test_borttagning_kopplar_loss_men_raderar_inga_rader(self):
        before = len(self.api.transactions()["transactions"])
        result = self.api.delete_source("google-workspace")
        self.assertEqual(result["uncoupled"], 1)
        self.assertIsNone(self.store.source_by_id("google-workspace"))
        self.assertEqual(len(self.api.transactions()["transactions"]), before)
        self.assertIsNone(self.transaction("Google Workspace_ab Dublin")["source_id"])

    def test_borttagningen_overlever_omlasning_fran_disk(self):
        self.api.delete_source("google-workspace")
        fresh = Api(temp_store_like(self.store))
        self.assertEqual([s["id"] for s in fresh.state()["sources"]], [])

    def test_borttagning_av_okand_kalla_ger_404(self):
        with self.assertRaises(ApiError) as caught:
            self.api.delete_source("finns-inte")
        self.assertEqual(caught.exception.status, 404)

    # -- provning av mönster ----------------------------------------------

    def test_provning_raknar_traffar_i_hela_listan(self):
        result = self.api.test_pattern({
            "pattern": "ANTHROPIC", "mode": "starts_with",
            "description": "ANTHROPIC IRELAND     DUBLIN",
        })
        self.assertTrue(result["matches"])
        self.assertEqual(result["total"], 3)

    def test_provning_visar_nar_laget_ar_for_snavt(self):
        result = self.api.test_pattern({
            "pattern": "DUBLIN", "mode": "starts_with",
            "description": "ANTHROPIC IRELAND     DUBLIN",
        })
        self.assertFalse(result["matches"])
        self.assertEqual(result["total"], 0)

    def test_provning_med_slutar_med_hittar_raden(self):
        result = self.api.test_pattern({
            "pattern": "DUBLIN", "mode": "ends_with",
            "description": "ANTHROPIC IRELAND     DUBLIN",
        })
        self.assertTrue(result["matches"])
        self.assertEqual(result["total"], 2)
        self.assertTrue(all(s.rstrip().endswith("Dublin") or s.rstrip().endswith("DUBLIN")
                            for s in result["samples"]))

    def test_provning_avvisar_okant_lage(self):
        with self.assertRaises(ApiError):
            self.api.test_pattern({"pattern": "X", "mode": "kanske"})

    def test_provning_med_tomt_monster_ger_noll(self):
        result = self.api.test_pattern({"pattern": "", "description": "Vad som helst"})
        self.assertFalse(result["matches"])
        self.assertEqual(result["total"], 0)

    def test_state_innehaller_lagena(self):
        modes = [m["id"] for m in self.api.state()["match_modes"]]
        self.assertEqual(modes, ["contains", "starts_with", "ends_with"])

    def test_okand_kalla_avvisas(self):
        row = self.transaction("Utdelning")
        with self.assertRaises(ApiError):
            self.api.update_transaction(row["id"], {"source_id": "finns-inte"})

    def test_ny_kalla_kopplar_raderna_direkt(self):
        """En regel som inte kopplar något är bara en text. Matchningen ska
        inte vänta på att användaren hittar en knapp."""
        result = self.api.create_source({"name": "Netlify", "match_patterns": ["NETLIFY"]})
        self.assertEqual(result["coupled"], 1)
        self.assertEqual(
            self.transaction("NETLIFY               SAN FRANCISCO")["source_id"], "netlify"
        )

    def test_redigerad_kalla_kopplar_raderna_direkt(self):
        created = self.api.create_source({"name": "Netlify"})["source"]
        result = self.api.update_source(created["id"], {"match_patterns": ["NETLIFY"]})
        self.assertEqual(result["coupled"], 1)
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

    def test_battre_regel_rattar_en_automatisk_koppling(self):
        """En automatisk koppling är motorns gissning. Dyker en mer specifik
        källa upp senare ska den ta över."""
        row = self.transaction("NETLIFY               SAN FRANCISCO")
        self.api.create_source({"name": "Kort", "match_patterns": ["NETLIFY"]})
        self.assertEqual(self.transaction(row["description"])["source_id"], "kort")

        self.api.create_source({"name": "Lang", "match_patterns": ["NETLIFY SAN FRANCISCO"]})
        self.assertEqual(self.transaction(row["description"])["source_id"], "lang")

    def test_battre_regel_rattar_inte_en_manuell_koppling(self):
        row = self.transaction("NETLIFY               SAN FRANCISCO")
        manuell = self.api.create_source({"name": "Manuell"})["source"]
        self.api.update_transaction(row["id"], {"source_id": manuell["id"]})

        self.api.create_source({"name": "Lang", "match_patterns": ["NETLIFY SAN FRANCISCO"]})
        self.assertEqual(self.transaction(row["description"])["source_id"], "manuell")

    def test_matchningen_tar_aldrig_bort_en_koppling(self):
        """Att en regel ändras får inte tömma en rad som redan hittat hem."""
        created = self.api.create_source({"name": "Netlify", "match_patterns": ["NETLIFY"]})["source"]
        self.api.update_source(created["id"], {"match_patterns": ["FINNS-INTE"]})
        self.assertEqual(
            self.transaction("NETLIFY               SAN FRANCISCO")["source_id"], "netlify"
        )

    def test_kopplingen_markeras_som_manuell_bara_vid_manuellt_val(self):
        auto = self.transaction("Google Workspace_ab Dublin")
        self.assertFalse(auto["source_manual"])

        row = self.transaction("Utdelning")
        created = self.api.create_source({"name": "Eget"})["source"]
        self.api.update_transaction(row["id"], {"source_id": created["id"]})
        self.assertTrue(self.transaction("Utdelning")["source_manual"])

    # -- förklaring av matchning ------------------------------------------

    def test_forklaring_sager_varfor_kallan_matchar(self):
        created = self.api.create_source({
            "name": "Hyra", "match_patterns": [{"pattern": "NETLIFY", "mode": "starts_with"}]
        })["source"]
        result = self.api.explain_source_match({
            "source_id": created["id"], "description": "NETLIFY               SAN FRANCISCO"
        })
        self.assertTrue(result["matches"])
        self.assertIn("börjar med", result["explanation"])

    def test_forklaring_sager_nar_kallan_inte_matchar(self):
        created = self.api.create_source({"name": "Hyra", "match_patterns": ["HYRA"]})["source"]
        result = self.api.explain_source_match({
            "source_id": created["id"], "description": "NETLIFY SAN FRANCISCO"
        })
        self.assertFalse(result["matches"])
        self.assertIsNone(result["explanation"])
        self.assertEqual(result["patterns"], ["HYRA"])

    def test_forklaring_av_okand_kalla_ger_404(self):
        with self.assertRaises(ApiError) as caught:
            self.api.explain_source_match({"source_id": "finns-inte", "description": "x"})
        self.assertEqual(caught.exception.status, 404)

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

    # -- utskick ----------------------------------------------------------

    def receipted(self):
        """En rad med verifikat och ifyllda adresser."""
        row = self.transaction("Google Workspace_ab Dublin")
        self.api.update_settings({
            "recipient_email": "inkorg@bokforing.example.se",
            "sender_email": "mig@mittforetag.se",
        })
        self.api.upload_receipts(row["id"], [("faktura.pdf", b"%PDF-1.4\ntrailer\n%%EOF\n")])
        return self.transaction("Google Workspace_ab Dublin")

    def test_utan_verifikat_gar_det_inte_att_skicka(self):
        row = self.transaction("Utdelning")
        details = self.api.email_preview(row["id"])
        self.assertFalse(details["can_send"])
        self.assertEqual(details["attachments"], [])

    def test_utan_adresser_gar_det_inte_att_skicka(self):
        row = self.transaction("Google Workspace_ab Dublin")
        self.api.upload_receipts(row["id"], [("f.pdf", b"%PDF-1.4\ntrailer\n%%EOF\n")])
        details = self.api.email_preview(row["id"])
        self.assertFalse(details["can_send"])
        self.assertIn("recipient_email", details["missing"])

    def test_med_verifikat_och_adresser_gar_det_att_skicka(self):
        row = self.receipted()
        details = self.api.email_preview(row["id"])
        self.assertTrue(details["can_send"])
        self.assertEqual(details["missing"], {})
        self.assertEqual(details["to"], "inkorg@bokforing.example.se")
        self.assertTrue(details["attachments"][0].endswith(".pdf"))

    def test_eml_skrivs_men_raden_markeras_inte_automatiskt(self):
        """§8.3 — verktyget kan inte veta om mejlet faktiskt gick iväg."""
        api = Api(self.store, allow_open=False)
        row = self.receipted()
        result = api.create_email(row["id"])
        self.assertTrue(Path(result["path"]).is_file())
        self.assertFalse(result["opened"])
        self.assertIsNone(self.transaction("Google Workspace_ab Dublin")["sent_at"])
        self.assertEqual(self.transaction("Google Workspace_ab Dublin")["status"], "has_receipt")

    def test_markera_och_angra_skickat(self):
        row = self.receipted()
        marked = self.api.mark_sent(row["id"])["transaction"]
        self.assertEqual(marked["status"], "sent")
        self.assertTrue(marked["sent_at"])

        unmarked = self.api.unmark_sent(row["id"])["transaction"]
        self.assertIsNone(unmarked["sent_at"])
        self.assertEqual(unmarked["status"], "has_receipt")

    def test_rad_utan_verifikat_kan_inte_markeras_som_skickad(self):
        row = self.transaction("Utdelning")
        with self.assertRaises(ApiError):
            self.api.mark_sent(row["id"])

    def test_flera_filer_laggs_till_utan_att_skriva_over(self):
        """Delbetalningar och samlingsfakturor kommer sällan som en fil."""
        row = self.receipted()
        result = self.api.upload_receipts(row["id"], [
            ("del2.pdf", b"%PDF-1.4\ntrailer\n%%EOF\n"),
            ("del3.pdf", b"%PDF-1.4\ntrailer\n%%EOF\n"),
        ])
        self.assertEqual(len(result["added"]), 2)
        namn = [r["original_filename"] for r in result["transaction"]["receipts"]]
        self.assertEqual(namn, ["faktura.pdf", "del2.pdf", "del3.pdf"])

    def test_en_av_flera_kan_tas_bort(self):
        row = self.receipted()
        self.api.upload_receipts(row["id"], [("del2.pdf", b"%PDF-1.4\ntrailer\n%%EOF\n")])
        aktuell = self.transaction("Google Workspace_ab Dublin")
        result = self.api.delete_receipt(row["id"], aktuell["receipts"][0]["stored_filename"])
        self.assertEqual(len(result["transaction"]["receipts"]), 1)
        self.assertEqual(result["transaction"]["status"], "has_receipt")

    def test_okant_filnamn_ger_404(self):
        row = self.receipted()
        with self.assertRaises(ApiError) as caught:
            self.api.delete_receipt(row["id"], "finns-inte.pdf")
        self.assertEqual(caught.exception.status, 404)

    def test_borttaget_verifikat_nollstaller_skickat(self):
        row = self.receipted()
        self.api.mark_sent(row["id"])
        namn = self.transaction("Google Workspace_ab Dublin")["receipts"][0]["stored_filename"]
        result = self.api.delete_receipt(row["id"], namn)["transaction"]
        self.assertIsNone(result["sent_at"])
        self.assertEqual(result["status"], "missing")

    # -- inställningar ----------------------------------------------------

    def test_adresser_sparas_till_settings_json(self):
        self.api.update_settings({"recipient_email": "inkorg@bokforing.example.se"})
        self.assertTrue(self.store.settings_path.is_file())
        fresh = Api(temp_store_like(self.store))
        self.assertEqual(
            fresh.state()["settings"]["recipient_email"], "inkorg@bokforing.example.se"
        )

    def test_orimlig_adress_avvisas(self):
        with self.assertRaises(ApiError):
            self.api.update_settings({"recipient_email": "inte-en-adress"})

    def test_tom_adress_far_sparas(self):
        """Att nollställa en adress ska gå — det är inte samma sak som skräp."""
        self.api.update_settings({"recipient_email": ""})
        self.assertEqual(self.api.state()["settings"]["recipient_email"], "")

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
