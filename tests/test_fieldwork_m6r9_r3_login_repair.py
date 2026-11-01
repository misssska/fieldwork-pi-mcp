"""Offline M6 R3 regression tests; never touch a real Pi or Docker."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from updater import fieldwork_m6r9_r3_repair_and_test as g

ORIGINAL = ("await userEvent.type(screen.getByLabelText('Admin e-mail'), 'admin@example.test')\n"*2).encode()

class R3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stage = Path(self.tmp.name)/"stage-v06"
        self.stage.mkdir()
        self.base = self.stage/"parity-m5.Krm2sA3i"
        self.base.mkdir()
        self.candidate = self.stage/"parity-m6._sdfbhky"
        self.candidate.mkdir()
        self.testfile = self.candidate/"frontend/src/components/Login.test.tsx"
        self.testfile.parent.mkdir(parents=True)
        self.testfile.write_bytes(ORIGINAL)
        self.old = self.base/"frontend/src/components/Login.test.tsx"
        self.old.parent.mkdir(parents=True)
        self.old.write_bytes(ORIGINAL)
        ui = self.candidate/"frontend/src/components/Login.tsx"
        ui.write_text("E-mail vagy felhasználónév",encoding="utf-8")
        (self.candidate/"docker-compose.m4-test-v4.yml").write_text("test")
        (self.candidate/".m6-r9-source-receipt.json").write_text(json.dumps({
            "source":str(self.base),"candidate":str(self.stage/".parity-m6-preparing._sdfbhky"),
            "status":"M6_R9_CANDIDATE_PREPARED_NOT_DEPLOYED",
            "production_modified":False
        }))
        for name,val in (("STATE",self.stage),("BASE",self.base),("CANDIDATE",self.candidate),
                         ("TESTFILE_SHA_BEFORE",hashlib.sha256(ORIGINAL).hexdigest())):
            ctx=patch.object(g,name,val);ctx.start();self.addCleanup(ctx.stop)

    def test_exact_replacement(self):
        changed=g.amended_bytes(ORIGINAL)
        self.assertEqual(changed.count(g.NEW_LABEL.encode()),2)
        self.assertNotIn(g.OLD_LABEL.encode(),changed)
        self.assertEqual(changed.replace(g.NEW_LABEL.encode(),g.OLD_LABEL.encode()),ORIGINAL)

    def test_hash_drift_denied(self):
        with self.assertRaisesRegex(RuntimeError,"EXPECTED_SHA_MISMATCH"):
            g.amended_bytes(ORIGINAL+b"evil")

    def test_anchor_drift_denied(self):
        changed=ORIGINAL.replace(g.OLD_LABEL.encode(),b"wrong")
        with patch.object(g,"TESTFILE_SHA_BEFORE",hashlib.sha256(changed).hexdigest()):
            with self.assertRaisesRegex(RuntimeError,"EXACT_TWO_ANCHORS_REQUIRED"):
                g.amended_bytes(changed)

    def test_copy_then_patch_backup_preserves_original(self):
        g.patch_test(self.testfile)
        self.assertEqual(self.testfile.read_bytes(),g.amended_bytes(ORIGINAL))
        self.assertEqual(self.testfile.with_name("Login.test.tsx.m6-r3-original.bak").read_bytes(),ORIGINAL)
        with self.assertRaisesRegex(RuntimeError,"EXPECTED_SHA_MISMATCH"):
            g.patch_test(self.testfile)

    def test_composition_rejects_public_db(self):
        cfg={"services":{"test-db":{"tmpfs":["/db"],"ports":["5432:5432"]},
                         "backend-tests":{"environment":{"FIELDWORK_TESTING":"1",
                         "FIELDWORK_TEST_DATABASE_URL":"postgresql://x:x@test-db:5432/x"}}}}
        with patch.object(g.subprocess,"run",return_value=subprocess.CompletedProcess([],0,json.dumps(cfg),"")):
            with self.assertRaisesRegex(RuntimeError,"COMPOSE_UNSAFE_SERVICE"):
                g.compose_guard()

if __name__=="__main__":
    unittest.main()
