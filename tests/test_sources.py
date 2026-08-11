"""Källmatchning (§4.3) — inklusive fallet som motiverar hela entiteten:
Google Workspace och Google Cloud är två källor med snarlik banktext.
"""

import json
import unittest

from helpers import ROOT  # noqa: F401

from kvittokoll.models import (
    MATCH_CONTAINS,
    MATCH_ENDS_WITH,
    MATCH_STARTS_WITH,
    MatchPattern,
    Source,
)
from kvittokoll.normalize import sort_key
from kvittokoll.sources import (
    compile_pattern,
    match_source,
    new_source,
    unique_source_id,
)


def source(source_id, patterns, **extra):
    return Source(id=source_id, name=source_id, match_patterns=patterns, **extra)


def starts(text):
    return {"pattern": text, "mode": MATCH_STARTS_WITH}


def ends(text):
    return {"pattern": text, "mode": MATCH_ENDS_WITH}


class MatchSourceTest(unittest.TestCase):
    def setUp(self):
        self.sources = [
            source("google-workspace", ["GOOGLE *WORKSPACE", "GOOGLE WORKSPA"]),
            source("google-cloud", ["GOOGLE CLOUD"]),
            source("anthropic-claude", ["ANTHROPIC* CLAUDE SUB", "CLAUDE.AI SUBSCRIPTIO"]),
        ]

    def test_delstrang_skiftlagesoberoende(self):
        matched, ambiguous = match_source("Google Workspace_ab Dublin", self.sources)
        self.assertEqual(matched, "google-workspace")
        self.assertEqual(ambiguous, [])

    def test_monster_med_skiljetecken_traffar_bankens_stavning(self):
        """'GOOGLE *WORKSPACE' ska träffa 'Google Workspace_ab' — samma
        normalisering körs på båda sidor."""
        matched, _ = match_source("Google Workspace_ab Dublin", self.sources)
        self.assertEqual(matched, "google-workspace")

    def test_syskonprodukter_halls_isar(self):
        self.assertEqual(match_source("Google CLOUD 46DG53 K8326", self.sources)[0], "google-cloud")
        self.assertEqual(
            match_source("Google Workspace_ab Dublin", self.sources)[0], "google-workspace"
        )

    def test_langre_monster_vinner(self):
        sources = [source("kort", ["GOOGLE"]), source("lang", ["GOOGLE WORKSPACE"])]
        matched, ambiguous = match_source("GOOGLE WORKSPACE ABC", sources)
        self.assertEqual(matched, "lang")
        self.assertEqual(ambiguous, [])

    def test_lika_langa_traffar_ger_tvetydighet_inte_gissning(self):
        # Båda mönstren är tio tecken och båda är delsträngar av texten.
        sources = [source("a", ["GOOGLE ABC"]), source("b", ["OOGLE ABCD"])]
        matched, ambiguous = match_source("GOOGLE ABCD", sources)
        self.assertIsNone(matched)
        self.assertEqual(ambiguous, ["a", "b"])

    def test_ingen_traff_ger_ingen_koppling(self):
        matched, ambiguous = match_source("HELT OKÄND HANDLARE", self.sources)
        self.assertIsNone(matched)
        self.assertEqual(ambiguous, [])

    def test_tom_text_kraschar_inte(self):
        self.assertEqual(match_source("", self.sources), (None, []))


class MatchModeTest(unittest.TestCase):
    """De tre lägena: innehåller, börjar med, slutar med."""

    def test_borjar_med_traffar_bara_i_borjan(self):
        sources = [source("kontorshyra", [starts("HYRA")])]
        self.assertEqual(match_source("Hyra Kontorsgatan 5", sources)[0], "kontorshyra")
        self.assertIsNone(match_source("Bilhyra Stockholm", sources)[0])
        self.assertIsNone(match_source("Avser hyra april", sources)[0])

    def test_innehaller_traffar_var_som_helst(self):
        sources = [source("allt-hyra", ["HYRA"])]
        for text in ("Hyra Kontorsgatan 5", "Bilhyra Stockholm", "Avser hyra april"):
            self.assertEqual(match_source(text, sources)[0], "allt-hyra", text)

    def test_slutar_med_traffar_bara_i_slutet(self):
        sources = [source("dublin", [ends("DUBLIN")])]
        self.assertEqual(match_source("ANTHROPIC IRELAND     DUBLIN", sources)[0], "dublin")
        self.assertIsNone(match_source("DUBLIN AIRPORT SHOP", sources)[0])

    def test_forankringen_galler_hela_texten_inte_ord(self):
        """\\A och \\Z, inte ^ och $ — en flerradig text ska inte kunna
        smita in genom en radbrytning."""
        sources = [source("hyra", [starts("HYRA")])]
        self.assertIsNone(match_source("Betalning\nHyra april", sources)[0])

    def test_lagena_normaliseras_som_vanlig_text(self):
        """Skiljetecken i början ska inte förstöra en börjar-med-matchning,
        eftersom båda sidor normaliseras först."""
        sources = [source("hyra", [starts("HYRA KONTOR")])]
        self.assertEqual(match_source("Hyra/Kontor Stockholm", sources)[0], "hyra")

    def test_anvandartext_tolkas_inte_som_regex(self):
        """Skriver användaren '.*' ska det matcha tecknen, inte allt."""
        sources = [source("prick", ["A.*B"])]
        self.assertIsNone(match_source("AXXXB", sources)[0])
        self.assertEqual(match_source("FIRMA A.*B AB", sources)[0], "prick")

    def test_forankrat_vinner_over_lika_langt_ofoerankrat(self):
        sources = [source("bred", ["HYRA"]), source("smal", [starts("HYRA")])]
        matched, ambiguous = match_source("Hyra Kontorsgatan 5", sources)
        self.assertEqual(matched, "smal")
        self.assertEqual(ambiguous, [])

    def test_langre_monster_slar_forankring(self):
        """Längden går först, enligt kravspecen."""
        sources = [source("kort", [starts("HYRA")]), source("lang", ["HYRA KONTORSGATAN"])]
        self.assertEqual(match_source("Hyra Kontorsgatan 5", sources)[0], "lang")

    def test_okant_lage_behandlas_som_innehaller(self):
        sources = [source("x", [{"pattern": "HYRA", "mode": "trams"}])]
        self.assertEqual(match_source("Bilhyra", sources)[0], "x")

    def test_tomt_monster_matchar_ingenting(self):
        self.assertIsNone(compile_pattern("", MATCH_STARTS_WITH))
        self.assertIsNone(match_source("Vad som helst", [source("tom", ["", "   "])])[0])


class MatchPatternSerializationTest(unittest.TestCase):
    def test_strang_tolkas_som_innehaller(self):
        pattern = MatchPattern.from_any("GOOGLE WORKSPACE")
        self.assertEqual(pattern.mode, MATCH_CONTAINS)
        self.assertEqual(pattern.pattern, "GOOGLE WORKSPACE")

    def test_objekt_behaller_laget(self):
        pattern = MatchPattern.from_any({"pattern": "HYRA", "mode": "starts_with"})
        self.assertEqual(pattern.mode, MATCH_STARTS_WITH)

    def test_skrap_lage_faller_tillbaka_pa_innehaller(self):
        self.assertEqual(MatchPattern.from_any({"pattern": "X", "mode": "hopp"}).mode, MATCH_CONTAINS)

    def test_innehaller_skrivs_som_kort_strang(self):
        """Håller sources.json handredigerbar i normalfallet."""
        written = source("s", ["GOOGLE", starts("HYRA")]).to_dict()["match_patterns"]
        self.assertEqual(written, ["GOOGLE", {"pattern": "HYRA", "mode": "starts_with"}])

    def test_rundtur_genom_json_bevarar_lagena(self):
        original = source("s", ["GOOGLE", starts("HYRA"), ends("DUBLIN")])
        restored = Source.from_dict(json.loads(json.dumps(original.to_dict())))
        self.assertEqual(
            [(p.pattern, p.mode) for p in restored.match_patterns],
            [("GOOGLE", MATCH_CONTAINS), ("HYRA", MATCH_STARTS_WITH), ("DUBLIN", MATCH_ENDS_WITH)],
        )

    def test_gamla_filer_utan_lagen_lases_fortfarande(self):
        restored = Source.from_dict({"id": "s", "name": "S", "match_patterns": ["GOOGLE WORKSPACE"]})
        self.assertEqual(restored.match_patterns[0].mode, MATCH_CONTAINS)
        self.assertEqual(match_source("Google Workspace_ab", [restored])[0], "s")


class SortOrderTest(unittest.TestCase):
    """Källorna listas i svensk bokstavsordning, på namn — inte på bolag."""

    def test_svenska_bokstaver_hamnar_efter_z(self):
        names = ["Örn", "Ziko Bank", "Åke", "Ärlig", "Alfa"]
        self.assertEqual(
            sorted(names, key=sort_key), ["Alfa", "Ziko Bank", "Åke", "Ärlig", "Örn"]
        )

    def test_skiftlage_spelar_ingen_roll(self):
        names = ["google Workspace", "GITHUB", "AIMO Parkering"]
        self.assertEqual(
            sorted(names, key=sort_key), ["AIMO Parkering", "GITHUB", "google Workspace"]
        )

    def test_store_listar_kallor_i_namnordning(self):
        import json
        import shutil
        import tempfile
        from pathlib import Path as P

        from helpers import temp_store

        tmp = P(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(tmp), True)
        store = temp_store(tmp, sources=[
            {"id": "b", "name": "Örn", "company": "Alfa"},
            {"id": "a", "name": "AIMO Parkering", "company": "Zeta"},
            {"id": "c", "name": "GITHUB", "company": "Microsoft"},
        ])
        self.assertEqual([s.name for s in store.sources()],
                         ["AIMO Parkering", "GITHUB", "Örn"])


class SourceIdTest(unittest.TestCase):
    def test_id_slugifieras_fran_namnet(self):
        created = new_source("Google Workspace", [])
        self.assertEqual(created.id, "google-workspace")
        self.assertEqual(created.filename_tag, "google-workspace")

    def test_krock_ger_suffix(self):
        existing = [source("google-workspace", [])]
        self.assertEqual(unique_source_id("Google Workspace", existing), "google-workspace-2")

    def test_omljud_forsvinner_ur_filnamnstaggen(self):
        created = new_source("Försäkring Länsförsäkringar", [])
        self.assertEqual(created.filename_tag, "forsakring-lansforsakringar")


if __name__ == "__main__":
    unittest.main()
