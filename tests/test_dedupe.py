"""Dubblettlogiken — den del där ett fel kostar mest.

Antingen försvinner en riktig transaktion (för aggressiv dedup) eller så växer
listan varje gång man importerar om samma period (för slapp dedup).
"""

import unittest

from helpers import ROOT  # noqa: F401

from kvittokoll.dedupe import assign_ids, base_key, make_id


def row(date, amount, description, **extra):
    data = {"date": date, "amount": amount, "description": description}
    data.update(extra)
    return data


class TestBaseKey(unittest.TestCase):
    def test_nyckelns_format(self):
        self.assertEqual(
            base_key("2026-03-14", -449.0, "GOOGLE *WORKSPACE_ABC"),
            "2026-03-14|-449.00|GOOGLE WORKSPACE ABC",
        )

    def test_id_med_lopnummer(self):
        self.assertEqual(
            make_id(base_key("2026-03-14", -449.0, "GOOGLE WORKSPACE"), 1),
            "2026-03-14|-449.00|GOOGLE WORKSPACE|1",
        )


class TestAssignIds(unittest.TestCase):
    def test_tom_databas_ger_allt_som_nytt(self):
        rows = [row("2026-08-11", -242.22, "ANTHROPIC IRELAND")]
        new, known = assign_ids(rows, [])
        self.assertEqual(len(new), 1)
        self.assertEqual(len(known), 0)
        self.assertEqual(new[0]["id"], "2026-08-11|-242.22|ANTHROPIC IRELAND|1")

    def test_tva_identiska_kop_samma_dag_ger_tva_rader(self):
        rows = [
            row("2026-08-10", -1256.09, "ANTHROPIC* CLAUDE SUB SAN FRANCISCO"),
            row("2026-08-10", -1256.09, "ANTHROPIC* CLAUDE SUB SAN FRANCISCO"),
        ]
        new, known = assign_ids(rows, [])
        self.assertEqual(len(new), 2)
        self.assertEqual(
            [r["id"].rsplit("|", 1)[1] for r in new], ["1", "2"]
        )

    def test_omimport_av_samma_fil_ger_noll_nya(self):
        rows = [
            row("2026-08-10", -1256.09, "ANTHROPIC* CLAUDE SUB"),
            row("2026-08-10", -1256.09, "ANTHROPIC* CLAUDE SUB"),
            row("2026-08-11", -242.22, "ANTHROPIC IRELAND"),
        ]
        first, _ = assign_ids(rows, [])
        second, known = assign_ids(rows, [r["id"] for r in first])
        self.assertEqual(second, [])
        self.assertEqual(len(known), 3)

    def test_overlappande_export_importerar_bara_differensen(self):
        """Tre dragningar samma dag när två redan finns lagrade."""
        stored = [
            row("2026-08-10", -1256.09, "ANTHROPIC* CLAUDE SUB"),
            row("2026-08-10", -1256.09, "ANTHROPIC* CLAUDE SUB"),
        ]
        first, _ = assign_ids(stored, [])

        larger_export = stored + [row("2026-08-10", -1256.09, "ANTHROPIC* CLAUDE SUB")]
        new, known = assign_ids(larger_export, [r["id"] for r in first])
        self.assertEqual(len(new), 1)
        self.assertEqual(len(known), 2)
        self.assertTrue(new[0]["id"].endswith("|3"))

    def test_olika_stavning_samma_transaktion_ar_samma_nyckel(self):
        rows_a = [row("2026-08-10", -19.40, "Google CLOUD  46DG53")]
        rows_b = [row("2026-08-10", -19.40, "GOOGLE*CLOUD 46DG53")]
        first, _ = assign_ids(rows_a, [])
        new, known = assign_ids(rows_b, [r["id"] for r in first])
        self.assertEqual(new, [])
        self.assertEqual(len(known), 1)

    def test_bankens_eget_id_anvands_nar_det_finns(self):
        rows = [row("2026-03-14", -449.0, "GOOGLE WORKSPACE", bank_id="SWD-0001")]
        new, _ = assign_ids(rows, [])
        self.assertEqual(new[0]["id"], "SWD-0001")

        again, known = assign_ids(rows, ["SWD-0001"])
        self.assertEqual(again, [])
        self.assertEqual(len(known), 1)

    def test_bankens_id_skiljer_identiska_belopp_samma_dag(self):
        rows = [
            row("2026-03-14", -449.0, "GOOGLE WORKSPACE", bank_id="A1"),
            row("2026-03-14", -449.0, "GOOGLE WORKSPACE", bank_id="A2"),
        ]
        new, _ = assign_ids(rows, [])
        self.assertEqual(sorted(r["id"] for r in new), ["A1", "A2"])

    def test_lasordningen_bevaras(self):
        rows = [
            row("2026-08-11", -1.0, "A"),
            row("2026-08-10", -2.0, "B"),
            row("2026-08-09", -3.0, "C"),
        ]
        new, _ = assign_ids(rows, [])
        self.assertEqual([r["description"] for r in new], ["A", "B", "C"])

    def test_intern_nyckel_lacker_inte_ut(self):
        new, known = assign_ids([row("2026-08-11", -1.0, "A")], [])
        self.assertNotIn("_order", new[0])


if __name__ == "__main__":
    unittest.main()
