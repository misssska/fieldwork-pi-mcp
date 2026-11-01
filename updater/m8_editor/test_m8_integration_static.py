import ast
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import build
import m8_editor_overlay as m8

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

if __name__=='__main__': unittest.main()
