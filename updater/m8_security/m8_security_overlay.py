#!/usr/bin/env python3
"""Strict bounded source transformer for a NEW FieldWork M8 authz/sync source candidate.
Source-only, no target data manipulation or production access.
"""
from __future__ import annotations
import hashlib
from pathlib import Path

class PatchStop(RuntimeError): pass

def once(s: str,old: str,new: str, label: str)->str:
    count=s.count(old)
    if count!=1:raise PatchStop(f'M8_ANCHOR_MISMATCH:{label}:{count}')
    return s.replace(old,new,1)

def digest(b:bytes)->str:return hashlib.sha256(b).hexdigest()


def main_patch(s:str)->str:
    s=once(s,'''def can_write_project(db: Session, project_id: str, user_id: str) -> bool:
    membership = project_membership(db, project_id, user_id)
    return bool(membership and membership.role in PROJECT_ROLES_WRITE)

def can_read_project(db: Session, project_id: str, user_id: str) -> bool:
    return project_membership(db, project_id, user_id) is not None''',
'''def system_admin(db: Session, user_id: str) -> bool:
    actor = db.get(User, user_id)
    return bool(actor and actor.active and actor.role == "admin")

def can_write_project(db: Session, project_id: str, user_id: str) -> bool:
    # System-admin rights are explicit, not modeled as fabricated memberships.
    if system_admin(db, user_id):
        return True
    membership = project_membership(db, project_id, user_id)
    return bool(membership and membership.role in PROJECT_ROLES_WRITE)

def can_read_project(db: Session, project_id: str, user_id: str) -> bool:
    return system_admin(db, user_id) or project_membership(db, project_id, user_id) is not None''','main-system-admin')
    s=once(s,'''    if cls is Project:
        if obj:
            writable_project(db, obj.id, user_id)
        return validate_project_data(db, data, entity_id, user_id, obj), entity_id''',
'''    if cls is Project:
        if obj:
            writable_project(db, obj.id, user_id)
        else:
            # A viewer can no longer become owner by creating a new root project.
            # Editor/owner may create a child only beneath a writable parent.
            parent_id = data.get("parent_id")
            if parent_id is None:
                if not system_admin(db, user_id):
                    raise PermissionError("Új főprojektet csak rendszergazda hozhat létre")
            else:
                writable_project(db, parent_id, user_id)
        return validate_project_data(db, data, entity_id, user_id, obj), entity_id''','main-root-project-gate')
    s=once(s,'''    memberships = set(db.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)).all())
    latest_by_entity = {}''',
'''    if user.role == "admin" and user.active:
        memberships = set(db.scalars(select(Project.id).where(Project.deleted.is_(False))).all())
        # Keep archived projects visible to administrators through their changes.
        memberships.update(db.scalars(select(Project.id).where(Project.deleted.is_(True))).all())
    else:
        memberships = set(db.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)).all())
    latest_by_entity = {}''','main-admin-global-pull')
    # Access scope is re-evaluated on every request from current DB state.
    # Fingerprint avoids stale UI following membership creation/revocation or role changes.
    marker='@app.get("/sync/pull", response_model=SyncPullOut)'
    addition='''@app.get("/sync/access-scope")
def sync_access_scope(user: User = Depends(current_user), db: Session = Depends(get_db)):
    import hashlib
    memberships = list(db.execute(
        select(ProjectMember.project_id, ProjectMember.role)
        .where(ProjectMember.user_id == user.id)
        .order_by(ProjectMember.project_id, ProjectMember.role)
    ).all())
    # Not a secret: the digest contains no email, passwords or sensitive payload.
    signature = '|'.join([user.id, user.role, str(user.active)] +
                         [f'{pid}:{role}' for pid, role in memberships])
    return {"fingerprint": hashlib.sha256(signature.encode('utf-8')).hexdigest(),
            "role": user.role, "project_count": len(memberships)}

'''+marker
    s=once(s,marker,addition,'main-scope-endpoint')
    return s


def team_patch(s:str)->str:
    s=once(s,"return bool(membership and membership.role == 'owner')",
           "return bool(user.active and user.role == 'admin') or bool(membership and membership.role == 'owner')",'team-admin-manager')
    s=once(s,'''        project_ids = set(db.scalars(select(ProjectMember.project_id)
            .join(Project, Project.id == ProjectMember.project_id)
            .where(ProjectMember.user_id == user.id, Project.deleted.is_(False))))''',
'''        project_ids = (set(db.scalars(select(Project.id).where(Project.deleted.is_(False))).all())
                       if user.role == 'admin' and user.active else
                       set(db.scalars(select(ProjectMember.project_id)
                           .join(Project, Project.id == ProjectMember.project_id)
                           .where(ProjectMember.user_id == user.id, Project.deleted.is_(False)))))''','team-directory-admin')
    return s


def api_patch(s:str)->str:
    anchor="export const pullChanges = (cursor: number, limit = 1000) => apiRequest<PullResponse>(`/sync/pull?cursor=${cursor}&limit=${limit}`)"
    return once(s,anchor,anchor+"\nexport const getAccessScope = () => apiRequest<{ fingerprint: string; role: string; project_count: number }>('/sync/access-scope')",'api-access-scope')


def app_patch(s:str)->str:
    s=once(s,"import { FieldworkProvider, useFieldwork } from './data/FieldworkContext'",
       "import { FieldworkProvider, useFieldwork } from './data/FieldworkContext'\nimport { getAccessScope } from './api/fieldwork'",'app-import')
    s=once(s,'''  // Az első snapshot egyszer fut; a további frissítéseket a felhasználó indítja.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void refresh(true).catch(() => undefined) }, [])''',
'''  // Preserve offline-first initial hydration; the server scope check is online-only.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void refresh(true).catch(() => undefined) }, [])
  useEffect(() => {
    let active = true
    let inFlight = false
    let priorScope: string | undefined
    const sync = async () => {
      if (!active || inFlight || document.visibilityState === 'hidden' || !navigator.onLine) return
      inFlight = true
      try {
        const { fingerprint } = await getAccessScope()
        if (!active) return
        const changed = priorScope !== undefined && priorScope !== fingerprint
        priorScope = fingerprint
        if (changed) await refresh(true)
        else await refresh(false)
      } catch {
        // Scope changes never grant access without a successful server response.
      } finally { inFlight = false }
    }
    const initial = window.setTimeout(() => { void sync() }, 3000)
    const interval = window.setInterval(() => { void sync() }, 12000)
    const focus = () => { void sync() }
    window.addEventListener('focus', focus)
    window.addEventListener('online', focus)
    document.addEventListener('visibilitychange', focus)
    return () => {
      active = false
      window.clearTimeout(initial)
      window.clearInterval(interval)
      window.removeEventListener('focus', focus)
      window.removeEventListener('online', focus)
      document.removeEventListener('visibilitychange', focus)
    }
  }, [refresh])''','app-auto-sync')
    return s


def projects_patch(s:str)->str:
    s=once(s,"import { Modal } from './Modal'","import { Modal } from './Modal'\nimport { useAuth } from '../auth/AuthContext'",'projects-auth-import')
    s=once(s,"export function Projects({ search = '' }: { search?: string }) {",
           "export function Projects({ search = '' }: { search?: string }) {\n  const { user } = useAuth()\n  const canCreateRoot = user?.role === 'admin'",'projects-auth-role')
    # UI only; backend enforces independent policy.
    s=once(s,'<button className="primary" onClick={() => { setParentForNew(null); setEditing(null) }}>+ Új projekt</button>',
           '{canCreateRoot && <button className="primary" onClick={() => { setParentForNew(null); setEditing(null) }}>+ Új projekt</button>}','projects-new-root-hide')
    return s

PATCHERS={
 'server/app/main.py':main_patch,
 'server/app/team_api.py':team_patch,
 'frontend/src/api/fieldwork.ts':api_patch,
 'frontend/src/App.tsx':app_patch,
 'frontend/src/components/Projects.tsx':projects_patch,
}

def apply(rel:str, data:bytes)->bytes:
    if rel not in PATCHERS:raise PatchStop('M8_NON_ALLOWLIST_FILE:'+rel)
    output=PATCHERS[rel](data.decode('utf-8')).encode('utf-8')
    if output==data:raise PatchStop('M8_EMPTY_PATCH:'+rel)
    return output


def old_team_test_patch(s: str)->str:
    return once(s,'''    assert client.get(f'/team/projects/{project_id}/members', headers=auth_headers).status_code == 403
    assert client.post(f'/team/projects/{project_id}/members', headers=auth_headers,
        json={'email':'admin@example.com','role':'owner'}).status_code == 403
    assert client.get(f'/team/projects/{uuid4()}/members', headers=auth_headers).status_code == 404''',
'''    # System admin must be able to recover orphaned projects without a membership.
    assert client.get(f'/team/projects/{project_id}/members', headers=auth_headers).status_code == 200
    assert client.post(f'/team/projects/{project_id}/members', headers=auth_headers,
        json={'email':'admin@example.com','role':'owner'}).status_code == 201
    assert client.get(f'/team/projects/{uuid4()}/members', headers=auth_headers).status_code == 404''',
'old-team-admin-recovery')

PATCHERS['server/tests/test_team_m4.py']=old_team_test_patch
