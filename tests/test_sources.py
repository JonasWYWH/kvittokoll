"""Källmatchning (§4.3) — inklusive fallet som motiverar hela entiteten:
Google Workspace och Google Cloud är två källor med snarlik banktext.
"""

import unittest

from helpers import ROOT  # noqa: F401

from kvittokoll.models import Source
from kvittokoll.sources import match_source, new_source, unique_source_id


def source(source_id, patterns, **extra):
    return Source(id=source_id, name=source_id, match_patterns=patterns, **extra)


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
