"""Filhantering: atomiska skrivningar, backup, statusberäkning."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, temp_store  # noqa: F401

from kvittokoll.models import Receipt, Transaction
from kvittokoll.storage import write_json_atomic


class AtomicWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.tmp), True)

    def test_skriver_och_laser_tillbaka(self):
        target = self.tmp / "data" / "transactions.json"
        write_json_atomic(target, [{"id": "a"}])
        with target.open(encoding="utf-8") as stream:
            self.assertEqual(json.load(stream), [{"id": "a"}])

    def test_inga_temporarfiler_lamnas_kvar(self):
        target = self.tmp / "x.json"
        write_json_atomic(target, {"a": 1})
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["x.json"])

    def test_misslyckad_skrivning_lamnar_originalet_orort(self):
        target = self.tmp / "x.json"
        write_json_atomic(target, {"version": 1})

        class Osparbar:
            pass

        with self.assertRaises(TypeError):
            write_json_atomic(target, {"trasig": Osparbar()})

        with target.open(encoding="utf-8") as stream:
            self.assertEqual(json.load(stream), {"version": 1})
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["x.json"])

    def test_aao_skrivs_som_tecken_inte_escapesekvenser(self):
        target = self.tmp / "x.json"
        write_json_atomic(target, {"name": "Försäkring"})
        self.assertIn("Försäkring", target.read_text(encoding="utf-8"))


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.store = temp_store(self.tmp)

    def test_ingen_backup_utan_fil(self):
        self.assertIsNone(self.store.backup_transactions())

    def test_backup_kopierar_innehallet(self):
        self.store.save_transactions([_transaction("a")])
        backup = self.store.backup_transactions()
        self.assertIsNotNone(backup)
        with Path(backup).open(encoding="utf-8") as stream:
            self.assertEqual(json.load(stream)[0]["id"], _transaction("a").id)

    def test_tva_backuper_samma_sekund_krockar_inte(self):
        self.store.save_transactions([_transaction("a")])
        first = self.store.backup_transactions()
        second = self.store.backup_transactions()
        self.assertNotEqual(first, second)
        self.assertTrue(Path(first).exists() and Path(second).exists())


class TrashTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.store = temp_store(self.tmp)

    def test_fil_flyttas_istallet_for_att_raderas(self):
        victim = self.tmp / "kvitto.pdf"
        victim.write_bytes(b"%PDF-1.4")
        moved = self.store.move_to_trash(victim)
        self.assertFalse(victim.exists())
        self.assertTrue(Path(moved).exists())
        self.assertEqual(Path(moved).read_bytes(), b"%PDF-1.4")


class StatusTest(unittest.TestCase):
    def test_statusen_foljer_av_faltens_varden(self):
        transaction = _transaction("a")
        self.assertEqual(transaction.compute_status(), "missing")

        transaction.receipts = [Receipt(original_filename="f.pdf")]
        self.assertEqual(transaction.compute_status(), "has_receipt")

        transaction.sent_at = "2026-08-11T10:00:00+02:00"
        self.assertEqual(transaction.compute_status(), "sent")

        transaction.requires_receipt = False
        self.assertEqual(transaction.compute_status(), "not_required")

    def test_not_required_ar_inte_en_radering(self):
        transaction = _transaction("a")
        transaction.requires_receipt = False
        data = transaction.to_dict()
        self.assertEqual(data["status"], "not_required")
        restored = Transaction.from_dict(data)
        restored.requires_receipt = True
        self.assertEqual(restored.compute_status(), "missing")

    def test_rundtur_genom_json_bevarar_faltena(self):
        transaction = _transaction("a")
        transaction.receipts = [Receipt("orig.pdf", "ny.pdf", "receipts/2026-08/ny.pdf", "nu")]
        transaction.note = "kolla momsen"
        restored = Transaction.from_dict(json.loads(json.dumps(transaction.to_dict())))
        self.assertEqual(restored.receipts[0].original_filename, "orig.pdf")
        self.assertEqual(restored.note, "kolla momsen")
        self.assertEqual(restored.base_key, transaction.base_key)


def _transaction(suffix):
    return Transaction(
        id="2026-08-11|-100.00|TEST|{}".format(suffix),
        date="2026-08-11",
        amount=-100.0,
        description="TEST",
    )


if __name__ == "__main__":
    unittest.main()
