import unittest

from helpers import ROOT  # noqa: F401  (lägger projektroten på sys.path)

from kvittokoll.normalize import (
    ParseError,
    format_amount,
    normalize_text,
    parse_amount,
    parse_date,
    slugify,
)


class TestNormalizeText(unittest.TestCase):
    def test_versaler_och_kollapsade_mellanslag(self):
        self.assertEqual(
            normalize_text("NETLIFY               SAN FRANCISCO"),
            "NETLIFY SAN FRANCISCO",
        )

    def test_specialtecken_blir_mellanslag(self):
        self.assertEqual(normalize_text("ANTHROPIC* CLAUDE SUB"), "ANTHROPIC CLAUDE SUB")
        self.assertEqual(normalize_text("Google Workspace_ab"), "GOOGLE WORKSPACE AB")

    def test_svenska_tecken_fallas_ihop(self):
        self.assertEqual(normalize_text("Försäkring Åhléns"), "FORSAKRING AHLENS")

    def test_tomt_ger_tom_strang(self):
        self.assertEqual(normalize_text(None), "")
        self.assertEqual(normalize_text(""), "")


class TestSlugify(unittest.TestCase):
    def test_gemener_bindestreck_inga_omljud(self):
        self.assertEqual(slugify("Google Workspace"), "google-workspace")
        self.assertEqual(slugify("Försäkring AB"), "forsakring-ab")

    def test_maxlangd_klipper_utan_avslutande_bindestreck(self):
        result = slugify("A" * 30 + " " + "B" * 30, max_length=40)
        self.assertLessEqual(len(result), 40)
        self.assertFalse(result.endswith("-"))


class TestParseAmount(unittest.TestCase):
    def test_punkt_som_decimaltecken(self):
        self.assertEqual(parse_amount("-1256.09", ".", ""), -1256.09)

    def test_komma_som_decimaltecken_och_blanksteg_som_tusental(self):
        self.assertEqual(parse_amount("1 234 567,89", ",", " "), 1234567.89)

    def test_efterstallt_minus(self):
        self.assertEqual(parse_amount("449,00-", ",", ""), -449.00)

    def test_parenteser_betyder_negativt(self):
        self.assertEqual(parse_amount("(449.00)", ".", ""), -449.00)

    def test_hard_space_som_tusentalsavgransare(self):
        self.assertEqual(parse_amount("1 234,50", ",", " "), 1234.50)

    def test_otolkbart_belopp_ger_parseerror(self):
        with self.assertRaises(ParseError):
            parse_amount("tolv kronor", ".", "")

    def test_tomt_belopp_ger_parseerror(self):
        with self.assertRaises(ParseError):
            parse_amount("", ".", "")


class TestFormatAmount(unittest.TestCase):
    def test_tva_decimaler_och_punkt(self):
        self.assertEqual(format_amount(-1256.09), "-1256.09")
        self.assertEqual(format_amount(449), "449.00")

    def test_negativ_nolla_blir_nolla(self):
        self.assertEqual(format_amount(-0.0), "0.00")


class TestParseDate(unittest.TestCase):
    def test_iso(self):
        self.assertEqual(parse_date("2026-08-11", "%Y-%m-%d"), "2026-08-11")

    def test_annat_format(self):
        self.assertEqual(parse_date("11.08.2026", "%d.%m.%Y"), "2026-08-11")

    def test_iso_accepteras_aven_med_annat_deklarerat_format(self):
        self.assertEqual(parse_date("2026-08-11", "%d.%m.%Y"), "2026-08-11")

    def test_skrap_ger_parseerror(self):
        with self.assertRaises(ParseError):
            parse_date("inte-ett-datum", "%Y-%m-%d")


if __name__ == "__main__":
    unittest.main()
