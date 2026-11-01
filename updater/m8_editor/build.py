from __future__ import annotations
import hashlib, json, pathlib, zipfile
ROOT=pathlib.Path(__file__).parent
SRC=ROOT/'baseline_sources.zip'
SOURCE_PREFIX=''
PINS={
 'team_api.py':'cf1db461dd8c4fec2b055bf4c72837d50bcefd79f8b83559431d85c06e6eabe8',
 'ReferenceTeam.tsx':'e89e7bc40b597389b5323c6073fdc1811108d33a0142a05fbb82b6dac30e0218',
 'TeamDirectory.ts':'80340cf537d596afba23a8dfa61d1446f8291f83651e59272180115db4ada0e5',
 'account_api.py':'ad40c32ba8196da6a9db54b9c3ebeca7342a216439e2a34d1bb0b8fc66eb068a',
}
def sha(data):return hashlib.sha256(data).hexdigest()
def once(s,old,new,label):
 if s.count(old)!=1: raise ValueError(f'PINNED_ANCHOR_FAILED:{label}:found={s.count(old)}')
 return s.replace(old,new,1)
def team_api(s):
 s=once(s,'''class MembershipIn(BaseModel):
    email: EmailStr
    role: str = Field(pattern='^(owner|editor|viewer)$')''', '''class MembershipIn(BaseModel):
    # Exactly one address mode: stable UUID from the approved project-owner list,
    # or legacy email. Keeping the old form preserves existing mobile clients.
    email: EmailStr | None = None
    user_id: str | None = Field(default=None, max_length=36)
    role: str = Field(pattern='^(owner|editor|viewer)$')''','membership-model')
 anchor="    @app.get('/team/projects/{project_id}/members')"
 code="""    @app.get('/team/projects/{project_id}/candidates')
    def candidates(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
        # A membership grant can enumerate eligible accounts only for project owners.
        require_manager(db, project_id, user)
        active_members = select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)
        entries = list(db.scalars(select(User).where(User.active.is_(True),
            User.id.not_in(active_members)).order_by(User.name, User.email)))
        return {'users': [{'id': person.id, 'name': person.name, 'email': person.email}
                          for person in entries]}

"""
 s=once(s,anchor,code+anchor,'candidate-endpoint')
 s=once(s,'''        person = db.scalar(select(User).where(User.email == str(body.email), User.active.is_(True)))
        if person is None:''','''        if (body.email is None) == (body.user_id is None):
            raise HTTPException(422, 'Pontosan egy azonosító vagy e-mail-cím szükséges')
        if body.user_id is not None:
            # Never trust a supplied id from the browser without owner authorization.
            person = db.scalar(select(User).where(User.id == body.user_id, User.active.is_(True)))
        else:
            person = db.scalar(select(User).where(User.email == str(body.email), User.active.is_(True)))
        if person is None:''','member-resolve')
 return s

def account_api(s):
 s=once(s,'from pydantic import BaseModel, EmailStr, Field, SecretStr','from pydantic import BaseModel, EmailStr, Field, SecretStr\nfrom typing import Literal','account-literal')
 s=once(s,'def register_account_routes(app, current_user):', '''class AccountRoleChange(BaseModel):
    # A global reader must be provisioned explicitly by a system admin.
    role: Literal['worker', 'editor']


def register_account_routes(app, current_user):''','account-role-model')
 anchor="    @app.post('/team/accounts', status_code=201)"
 code="""    @app.patch('/team/accounts/{account_id}/role')
    def change_global_view_scope(account_id: str, body: AccountRoleChange,
                                 user: User = Depends(current_user), db: Session = Depends(get_db)):
        require_admin(user)
        target = db.get(User, account_id)
        if target is None or not target.active:
            raise HTTPException(404, 'Nincs ilyen aktív felhasználó')
        if target.role == 'admin':
            raise HTTPException(403, 'Rendszergazdai szerepkör itt nem változtatható')
        target.role = body.role
        db.commit()
        db.refresh(target)
        return describe(target)

"""
 return once(s,anchor,code+anchor,'account-role-route')

def team_ts(s):
 s=once(s,'''export const getMembers = (projectId: string) => apiRequest<{ can_manage: boolean; members: TeamMember[] }>(`/team/projects/${encodeURIComponent(projectId)}/members`)''', '''export const getMembers = (projectId: string) => apiRequest<{ can_manage: boolean; members: TeamMember[] }>(`/team/projects/${encodeURIComponent(projectId)}/members`)
export const getCandidates = (projectId: string) => apiRequest<{ users: Array<Pick<TeamPerson, 'id' | 'name' | 'email'>> }>(`/team/projects/${encodeURIComponent(projectId)}/candidates`)
export const addMemberById = (projectId: string, userId: string, role: TeamMember['role']) =>
  apiRequest<TeamMember>(`/team/projects/${encodeURIComponent(projectId)}/members`, {method: 'POST', body: JSON.stringify({user_id:userId, role})})
export const changeGlobalRole = (userId: string, role: 'worker' | 'editor') =>
  apiRequest<Account>(`/team/accounts/${encodeURIComponent(userId)}/role`, {method:'PATCH',body:JSON.stringify({role})})''','front-api')
 return s

def team_view(s):
 s=once(s,"import { addMember, changeMember, createAccount, getMembers, removeMember, useTeamDirectory, type TeamMember } from './TeamDirectory'", "import { addMemberById, changeMember, changeGlobalRole, createAccount, getCandidates, getMembers, removeMember, useTeamDirectory, type TeamMember } from './TeamDirectory'", 'front-import')
 s=once(s,"  const [email,setEmail] = useState('')", "  const [search,setSearch] = useState('')\n  const [picked,setPicked] = useState('')\n  const [candidates,setCandidates] = useState<Array<{id:string; name:string; email:string}>>([])",'front-states')
 s=once(s,"""    getMembers(selectedProjectId).then(value=>{if(active){setMembership(value);setError('');setLoading(false)}})
      .catch(caught=>{if(active){setError(caught instanceof Error?caught.message:'A taglista nem tölthető be.');setLoading(false)}})""", """    setMembership({can_manage:false,members:[]});setCandidates([]);setPicked('')
    getMembers(selectedProjectId).then(async value=>{
      if (!active) return
      setMembership(value)
      if (value.can_manage) {
        const result=await getCandidates(selectedProjectId)
        if(active) setCandidates(result.users)
      }
      if(active){setError('');setLoading(false)}
    }).catch(caught=>{if(active){setError(caught instanceof Error?caught.message:'A taglista nem tölthető be.');setLoading(false)}})""",'front-load')
 s=once(s,"""    if(!selectedProjectId||!email.trim()) return
    void transact(async()=>{await addMember(selectedProjectId,email.trim(),role);setEmail('')})""", """    if(!selectedProjectId||!picked) return
    void transact(async()=>{await addMemberById(selectedProjectId,picked,role);setPicked('');setSearch('')})""",'front-add')
 s=once(s,"""      <label>E-mail-cím <input type="email" autoComplete="off" required value={email} onChange={event=>setEmail(event.target.value)} placeholder="felhasznalo@ceg.hu"/></label>""", """      <label>Felhasználó keresése <input type="search" value={search} onChange={event=>{setSearch(event.target.value);setPicked('')}} placeholder="Név vagy e-mail keresése"/></label>
      <label>Meglévő fiók kiválasztása <select aria-label="Meglévő felhasználó" required value={picked} onChange={event=>setPicked(event.target.value)}>
        <option value="">Válassz a találatokból…</option>
        {candidates.filter(person=>`${person.name} ${person.email}`.toLocaleLowerCase('hu-HU').includes(search.toLocaleLowerCase('hu-HU'))).map(person=><option key={person.id} value={person.id}>{person.name} — {person.email}</option>)}
      </select></label>""", 'front-selection')
 s=once(s,'<button type="submit" disabled={busy||!email.trim()}>+ Projekttag hozzáadása</button>','<button type="submit" disabled={busy||!picked}>+ Projekttag hozzáadása</button>','front-add-button')
 anchor='    {membership.can_manage && <form className="rp-team-add" onSubmit={add}>'
 markup='''    {user?.role==='admin' && <section className="rp-team-add" aria-label="Rendszerszintű projektlátás">
      <h2>Teljes projektáttekintés</h2>
      <p>A globális szerkesztő minden projektet megtekinthet, de módosítani csak a saját projektjeiben tud. Az új jogosultság friss bejelentkezéskor lép érvénybe a teljes korábbi adatkörre.</p>
      {users.filter(person=>person.system_role==='worker'||person.system_role==='editor').map(person=><label key={person.id}>{person.name} — {person.email}
        <select aria-label={`${person.name} globális projektlátása`} value={person.system_role} disabled={busy} onChange={event=>void transact(()=>changeGlobalRole(person.id,event.target.value as 'worker'|'editor'))}>
          <option value="worker">Csak megosztott projektek</option>
          <option value="editor">Minden projekt olvasása</option>
        </select>
      </label>)}
    </section>}
'''
 return once(s,anchor,markup+anchor,'front-global-role-ui')

def main_py(s):
 s=once(s,'''def can_read_project(db: Session, project_id: str, user_id: str) -> bool:
    return project_membership(db, project_id, user_id) is not None''','''def can_read_project(db: Session, project_id: str, user_id: str) -> bool:
    # Global editors can inspect projects; write access remains membership-scoped.
    viewer = db.get(User, user_id)
    return bool(viewer and viewer.active and viewer.role == 'editor') or project_membership(db, project_id, user_id) is not None''','backend-read')
 s=once(s,'''    memberships = set(db.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)).all())
    latest_by_entity = {}''','''    if user.active and user.role == 'editor':
        memberships = set(db.scalars(select(Project.id)).all())
    else:
        memberships = set(db.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)).all())
    latest_by_entity = {}''','backend-pull')
 return s
PATCHERS={'team_api.py':team_api,'ReferenceTeam.tsx':team_view,'TeamDirectory.ts':team_ts,'account_api.py':account_api}

def generate():
 data={}
 with zipfile.ZipFile(SRC) as z:
  for name,patch in PATCHERS.items():
   raw=z.read(SOURCE_PREFIX+name)
   if sha(raw)!=PINS[name]:raise ValueError('SOURCE_DRIFT:'+name)
   out=patch(raw.decode('utf-8')).encode('utf-8')
   if out==raw:raise ValueError('UNCHANGED:'+name)
   data[name]=out
 for name,payload in data.items():
  d=ROOT/'out'/name;d.parent.mkdir(exist_ok=True)
  d.write_bytes(payload)
 (ROOT/'out/MANIFEST.json').write_text(json.dumps({'base':'FieldWork_StableDEV_M6 original source pins', 'files':{n:sha(b) for n,b in data.items()},'main_patch_strategy':'strict two anchors / no deployment'},indent=2))
 return data
if __name__=='__main__':
 d=generate()
 for k,v in d.items():print(k,len(v),sha(v))
