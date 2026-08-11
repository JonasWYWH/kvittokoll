"""HTTP-lagret: riktiga anrop mot en riktig server på en ledig port."""

import json
import shutil
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from helpers import ROOT, fixture_bytes, temp_store  # noqa: F401

from kvittokoll.server import create_server


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        store = temp_store(self.tmp)
        self.httpd = create_server(store, host="127.0.0.1", port=0)
        self.base = "http://127.0.0.1:{}".format(self.httpd.server_address[1])
        thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def call(self, method, path, body=None, headers=None):
        request = Request(
            self.base + path, data=body, method=method, headers=headers or {}
        )
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def json_call(self, method, path, payload):
        return self.call(
            method,
            path,
            json.dumps(payload).encode("utf-8"),
            {"Content-Type": "application/json"},
        )

    def upload(self, filename, data, profile_id=None):
        boundary = "----kvittokoll{}".format(uuid.uuid4().hex)
        parts = []
        if profile_id:
            parts.append(
                (
                    "--{}\r\nContent-Disposition: form-data; name=\"profile_id\"\r\n\r\n"
                    "{}\r\n".format(boundary, profile_id)
                ).encode("utf-8")
            )
        parts.append(
            (
                "--{}\r\nContent-Disposition: form-data; name=\"file\"; "
                'filename="{}"\r\nContent-Type: application/octet-stream\r\n\r\n'.format(
                    boundary, filename
                )
            ).encode("utf-8")
        )
        parts.append(data)
        parts.append("\r\n--{}--\r\n".format(boundary).encode("utf-8"))
        return self.call(
            "POST",
            "/api/import/preview",
            b"".join(parts),
            {"Content-Type": "multipart/form-data; boundary={}".format(boundary)},
        )

    # -- statiska filer ---------------------------------------------------

    def test_startsidan_serveras(self):
        with urlopen(self.base + "/", timeout=10) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("Kvittokoll", response.read().decode("utf-8"))

    def test_katalogtraversering_avvisas(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base + "/../app.py", timeout=10)
        self.assertIn(caught.exception.code, (403, 404))

    # -- api --------------------------------------------------------------

    def test_state_ar_tomt_fran_borjan(self):
        status, payload = self.call("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(payload["transactions"], [])
        self.assertTrue(any(p["id"] == "swedbank" for p in payload["profiles"]))

    def test_okand_vag_ger_404(self):
        with self.assertRaises(HTTPError) as caught:
            self.call("GET", "/api/finns-inte")
        self.assertEqual(caught.exception.code, 404)

    def test_hela_importflodet_over_http(self):
        status, preview = self.upload(
            "swedbank_sample.csv", fixture_bytes("swedbank_sample.csv")
        )
        self.assertEqual(status, 200)
        self.assertEqual(preview["summary"]["new"], 8)
        self.assertEqual(preview["summary"]["failed"], 2)

        status, committed = self.json_call(
            "POST", "/api/import/commit", {"token": preview["token"]}
        )
        self.assertEqual(committed["added"], 8)
        self.assertEqual(len(committed["transactions"]), 8)

    def test_id_med_lodstreck_overlever_url_kodning(self):
        _, preview = self.upload("s.csv", fixture_bytes("swedbank_sample.csv"))
        self.json_call("POST", "/api/import/commit", {"token": preview["token"]})
        _, state = self.call("GET", "/api/state")
        transaction_id = state["transactions"][0]["id"]
        self.assertIn("|", transaction_id)

        _, result = self.json_call(
            "PATCH",
            "/api/transactions/{}".format(quote(transaction_id, safe="")),
            {"requires_receipt": False, "note": "kollad"},
        )
        self.assertEqual(result["transaction"]["id"], transaction_id)
        self.assertEqual(result["transaction"]["status"], "not_required")
        self.assertEqual(result["transaction"]["note"], "kollad")

    def test_bulkvagen_krockar_inte_med_id_vagen(self):
        _, preview = self.upload("s.csv", fixture_bytes("swedbank_sample.csv"))
        self.json_call("POST", "/api/import/commit", {"token": preview["token"]})
        _, state = self.call("GET", "/api/state")
        ids = [row["id"] for row in state["transactions"][:2]]

        _, result = self.json_call(
            "PATCH", "/api/transactions/bulk", {"ids": ids, "changes": {"requires_receipt": False}}
        )
        self.assertEqual(len(result["updated"]), 2)

    def test_kallor_kan_redigeras_och_tas_bort_over_http(self):
        _, created = self.json_call("POST", "/api/sources", {"name": "Hyra kontor"})
        source_id = created["source"]["id"]

        _, updated = self.json_call(
            "PATCH",
            "/api/sources/{}".format(quote(source_id, safe="")),
            {"company": "Hyresvärden AB",
             "match_patterns": [{"pattern": "HYRA", "mode": "starts_with"}]},
        )
        self.assertEqual(updated["source"]["company"], "Hyresvärden AB")
        self.assertEqual(updated["source"]["match_patterns"],
                         [{"pattern": "HYRA", "mode": "starts_with"}])

        status, deleted = self.call("DELETE", "/api/sources/{}".format(quote(source_id, safe="")))
        self.assertEqual(status, 200)
        self.assertEqual(deleted["deleted"], source_id)

        _, state = self.call("GET", "/api/state")
        self.assertEqual(state["sources"], [])

    def test_fel_i_api_ger_json_inte_stacktrace(self):
        with self.assertRaises(HTTPError) as caught:
            self.json_call("POST", "/api/import/commit", {"token": "finns-inte"})
        payload = json.loads(caught.exception.read().decode("utf-8"))
        self.assertEqual(caught.exception.code, 404)
        self.assertIn("Ladda upp filen igen", payload["error"])

    def test_trasig_fil_ger_begripligt_fel(self):
        with self.assertRaises(HTTPError) as caught:
            self.upload("skrap.csv", b"det har ar inte en csv-fil\n")
        payload = json.loads(caught.exception.read().decode("utf-8"))
        self.assertEqual(caught.exception.code, 400)
        self.assertTrue(payload["error"])


if __name__ == "__main__":
    unittest.main()
