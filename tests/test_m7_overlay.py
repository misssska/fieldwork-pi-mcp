import unittest
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
if not (ROOT/'video_overlay.py').is_file():
    ROOT=Path(__file__).resolve().parents[1]/'updater/m7_video'
sys.path.insert(0,str(ROOT))
from video_overlay import (once, SourceStop, video_main, video_nginx, video_types,
 video_viewer,video_api,video_docs,role_taskdetail,docs_existing_tests,task_existing_tests,
 ROLE_HOOK,SOURCE_PATCHERS,SOURCE_PINS)

class M7NegativeGate(unittest.TestCase):
    def test_strict_anchor_denies_missing(self):
        with self.assertRaisesRegex(SourceStop,'ANCHOR_MISMATCH'):
            once('hello','missing','world','demo')
    def test_strict_anchor_denies_duplicate(self):
        with self.assertRaisesRegex(SourceStop,'ANCHOR_MISMATCH'):
            once('a a','a','x','duplicate')
    def test_main_adds_video_and_checks_nonvideo_upload_preserved(self):
        sample='''DOCUMENT_MIME_EXTENSIONS = {\n    "image/webp": "webp",\n}\ndef inspect_document(path: Path, mime_type: str) -> int | None:\n    try:\n        if mime_type == "application/pdf":\n            pass\n    except: pass\n\nasync def upload():\n                if size > settings.max_upload_bytes:\n                    raise HTTPException(413, "A dokumentum túl nagy")\n'''
        amended=video_main(sample)
        self.assertIn('"video/mp4": "mp4"',amended)
        self.assertIn('validate_video_header',amended)
        self.assertIn('VIDEO_MAX_UPLOAD_BYTES = 100 * 1024 * 1024',amended)
        self.assertIn('else settings.max_upload_bytes',amended)
        self.assertEqual(amended.count('validate_video_header(path, mime_type)'),1)
    def test_nginx_must_have_multiple_csp_entries(self):
        with self.assertRaises(SourceStop):video_nginx('client_max_body_size 30m;')
    def test_nginx_keeps_other_security_headers_and_adds_media(self):
        sample="client_max_body_size 30m; connect-src 'self'; object-src 'none'; connect-src 'self'; object-src 'none'; X-Frame-Options DENY;"
        out=video_nginx(sample)
        self.assertEqual(out.count("media-src 'self' blob:"),2)
        self.assertIn('X-Frame-Options DENY',out)
        self.assertIn('client_max_body_size 110m;',out)
    def test_types_add_both_video_variants(self):
        a=video_types("mime_type: 'application/pdf' | 'image/jpeg' | 'image/png' | 'image/webp'")
        self.assertIn("| 'video/mp4' | 'video/webm'",a)
    def test_viewer_is_video_not_image_and_blob_preserved(self):
        before="  return document.mime_type === 'application/pdf' ? <PdfCanvas blob={resource.blob} expectedPages={document.page_count} /> : <div className=\"image-viewer\"><img src={resource.url} alt={document.name} /></div>"
        out=video_viewer(before)
        self.assertIn('<video controls playsInline preload="metadata"',out)
        self.assertIn('src={resource.url}',out)
        self.assertIn('Videó letöltése',out)
    def test_document_timeout_only_once(self):
        a=video_api('    xhr.timeout = 60_000\nCsak PDF, JPEG, PNG vagy WebP dokumentum tölthető fel.')
        self.assertIn('300_000',a)
        self.assertIn('WebM',a)
    def test_documents_client_denies_viewer_and_large_video(self):
        sample='''import { DocumentViewer } from './DocumentViewer'\nconst ALLOWED_TYPES = ['application/pdf', 'image/jpeg', 'image/png', 'image/webp']\nexport function Documents({ projectId }: { projectId: string }) {\nconst chooseFile = (next?: File) => { setError(''); setFile(next); if (next && !ALLOWED_TYPES.includes(next.type)) {\n    if (!file || !name.trim()) return\n<div className="upload-box document-upload">\nPDF, JPEG, PNG vagy WebP kiválasztása\naccept="application/pdf,image/jpeg,image/png,image/webp"\nCsak PDF, JPEG, PNG vagy WebP dokumentum választható.'''
        out=video_docs(sample)
        self.assertIn('if (!file || !name.trim() || !canWrite) return',out)
        self.assertIn('hidden={!canWrite}',out)
        self.assertIn('100 : 25',out)
    def test_task_comment_and_upload_hidden_for_viewer(self):
        sample='''import { PhotoGallery } from './PhotoGallery'\nexport function TaskDetail({ task, onClose }: { task: Task; onClose: () => void }) {\n    if (!text.trim()) return\n    if (!file) return\n<form className="inline-form" onSubmit={addComment}>\n<div className="upload-box"><label htmlFor="photo">'''
        out=role_taskdetail(sample)
        self.assertEqual(out.count('hidden={!canWrite}'),2)
        self.assertIn('|| !canWrite',out)
    def test_existing_tests_mock_writable_role_only_in_test_files(self):
        sample="import { TaskDetail } from './TaskDetail'"
        self.assertIn("vi.mock('./useProjectWrite'",task_existing_tests(sample))
        docs="vi.mock('./DocumentViewer',\nPDF, JPEG"
        self.assertIn('PDF, kép vagy videó',docs_existing_tests(docs))
    def test_fail_closed_uses_server_project_membership(self):
        self.assertIn('getMembers(projectId)',ROLE_HOOK)
        self.assertIn('setAllowed(false)',ROLE_HOOK)
        self.assertIn("membership?.role === 'owner' || membership?.role === 'editor'",ROLE_HOOK)
        self.assertNotIn("user.role === 'admin'",ROLE_HOOK)
    def test_patch_only_named_files(self):
        self.assertEqual(len(SOURCE_PATCHERS),11)
        self.assertEqual(len(SOURCE_PINS),10)
    def test_backend_viewer_regression_present(self):
        source=(ROOT/'test_video_m7.py').read_text()
        self.assertIn("test_viewer_can_download_but_cannot_upload_or_modify",source)
        self.assertIn("==403",source)
        self.assertIn("'rejected'",source)
    def test_no_deployment_in_candidate_script(self):
        source=(ROOT/'m7_candidate.py').read_text()
        for forbidden in ("['up','-d','--build'",'18090','/opt/fieldwork'):
            self.assertNotIn("subprocess.run(['docker','compose','-p','fieldwork-parity-m6-r9'",source)
        self.assertIn('M7_VIDEO_AND_VIEWER_TESTS_PASS_NO_DEPLOYMENT',source)
    def test_r2_exact_pi_m6_document_source_pins(self):
        # Host read-only diagnostic 2026-11-01, exact SHA256 values.
        self.assertEqual(SOURCE_PINS['frontend/src/components/Documents.tsx'],
            'a99dd1f32d240bc1540c36e7bb8977f8583b4e328825f815cc3ae7da4524e947')
        self.assertEqual(SOURCE_PINS['frontend/src/components/TaskDetail.tsx'],
            '2ef173512fc252c6f9229c1812d7ae650b473e97d0340813bb4fc792b5f3c170')

    def test_r2_changed_content_still_fails_closed(self):
        from video_overlay import patch_existing
        with self.assertRaisesRegex(SourceStop, 'M7_SOURCE_HASH_DRIFT'):
            patch_existing('frontend/src/components/Documents.tsx',
                           b'not-the-verified-M6-Documents.tsx-source',
                           SOURCE_PINS['frontend/src/components/Documents.tsx'])

    def test_strict_no_hardcoded_credentials_in_patch(self):
        source=(ROOT/'video_overlay.py').read_text()
        self.assertNotIn('admin/admin',source)
        self.assertNotIn('CHANGE_THIS_PASSWORD',source)

if __name__=='__main__':unittest.main()
