"""M8 safe, exact-anchor source overlay for a verified M7 isolated source copy."""
import hashlib
import importlib.util
from pathlib import Path

BASE = Path(__file__).resolve().parent

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def once(s: str, old: str, new: str, label: str) -> str:
    count=s.count(old)
    if count != 1:
        raise ValueError(f'M8_ANCHOR_DRIFT:{label}:{count}')
    return s.replace(old,new,1)

# This source is pinned in the M8 archive (and checked again by the Pi launcher).
from build import main_py as previous_main_patch

def patch_main(s: str) -> str:
    s=previous_main_patch(s)
    s=once(s,'import hashlib\n','import hashlib\nimport json\n','json-import')
    marker='@app.get("/sync/pull", response_model=SyncPullOut)'
    scope='''@app.get("/sync/access-scope")
def access_scope(user: User = Depends(current_user), db: Session = Depends(get_db)):
    # A role/membership change invalidates all old client-side entity visibility.
    # Never expose project IDs or member emails in this response.
    roles = sorted((member.project_id, member.role) for member in
                   db.scalars(select(ProjectMember).where(ProjectMember.user_id == user.id)))
    snapshot = json.dumps([user.id, user.role, bool(user.active), roles],
                          separators=(',', ':'), ensure_ascii=True)
    return {'fingerprint': hashlib.sha256(snapshot.encode('utf-8')).hexdigest()}

'''
    return once(s,marker,scope+marker,'scope-route')

def patch_app(s: str) -> str:
    s=once(s,"import { useAuth } from './auth/AuthContext'", "import { useAuth } from './auth/AuthContext'\nimport { getAccessScope } from './api/fieldwork'",'app-api-import')
    needle='  // Az első snapshot egyszer fut; a további frissítéseket a felhasználó indítja.\n  // eslint-disable-next-line react-hooks/exhaustive-deps\n  useEffect(() => { void refresh(true).catch(() => undefined) }, [])'
    replacement='''  // Initial full authorized snapshot. Never replace this with cursor-only pull.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void refresh(true).catch(() => undefined) }, [])
  useEffect(() => {
    let stopped = false
    let running = false
    let previousScope: string | undefined
    const check = async () => {
      if (stopped || running || document.visibilityState === 'hidden' || !navigator.onLine) return
      running = true
      try {
        const nextScope = (await getAccessScope()).fingerprint
        if (stopped) return
        if (previousScope !== undefined && nextScope !== previousScope) {
          // A new authenticated page load drops all React in-memory entities
          // before rehydrating from the newly authorized membership snapshot.
          window.location.reload()
          return
        }
        previousScope = nextScope
        await refresh(false)
      } catch {
        // Network/auth errors remain visible through the existing sync status;
        // no speculative local access escalation or cached-data backfill.
      } finally { running = false }
    }
    const tick = () => { void check() }
    const timer = window.setInterval(tick, 12_000)
    window.addEventListener('focus', tick)
    window.addEventListener('online', tick)
    document.addEventListener('visibilitychange', tick)
    void check()
    return () => {
      stopped = true
      window.clearInterval(timer)
      window.removeEventListener('focus', tick)
      window.removeEventListener('online', tick)
      document.removeEventListener('visibilitychange', tick)
    }
  }, [refresh])'''
    return once(s,needle,replacement,'app-auto-sync')

def patch_api(s: str) -> str:
    if 'export const getAccessScope =' in s:
        raise ValueError('M8_ANCHOR_DRIFT:api-scope-already-patched')
    needle="export const getHealth = () => apiRequest<{ status: string }>('/health', {}, undefined, false)"
    return once(s,needle,"export const getAccessScope = () => apiRequest<{ fingerprint: string }>('/sync/access-scope')\n"+needle,'api-scope')

PATCHERS={
 'server/app/main.py':patch_main,
 'frontend/src/App.tsx':patch_app,
 'frontend/src/api/fieldwork.ts':patch_api,
}
