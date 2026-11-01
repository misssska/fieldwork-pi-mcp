import ast, hashlib, pathlib, unittest, zipfile, sys
sys.path.insert(0,str(pathlib.Path(__file__).parent))
import build

class EditorTeamOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.outputs=build.generate()

    def test_source_pins(self):
        with zipfile.ZipFile(build.SRC) as zip:
            for f,digest in build.PINS.items():
                self.assertEqual(build.sha(zip.read(build.SOURCE_PREFIX+f)),digest)

    def test_no_implicit_global_admin_override(self):
        sample='''def can_read_project(db: Session, project_id: str, user_id: str) -> bool:
    return project_membership(db, project_id, user_id) is not None
    memberships = set(db.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)).all())
    latest_by_entity = {}'''
        result=build.main_py(sample)
        self.assertIn("viewer.role == 'editor'",result)
        self.assertNotIn("viewer.role == 'admin'",result)
        self.assertIn("user.role == 'editor'",result)
        self.assertIn('project_membership(db, project_id, user_id) is not None',result)

    def test_patch_fail_closed(self):
        for f,patch in build.PATCHERS.items():
            with self.assertRaisesRegex(ValueError,'PINNED_ANCHOR_FAILED'):
                patch('unexpected changed source')

    def test_python_parses(self):
        for f in ['team_api.py','account_api.py']:
            ast.parse(self.outputs[f],filename=f)

    def test_member_candidates_only_owner(self):
        s=self.outputs['team_api.py'].decode()
        self.assertIn('def candidates(',s)
        region=s[s.index('def candidates('):s.index("@app.get('/team/projects/{project_id}/members')")]
        self.assertIn('require_manager(db, project_id, user)',region)
        self.assertIn('User.active.is_(True)',region)
        self.assertIn('User.id.not_in(active_members)',region)

    def test_identity_mode_exclusive(self):
        s=self.outputs['team_api.py'].decode()
        self.assertIn('if (body.email is None) == (body.user_id is None)',s)
        self.assertIn('if body.user_id is not None:',s)
        self.assertIn('status_code=201',s)

    def test_global_role_only_admin_and_not_admin_changed(self):
        s=self.outputs['account_api.py'].decode()
        self.assertIn('require_admin(user)',s[s.index("@app.patch('/team/accounts/{account_id}/role')"):])
        self.assertIn("if target.role == 'admin'",s)
        self.assertIn("Literal['worker', 'editor']",s)
        self.assertNotIn("Literal['admin'",s)

    def test_ui_selects_by_id_not_email(self):
        s=self.outputs['ReferenceTeam.tsx'].decode()
        self.assertIn('getCandidates(selectedProjectId)',s)
        self.assertIn('addMemberById(selectedProjectId,picked,role)',s)
        self.assertIn('type="search"',s)
        self.assertNotIn('addMember(selectedProjectId,email.trim()',s)
        self.assertIn('changeGlobalRole(person.id',s)

    def test_client_member_legacy_kept(self):
        s=self.outputs['TeamDirectory.ts'].decode()
        self.assertIn('export const addMember =',s)
        self.assertIn('export const addMemberById =',s)
        self.assertIn('export const changeGlobalRole',s)

    def test_read_only_editor_not_write_all(self):
        s=build.main_py('''def can_read_project(db: Session, project_id: str, user_id: str) -> bool:
    return project_membership(db, project_id, user_id) is not None
    memberships = set(db.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)).all())
    latest_by_entity = {}''')
        self.assertNotIn('def can_write_project',s)
        self.assertNotIn("can_write_project(db, project_id, user_id):\n    return True",s)

if __name__=='__main__':unittest.main()
