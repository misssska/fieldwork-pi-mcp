#!/usr/bin/env python3
"""FieldWork M7: deterministic project-document video+viewer-UI source overlays.

This module only transforms source in memory and writes to a *new isolated*
private M7 candidate after an external approval gate. NEVER edit the live M6.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib

# Original R8 files were read using the read-only FieldWork Pi MCP in this turn.
SOURCE_PINS = {
    'nginx/default.conf': 'c96b7463d99b1cdb07d4700568374fe958bd8e83a59bf87dc4ee2d6e56762d4c',
    'frontend/src/types.ts': 'f06a55d96c0de2c94f54f5716b927ca6681f0da3022c86ee1191c79c6e651ca2',
    'frontend/src/components/Documents.tsx': 'a99dd1f32d240bc1540c36e7bb8977f8583b4e328825f815cc3ae7da4524e947',
    'frontend/src/components/DocumentViewer.tsx': 'b1160d91d08edcc00fbb1f617a8b648f17a971869eeac9eac0530fc56c152109',
    'frontend/src/components/TaskDetail.tsx': '2ef173512fc252c6f9229c1812d7ae650b473e97d0340813bb4fc792b5f3c170',
    'frontend/src/api/fieldwork.ts': 'b986944a0622d1a6f1e0f0aecd9da520c499ca8cc9f8f4aba0c11891f764d149',
}

class SourceStop(RuntimeError):
    pass

def once(s: str, old: str, new: str, label: str) -> str:
    n=s.count(old)
    if n!=1:
        raise SourceStop(f'M7_ANCHOR_MISMATCH:{label}:{n}')
    return s.replace(old,new)

def sha(data:bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def video_main(s: str) -> str:
    # M6 main is already altered by the verified R6 source receipt.
    s=once(s, '    "image/webp": "webp",',
             '    "image/webp": "webp",\n    "video/mp4": "mp4",\n    "video/webm": "webm",', 'backend-mime-types')
    s=once(s, 'def inspect_document(path: Path, mime_type: str) -> int | None:',
'''VIDEO_MAX_UPLOAD_BYTES = 100 * 1024 * 1024
VIDEO_MIME_TYPES = frozenset({"video/mp4", "video/webm"})

def validate_video_header(path: Path, mime_type: str) -> None:
    """Reject obvious MIME spoofing; no arbitrary external decoders executed.

    Container/header validation is intentionally bounded, not a video codec
    audit; a browser may still reject unsupported codec profiles.
    """
    with path.open('rb') as handle:
        header = handle.read(4096)
    if mime_type == 'video/mp4':
        if len(header) < 16 or header[4:8] != b'ftyp' or not 16 <= int.from_bytes(header[:4], 'big') <= 4096:
            raise HTTPException(415, 'Érvénytelen MP4 konténer')
    elif mime_type == 'video/webm':
        if not header.startswith(bytes.fromhex('1a45dfa3')) or b'webm' not in header[:4096].lower():
            raise HTTPException(415, 'Érvénytelen WebM konténer')
    else:
        raise HTTPException(415, 'Nem támogatott videótípus')

def inspect_document(path: Path, mime_type: str) -> int | None:''', 'backend-video-header')
    s=once(s, '        if mime_type == "application/pdf":',
'''        if mime_type in VIDEO_MIME_TYPES:
            validate_video_header(path, mime_type)
            return None
        if mime_type == "application/pdf":''', 'backend-video-inspection')
    s=once(s, '                if size > settings.max_upload_bytes:\n                    raise HTTPException(413, "A dokumentum túl nagy")',
'''                limit = VIDEO_MAX_UPLOAD_BYTES if upload.content_type in VIDEO_MIME_TYPES else settings.max_upload_bytes
                if size > limit:
                    raise HTTPException(413, "A dokumentum túl nagy")''', 'backend-size-limit')
    return s

def video_nginx(s: str) -> str:
    if s.count('client_max_body_size 30m;')!=1:
        raise SourceStop('M7_NGINX_UPLOAD_LIMIT_DRIFT')
    s=s.replace('client_max_body_size 30m;', 'client_max_body_size 110m;')
    old="connect-src 'self'; object-src 'none';"
    n=s.count(old)
    if n < 2:
        raise SourceStop('M7_NGINX_CSP_MISSING')
    return s.replace(old,"connect-src 'self'; media-src 'self' blob:; object-src 'none';")

def video_types(s: str) -> str:
    return once(s, "mime_type: 'application/pdf' | 'image/jpeg' | 'image/png' | 'image/webp'",
                "mime_type: 'application/pdf' | 'image/jpeg' | 'image/png' | 'image/webp' | 'video/mp4' | 'video/webm'", 'typescript-video-type')

def video_viewer(s: str) -> str:
    old="  return document.mime_type === 'application/pdf' ? <PdfCanvas blob={resource.blob} expectedPages={document.page_count} /> : <div className=\"image-viewer\"><img src={resource.url} alt={document.name} /></div>"
    new="""  if (document.mime_type === 'application/pdf') return <PdfCanvas blob={resource.blob} expectedPages={document.page_count} />
  if (document.mime_type === 'video/mp4' || document.mime_type === 'video/webm') {
    return <div className="video-viewer"><video controls playsInline preload="metadata" src={resource.url} aria-label={document.name} style={{ maxWidth: '100%', maxHeight: '70vh' }}>A böngésző nem támogatja a videó lejátszását.</video><p><a href={resource.url} download={document.original_filename}>Videó letöltése</a></p></div>
  }
  return <div className="image-viewer"><img src={resource.url} alt={document.name} /></div>"""
    return once(s,old,new,'viewer-video-element')

def video_api(s: str) -> str:
    s=once(s, '    xhr.timeout = 60_000', '    xhr.timeout = 300_000', 'document-upload-timeout')
    return once(s, 'Csak PDF, JPEG, PNG vagy WebP dokumentum tölthető fel.',
               'Csak PDF, JPEG, PNG, WebP, MP4 vagy WebM fájl tölthető fel.', 'document-upload-error')

def video_docs(s: str) -> str:
    s=once(s,"const ALLOWED_TYPES = ['application/pdf', 'image/jpeg', 'image/png', 'image/webp']",
           "const ALLOWED_TYPES = ['application/pdf', 'image/jpeg', 'image/png', 'image/webp', 'video/mp4', 'video/webm']", 'docs-types')
    s=once(s,'Csak PDF, JPEG, PNG vagy WebP dokumentum választható.',
           'Csak PDF, JPEG, PNG, WebP, MP4 vagy WebM dokumentum választható.', 'docs-choose-message')
    s=once(s,'PDF, JPEG, PNG vagy WebP kiválasztása',
           'PDF, kép vagy videó kiválasztása (MP4/WebM max. 100 MB)', 'docs-label')
    s=once(s,'accept="application/pdf,image/jpeg,image/png,image/webp"',
           'accept="application/pdf,image/jpeg,image/png,image/webp,video/mp4,video/webm"', 'docs-accept')
    # A separate, fail-closed per-project permission hook; UI is not a security boundary.
    s=once(s, "import { DocumentViewer } from './DocumentViewer'",
           "import { DocumentViewer } from './DocumentViewer'\nimport { useProjectWrite } from './useProjectWrite'", 'docs-import-role')
    s=once(s,'export function Documents({ projectId }: { projectId: string }) {',
           'export function Documents({ projectId }: { projectId: string }) {\n  const canWrite = useProjectWrite(projectId)', 'docs-role-hook')
    s=once(s,'<div className="upload-box document-upload">',
           '<div className="upload-box document-upload" hidden={!canWrite} style={{ display: canWrite ? undefined : \'none\' }}>', 'docs-hide-upload')
    # Ensure client avoids attempting upload even with devtools/timing changes.
    s=once(s,'    if (!file || !name.trim()) return',
           '    if (!file || !name.trim() || !canWrite) return', 'docs-deny-on-action')
    s=once(s,"const chooseFile = (next?: File) => { setError(''); setFile(next); if (next && !ALLOWED_TYPES.includes(next.type)) {",
           "const chooseFile = (next?: File) => { setError(''); setFile(next); if (next && next.size > (next.type.startsWith('video/') ? 100 : 25) * 1024 * 1024) { setFile(undefined); setError('A kiválasztott fájl túl nagy.') ; return } if (next && !ALLOWED_TYPES.includes(next.type)) {", 'docs-prevalidate-size')
    return s

def role_taskdetail(s: str) -> str:
    s=once(s, "import { PhotoGallery } from './PhotoGallery'",
           "import { PhotoGallery } from './PhotoGallery'\nimport { useProjectWrite } from './useProjectWrite'", 'task-role-import')
    s=once(s, 'export function TaskDetail({ task, onClose }: { task: Task; onClose: () => void }) {',
           'export function TaskDetail({ task, onClose }: { task: Task; onClose: () => void }) {\n  const canWrite = useProjectWrite(task.project_id)', 'task-role-hook')
    s=once(s, '    if (!text.trim()) return', '    if (!text.trim() || !canWrite) return', 'task-role-comment-action')
    s=once(s, '    if (!file) return', '    if (!file || !canWrite) return', 'task-role-upload-action')
    s=once(s, '<form className="inline-form" onSubmit={addComment}>',
           '<form className="inline-form" onSubmit={addComment} hidden={!canWrite} style={{ display: canWrite ? undefined : \'none\' }}>', 'task-role-comment-form')
    s=once(s, '<div className="upload-box"><label htmlFor="photo">',
           '<div className="upload-box" hidden={!canWrite} style={{ display: canWrite ? undefined : \'none\' }}><label htmlFor="photo">', 'task-role-photo-upload')
    return s

SOURCE_PATCHERS = {
  'server/app/main.py': video_main,
  'nginx/default.conf': video_nginx,
  'frontend/src/types.ts': video_types,
  'frontend/src/components/DocumentViewer.tsx': video_viewer,
  'frontend/src/components/Documents.tsx': video_docs,
  'frontend/src/components/TaskDetail.tsx': role_taskdetail,
  'frontend/src/api/fieldwork.ts': video_api,
}

ROLE_HOOK = '''import { useEffect, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { getMembers } from './TeamDirectory'

/** Fail closed: every project write requires current server-backed membership. */
export function useProjectWrite(projectId: string) {
  const { user } = useAuth()
  const [allowed, setAllowed] = useState(false)
  useEffect(() => {
    let active = true
    setAllowed(false)
    if (!projectId || !user?.id) return () => { active = false }
    const logout = () => { active = false; setAllowed(false) }
    window.addEventListener('fieldwork:logout', logout)
    getMembers(projectId).then(value => {
      if (!active) return
      const membership = value.members.find(member => member.id === user.id)
      setAllowed(membership?.role === 'owner' || membership?.role === 'editor')
    }).catch(() => { if (active) setAllowed(false) })
    return () => { active = false; window.removeEventListener('fieldwork:logout', logout) }
  }, [projectId, user?.id])
  return allowed
}
'''

def patch_existing(relative: str, source: bytes, expected_sha: str | None = None) -> bytes:
    if expected_sha and sha(source) != expected_sha:
        raise SourceStop('M7_SOURCE_HASH_DRIFT:' + relative)
    if relative not in SOURCE_PATCHERS:
        raise SourceStop('M7_SOURCE_NOT_ALLOWLISTED:' + relative)
    decoded=source.decode('utf-8')
    changed=SOURCE_PATCHERS[relative](decoded).encode('utf-8')
    if source == changed:
        raise SourceStop('M7_EMPTY_PATCH:' + relative)
    return changed

# Existing UI test suites intentionally receive a writable-role fixture. A
# separate new test verifies fail-closed viewer behavior, not just CSS hiding.
SOURCE_PINS.update({
 'frontend/src/components/Documents.test.tsx': '98a5e707d5e7bee17ed6ed1a10f5964af96e754f40cee6fc8ff0a757bb1d599c',
 'frontend/src/components/UploadLifecycle.integration.test.tsx': 'bfd7333db65c847a110971a07e07f1d0af6b11cca39a43c8f82510fdc7e579ff',
 'frontend/src/components/Crud.integration.test.tsx': '3d454f472b6207d0585f4e682d624c29d8dbd57e4fc1455245106eec4cd59381',
})

def docs_existing_tests(s: str) -> str:
    s=once(s,"vi.mock('./DocumentViewer',", "vi.mock('./useProjectWrite', () => ({ useProjectWrite: () => true }))\nvi.mock('./DocumentViewer',", 'docs-existing-mock')
    return s.replace('PDF, JPEG', 'PDF, kép vagy videó')

def task_existing_tests(s: str) -> str:
    return once(s, "import { TaskDetail } from './TaskDetail'", "import { TaskDetail } from './TaskDetail'\nvi.mock('./useProjectWrite', () => ({ useProjectWrite: () => true }))", 'task-existing-role-mock')

SOURCE_PATCHERS.update({
  'frontend/src/components/Documents.test.tsx': docs_existing_tests,
  'frontend/src/components/UploadLifecycle.integration.test.tsx': task_existing_tests,
  'frontend/src/components/Crud.integration.test.tsx': task_existing_tests,
})

SOURCE_PINS['frontend/src/components/Projects.test.tsx'] = 'b48d32196eebc398376f3df66038f9f26e054ea4c44fd1d990935d186573307a'

def project_existing_tests(s: str) -> str:
    return once(s, "vi.mock('../data/FieldworkContext', () => ({ useFieldwork: () => state }))",
                "vi.mock('../data/FieldworkContext', () => ({ useFieldwork: () => state }))\nvi.mock('./useProjectWrite', () => ({ useProjectWrite: () => true }))",'projects-existing-test-mock')
SOURCE_PATCHERS['frontend/src/components/Projects.test.tsx'] = project_existing_tests
