"""Import av en riktig bankexport.

Testet körs bara om det ligger en exportfil i ``Transactions/``. Filen ingår
inte i repot — den innehåller riktiga transaktioner. Poängen är att kunna köra
dubblettlogiken mot skarp data innan den släpps lös på resten av bygget.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, temp_store  # noqa: F401

from kvittokoll import importer

EXPORTS = sorted((ROOT / "Transactions").glob("*.csv")) if (ROOT / "Transactions").exists() else []


@unittest.skipUnless(EXPORTS, "ingen exportfil i Transactions/")
class RealExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.store = temp_store(self.tmp)
        self.path = EXPORTS[-1]
        self.data = self.path.read_bytes()

    def preview(self):
        return importer.preview(self.store, self.path.name, self.data)

    def test_hela_filen_tolkas_utan_fel(self):
        result = self.preview()
        self.assertEqual(
            result["summary"]["failed"],
            0,
            "otolkbara rader: {}".format(result["errors"]),
        )
        self.assertGreater(result["summary"]["parsed"], 0)

    def test_varje_rad_far_ett_unikt_id(self):
        rows = self.preview()["rows"]
        ids = [row["id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)))

    def test_omimport_ger_noll_nya(self):
        importer.commit(self.store, self.preview())
        count = len(self.store.transactions())
        again = self.preview()
        self.assertEqual(again["summary"]["new"], 0)
        self.assertEqual(again["summary"]["known"], count)

    def test_saldot_stammer_mellan_raderna(self):
        """Saldot ska gå ihop rad för rad.

        Swedbank skriver nyast först, och saldot på en rad är saldot *efter*
        den transaktionen. Alltså: saldo[i] - saldo[i+1] == belopp[i], i
        filens egen ordning. Håller det för hela filen är tecken,
        decimaltolkning och kolumnmappning bevisligen rätt.
        """
        result = self.preview()
        self.assertEqual(result["summary"]["failed"], 0, "kedjan bryts av otolkade rader")
        rows = result["rows"]
        checked = 0
        for newer, older in zip(rows, rows[1:]):
            if newer["balance"] is None or older["balance"] is None:
                continue
            self.assertAlmostEqual(
                newer["balance"] - older["balance"],
                newer["amount"],
                places=2,
                msg="saldot går inte ihop vid {} ({})".format(
                    newer["date"], newer["description"]
                ),
            )
            checked += 1
        self.assertGreater(checked, 0, "hittade inga jämförbara rader")


if __name__ == "__main__":
    unittest.main()
