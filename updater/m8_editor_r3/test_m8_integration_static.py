import ast
import json
import tempfile
from unittest.mock import patch
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import build
import m8_editor_overlay as m8
import m8_candidate as candidate

MAIN_SAMPLE = '''import hashlib\ndef can_read_project(db: Session, project_id: str, user_id: str) -> bool:\n    return project_membership(db, project_id, user_id) is not None\n    memberships = set(db.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)).all())\n    latest_by_entity = {}\n@app.get("/sync/pull", response_model=SyncPullOut)\ndef sync_pull(): pass'''
APP_SAMPLE = "import { useAuth } from './auth/AuthContext'\n  // Az első snapshot egyszer fut; a további frissítéseket a felhasználó indítja.\n  // eslint-disable-next-line react-hooks/exhaustive-deps\n  useEffect(() => { void refresh(true).catch(() => undefined) }, [])"
API_SAMPLE = "export const getHealth = () => apiRequest<{ status: string }>('/health', {}, undefined, false)"

class M8StaticIntegrationTests(unittest.TestCase):
 def test_source_pins_and_generated_sources(self):
  for name,data in build.generate().items():
   self.assertEqual(data, (Path(build.ROOT)/'out'/name).read_bytes())
 def test_strict_anchor_failure(self):
  for fn in m8.PATCHERS.values():
   with self.assertRaisesRegex(ValueError, 'M8_ANCHOR_DRIFT|PINNED_ANCHOR_FAILED'):
    fn('unrelated')
 def test_backend_python_parses(self):
  self.assertTrue(ast.parse(m8.patch_main(MAIN_SAMPLE)))
 def test_no_unbounded_global_write(self):
  s=m8.patch_main(MAIN_SAMPLE)
  self.assertIn("viewer.role == 'editor'",s)
  self.assertIn('def access_scope(',s)
  self.assertNotIn("viewer.role == 'admin'",s)
  self.assertNotIn('can_write_project',s)
 def test_scope_fingerprint_no_project_identifier_leak_in_response(self):
  s=m8.patch_main(MAIN_SAMPLE)
  section=s[s.index('def access_scope('):s.index('@app.get("/sync/pull"')]
  self.assertIn("return {'fingerprint':",section)
  self.assertNotIn("return {'projects':",section)
 def test_frontend_timer_and_forced_snapshot(self):
  s=m8.patch_app(APP_SAMPLE)
  self.assertIn('window.setInterval(tick, 12_000)',s)
  self.assertIn('window.location.reload()',s)
  self.assertIn('await refresh(false)',s)
  self.assertIn('void refresh(true)',s)
  self.assertIn("window.removeEventListener('focus', tick)",s)
 def test_api_scope(self):
  self.assertIn('/sync/access-scope',m8.patch_api(API_SAMPLE))
 def test_dupe_rejected(self):
  with self.assertRaisesRegex(ValueError,'M8_ANCHOR_DRIFT'):
   m8.patch_api(m8.patch_api(API_SAMPLE))

 def _make_ancestry(self, root):
  state=Path(root)
  m5=state/'parity-m5.Krm2sA3i'
  m6=state/'parity-m6._sdfbhky'
  m7=state/'parity-m7-video.7bc9a74m'
  code=("import { useAuth } from './auth/AuthContext'\n"
        "  // Az első snapshot egyszer fut; a további frissítéseket a felhasználó indítja.\n"
        "  useEffect(() => { void refresh(true).catch(() => undefined) }, [])\n")
  for folder in (m5,m6,m7):
   (folder/'frontend/src').mkdir(parents=True)
   (folder/'frontend/src/App.tsx').write_text(code)
  (m6/'.m6-r9-source-receipt.json').write_text(json.dumps({
   'source':str(m5), 'status':'M6_R9_CANDIDATE_PREPARED_NOT_DEPLOYED',
   'production_modified':False,'modified':{f'server/{i}.py':str(i) for i in range(11)}
  }))
  return m5,m6,m7,{'source_m6':str(m6),'changed_files_sha256':{}}
 def test_app_provenance_three_exact_source_hashes(self):
  with tempfile.TemporaryDirectory() as temp:
   m5,m6,m7,receipt=self._make_ancestry(temp)
   with patch.object(candidate,'M5',m5),patch.object(candidate,'M6',m6),patch.object(candidate,'M7',m7):
    self.assertEqual(candidate.verified_app_pin(receipt),candidate.digest(m7/candidate.APP_REL))
 def test_app_provenance_detects_tampered_m7(self):
  with tempfile.TemporaryDirectory() as temp:
   m5,m6,m7,receipt=self._make_ancestry(temp)
   (m7/candidate.APP_REL).write_text('tampered')
   with patch.object(candidate,'M5',m5),patch.object(candidate,'M6',m6),patch.object(candidate,'M7',m7):
    with self.assertRaisesRegex(candidate.GateStop,'M7_APP_ANCESTOR_SHA_DRIFT'):
     candidate.verified_app_pin(receipt)
 def test_app_provenance_detects_tampered_m6(self):
  with tempfile.TemporaryDirectory() as temp:
   m5,m6,m7,receipt=self._make_ancestry(temp)
   (m6/candidate.APP_REL).write_text('tampered')
   with patch.object(candidate,'M5',m5),patch.object(candidate,'M6',m6),patch.object(candidate,'M7',m7):
    with self.assertRaisesRegex(candidate.GateStop,'M7_APP_ANCESTOR_SHA_DRIFT'):
     candidate.verified_app_pin(receipt)
 def test_app_provenance_detects_false_receipt(self):
  with tempfile.TemporaryDirectory() as temp:
   m5,m6,m7,receipt=self._make_ancestry(temp)
   receipt['changed_files_sha256'][candidate.APP_REL]='a'*64
   with patch.object(candidate,'M5',m5),patch.object(candidate,'M6',m6),patch.object(candidate,'M7',m7):
    with self.assertRaisesRegex(candidate.GateStop,'M7_APP_ANCESTRY_RECEIPT_INVALID'):
     candidate.verified_app_pin(receipt)

if __name__=='__main__': unittest.main()
