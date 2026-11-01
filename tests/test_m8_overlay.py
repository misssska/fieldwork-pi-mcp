import importlib.util
import hashlib
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent
MODULE_DIR = ROOT if (ROOT/'m8_security_overlay.py').is_file() else ROOT.parent/'updater/m8_security'
sys.path.insert(0,str(MODULE_DIR))
from m8_security_overlay import (once, PatchStop, main_patch, team_patch,
                                 app_patch, api_patch, projects_patch,
                                 old_team_test_patch, PATCHERS, apply)

class M8NegativeSourceGate(unittest.TestCase):
    def test_allowlist_exact(self):
        self.assertEqual(set(PATCHERS),{
            'server/app/main.py','server/app/team_api.py',
            'server/tests/test_team_m4.py','frontend/src/api/fieldwork.ts',
            'frontend/src/App.tsx','frontend/src/components/Projects.tsx'})
    def test_strict_anchor_missing(self):
        with self.assertRaisesRegex(PatchStop,'M8_ANCHOR_MISMATCH'):
            once('alpha','beta','gamma','tamper')
    def test_strict_anchor_duplicate(self):
        with self.assertRaisesRegex(PatchStop,'M8_ANCHOR_MISMATCH'):
            once('x x','x','y','duplicate')
    def test_no_unapproved_path(self):
        with self.assertRaisesRegex(PatchStop,'M8_NON_ALLOWLIST_FILE'):
            apply('/opt/fieldwork/server/app/main.py',b'irrelevant')
    def test_team_exact_real_module(self):
        # CI repo path vs local package source.
        candidates=[MODULE_DIR/'team_api.py',ROOT.parent/'fieldwork_stabledev_m6/src/team_api.py']
        base=next((p for p in candidates if p.is_file()),None)
        self.assertIsNotNone(base)
        raw=base.read_text()
        self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(),
                         'cf1db461dd8c4fec2b055bf4c72837d50bcefd79f8b83559431d85c06e6eabe8')
        output=team_patch(raw)
        self.assertIn("user.role == 'admin'",output)
        self.assertIn("Project.id).where(Project.deleted.is_(False)",output)
        compile(output,'server/app/team_api.py','exec')
    def test_team_legacy_test_exact(self):
        candidates=[MODULE_DIR/'test_team_m4.py',ROOT.parent/'fieldwork_stabledev_m6/src/test_team_m4.py']
        base=next((p for p in candidates if p.is_file()),None)
        self.assertIsNotNone(base)
        raw=base.read_text()
        self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(),
                         '49139da653c5486a3463ed762271f144c79bd8b825352610d1e9b782cd1ac254')
        after=old_team_test_patch(raw)
        self.assertIn('System admin must be able',after)
        compile(after,'server/tests/test_team_m4.py','exec')
    def test_main_admin_and_root_gates(self):
        src='''def can_write_project(db: Session, project_id: str, user_id: str) -> bool:
    membership = project_membership(db, project_id, user_id)
    return bool(membership and membership.role in PROJECT_ROLES_WRITE)

def can_read_project(db: Session, project_id: str, user_id: str) -> bool:
    return project_membership(db, project_id, user_id) is not None

    if cls is Project:
        if obj:
            writable_project(db, obj.id, user_id)
        return validate_project_data(db, data, entity_id, user_id, obj), entity_id

    memberships = set(db.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)).all())
    latest_by_entity = {}

@app.get("/sync/pull", response_model=SyncPullOut)'''
        result=main_patch(src)
        self.assertIn('if not system_admin(db, user_id)',result)
        self.assertIn('def sync_access_scope',result)
        self.assertIn('if user.role == "admin" and user.active',result)
        self.assertIn('return system_admin(db, user_id) or',result)
        with self.assertRaisesRegex(PatchStop,'main-system-admin'):
            main_patch(src.replace('membership.role in PROJECT_ROLES_WRITE','membership.role in ("viewer", "editor")'))
    def test_api_scope_anchor(self):
        s='export const pullChanges = (cursor: number, limit = 1000) => apiRequest<PullResponse>(`/sync/pull?cursor=${cursor}&limit=${limit}`)'
        self.assertIn('getAccessScope',api_patch(s))
    def test_app_polling_replaces_only_old_manual_refresh(self):
        s="""import { FieldworkProvider, useFieldwork } from './data/FieldworkContext'
  // Az első snapshot egyszer fut; a további frissítéseket a felhasználó indítja.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void refresh(true).catch(() => undefined) }, [])"""
        a=app_patch(s)
        self.assertIn('window.setInterval',a)
        self.assertIn('inFlight',a)
        self.assertIn('priorScope !== fingerprint',a)
        self.assertIn('visibilitychange',a)
        self.assertIn('clearInterval',a)
    def test_project_root_ui(self):
        s='''import { Modal } from './Modal'
export function Projects({ search = '' }: { search?: string }) {
<button className="primary" onClick={() => { setParentForNew(null); setEditing(null) }}>+ Új projekt</button>'''
        result=projects_patch(s)
        self.assertIn('canCreateRoot && <button',result)
    def test_backend_new_regression_test_valid_syntax(self):
        p=MODULE_DIR/'test_security_m8.py'
        self.assertTrue(p.is_file())
        compile(p.read_text(),'test_security_m8.py','exec')

if __name__=='__main__': unittest.main()
