import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Plan } from '../types'
import { DocumentViewer } from './DocumentViewer'
const api = vi.hoisted(() => ({ fetchProtectedBlob: vi.fn(), technicalError: (error: unknown) => String(error) }))
vi.mock('../api/client', () => api)
vi.mock('../utils/pdf', () => ({ loadPdfDocument: vi.fn() }))
const video = (id: string, mime_type: 'video/mp4' | 'video/webm'): Plan => ({
  id, project_id:'p1', name:'Helyszíni videó', description:'', revision:'v1',
  file_path:'documents/video', original_filename:'munka.mp4', file_size:100,
  mime_type, page_count:null, uploaded_by_id:'u1', created_at:'2026-01-01',
  status:'active', deleted:false, version:1, updated_at:'2026-01-01'
})
describe('védett videó dokumentum', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.fetchProtectedBlob.mockResolvedValue(new Blob(['dummy video'], { type:'video/mp4' }))
    vi.stubGlobal('URL', { createObjectURL: vi.fn(()=>'blob:video-local'), revokeObjectURL:vi.fn() })
  })
  it('védetten letölti, videóként jeleníti meg és logoutkor visszavonja az URL-t', async () => {
    render(<DocumentViewer document={video('one','video/mp4')} />)
    const player=await screen.findByLabelText('Helyszíni videó')
    expect(player.tagName.toLowerCase()).toBe('video')
    expect(player).toHaveAttribute('controls')
    expect(player).toHaveAttribute('src','blob:video-local')
    expect(api.fetchProtectedBlob).toHaveBeenCalledWith('/api/plans/one/content')
    window.dispatchEvent(new Event('fieldwork:logout'))
    await waitFor(()=>expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1))
  })
  it('WebM változat is a videólejátszót használja', async () => {
    render(<DocumentViewer document={video('two','video/webm')} />)
    expect((await screen.findByLabelText('Helyszíni videó')).tagName.toLowerCase()).toBe('video')
  })
})
