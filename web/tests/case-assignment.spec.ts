import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CaseAssignment from '../src/ui/CaseAssignment.vue'
import { ApiError, coreApi, type CaseCollaboration } from '../src/client'

const current: CaseCollaboration = { case_id: 'case-a', version: 2, is_owner: false,
  owner: { username: 'reviewer', display_name: '专员一', role: 'REVIEWER', enabled: true },
  allowed_actions: ['TAKEOVER'], history: [] }
const open = (value = current) => mount(CaseAssignment, { props: {
  token: 't', current: value, loading: false, busy: false,
} })
afterEach(() => vi.restoreAllMocks())

describe('case ownership controls', () => {
  it('requires an explicit admin gesture and reason; a conflict refreshes without retrying', async () => {
    const change = vi.spyOn(coreApi, 'changeCollaboration').mockRejectedValue(new ApiError(409, 'CONFLICT', 'stale'))
    const wrapper = open()
    expect(wrapper.text()).toContain('当前仅可查看')
    expect(change).not.toHaveBeenCalled()
    await wrapper.findAll('button').find(b => b.text() === '管理员接管')!.trigger('click')
    expect(wrapper.get('.dialog-actions button:last-child').attributes('disabled')).toBeDefined()
    await wrapper.get('textarea').setValue('负责人离线，由管理员接管')
    await wrapper.get('.dialog-actions button:last-child').trigger('click')
    await flushPromises()
    expect(change).toHaveBeenCalledExactlyOnceWith('t', current, 'TAKEOVER', '负责人离线，由管理员接管', undefined)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('请刷新后重新操作')
    expect(wrapper.emitted('changed')).toHaveLength(1)
    // The parent refreshes through null before returning the new owner/version.
    await wrapper.setProps({ current: null, loading: true })
    await wrapper.setProps({ current: { ...current, version: 3 }, loading: false })
    expect(wrapper.text()).toContain('请刷新后重新操作')
    await wrapper.setProps({ token: 'other-session' })
    expect(wrapper.text()).not.toContain('请刷新后重新操作')
    await wrapper.setProps({ current: { ...current, case_id: 'case-b' } })
    expect(wrapper.text()).not.toContain('请刷新后重新操作')
    wrapper.unmount()
  })

  it('discards a late staff list when the selected case changes', async () => {
    let resolve!: (staff: NonNullable<CaseCollaboration['owner']>[]) => void
    vi.spyOn(coreApi, 'reviewStaff').mockImplementation(() => new Promise(done => { resolve = done }))
    const wrapper = open({ ...current, is_owner: true, allowed_actions: ['TRANSFER'] })
    await wrapper.findAll('button').find(b => b.text() === '转交工单')!.trigger('click')
    await wrapper.setProps({ current: { ...current, case_id: 'case-b' } })
    resolve([{ username: 'late', display_name: '过期人员', role: 'REVIEWER', enabled: true }])
    await flushPromises()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('过期人员')
    wrapper.unmount()
  })

  it('lists real transfer targets and closes the form if collaboration advances', async () => {
    vi.spyOn(coreApi, 'reviewStaff').mockResolvedValue([current.owner!,
      { username: 'reviewer-2', display_name: '专员二', role: 'REVIEWER', enabled: true }])
    const change = vi.spyOn(coreApi, 'changeCollaboration')
    const wrapper = open({ ...current, is_owner: true, allowed_actions: ['TRANSFER'] })
    await wrapper.findAll('button').find(b => b.text() === '转交工单')!.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('option').map(o => o.text())).toEqual(['请选择本商家工作人员', '专员二'])
    await wrapper.setProps({ current: { ...current, version: 3 } })
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(change).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
