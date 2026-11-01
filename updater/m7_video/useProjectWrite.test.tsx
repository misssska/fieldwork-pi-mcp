import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useProjectWrite } from './useProjectWrite'
const auth=vi.hoisted(()=>({ user:{id:'viewer',role:'worker'} as {id:string,role:string} }))
const api=vi.hoisted(()=>({ getMembers:vi.fn() }))
vi.mock('../auth/AuthContext',()=>({useAuth:()=>auth}))
vi.mock('./TeamDirectory',()=>api)
describe('projektszintű szerkesztési jog fail-closed',()=>{
  beforeEach(()=>{vi.clearAllMocks();auth.user={id:'viewer',role:'worker'}})
  it('viewer marad csak olvasható',async()=>{
    api.getMembers.mockResolvedValue({can_manage:false,members:[{id:'viewer',role:'viewer'}]})
    const {result}=renderHook(()=>useProjectWrite('p1'))
    expect(result.current).toBe(false)
    await waitFor(()=>expect(api.getMembers).toHaveBeenCalledWith('p1'))
    expect(result.current).toBe(false)
  })
  it('owner/editor csak szerveroldalról kap szerkesztési jogot',async()=>{
    api.getMembers.mockResolvedValue({can_manage:false,members:[{id:'viewer',role:'editor'}]})
    const {result}=renderHook(()=>useProjectWrite('p1'))
    await waitFor(()=>expect(result.current).toBe(true))
  })
  it('ismeretlen projekt vagy sikertelen lekérés nem ad jogosultságot',async()=>{
    api.getMembers.mockRejectedValue(new Error('403'))
    const {result}=renderHook(()=>useProjectWrite('forbidden'))
    await waitFor(()=>expect(api.getMembers).toHaveBeenCalledWith('forbidden'))
    expect(result.current).toBe(false)
  })
})
