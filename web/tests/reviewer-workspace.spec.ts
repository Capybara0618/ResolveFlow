import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ReviewerWorkspace from '../src/ui/ReviewerWorkspace.vue'
import { ApiError, coreApi, type CaseSnapshot, type ReviewContext } from '../src/client'

const snapshot: CaseSnapshot = {
  case: { case_id: 'case-handoff', status: 'PENDING_REVIEW', input_revision: 2, version: 7, line_id: 'line-1' },
  evidence: [{ observation_id: 'ev-1', content: '客户提交的材料', evidence_kind: 'CUSTOMER_STATEMENT',
    source_ref: 'case:case-handoff/evidence:ev-1', source_version: '1', content_hash: 'a'.repeat(64) }], timeline: [],
}
const context: ReviewContext = {
  case_version: 7, input_revision: 2, allowed_actions: ['MANUAL_PROPOSAL', 'REJECT', 'REQUEST_INFO'], blocked_reason: '',
  policy_status: 'PINNED', policy_rules: [{ bundle_id: 'policy-1', version: '2026.09', rule_id: 'lost',
    title: '物流丢失退款', text: '必须确认丢失；签收争议需人工判断。', chunk_id: 'chunk-1', content_hash: 'b'.repeat(64) }],
}
afterEach(() => vi.restoreAllMocks())
describe('reviewer handoff', () => {
  it('requires explicit evidence and policy selection and submits the version the reviewer read', async () => {
    vi.spyOn(coreApi, 'reviewContext').mockResolvedValue(context)
    const submit = vi.spyOn(coreApi, 'reviewerAction').mockResolvedValue(snapshot)
    const wrapper = mount(ReviewerWorkspace, { props: { token: 't', snapshot, busy: false } })
    await flushPromises()
    expect(wrapper.text()).toContain('签收争议需人工判断')
    await wrapper.get('[data-test="manual-proposal"]').trigger('click')
    expect(wrapper.get('[data-test="submit-handoff"]').attributes('disabled')).toBeDefined()
    await wrapper.get('textarea').setValue('结合材料与条款申请全额退款')
    for (const input of wrapper.findAll('input[type="checkbox"]')) await input.setValue(true)
    vi.mocked(coreApi.reviewContext).mockResolvedValue({ ...context, case_version: 8 })
    await wrapper.setProps({ snapshot: { ...snapshot, case: { ...snapshot.case, version: 8 } } })
    await flushPromises()
    await wrapper.get('[data-test="submit-handoff"]').trigger('click')
    await flushPromises()
    expect(submit).toHaveBeenCalledWith('t', snapshot, {
      action: 'MANUAL_PROPOSAL', reason: '结合材料与条款申请全额退款',
      evidence_refs: [{ observation_id: 'ev-1', source_ref: snapshot.evidence[0].source_ref, source_version: '1', content_hash: 'a'.repeat(64) }],
      policy_refs: [{ bundle_id: 'policy-1', version: '2026.09', rule_id: 'lost', chunk_id: 'chunk-1', content_hash: 'b'.repeat(64) }],
    })
    expect(wrapper.emitted('changed')).toHaveLength(1)
    expect(wrapper.text()).toContain('仍需单独审批')
    wrapper.unmount()
  })
  it('refreshes after a conflicting decision without keeping an old form open', async () => {
    vi.spyOn(coreApi, 'reviewContext').mockResolvedValue(context)
    vi.spyOn(coreApi, 'reviewerAction').mockRejectedValue(new ApiError(409, 'CONFLICT', 'stale'))
    const wrapper = mount(ReviewerWorkspace, { props: { token: 't', snapshot, busy: false } })
    await flushPromises()
    await wrapper.get('[data-test="handoff-reject"]').trigger('click')
    await wrapper.get('textarea').setValue('材料不支持退款')
    await wrapper.get('[data-test="submit-handoff"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('重新核对')
    expect(wrapper.emitted('changed')).toHaveLength(1)
    wrapper.unmount()
  })
  it('shows a frozen case as read-only with policy text still available', async () => {
    vi.spyOn(coreApi, 'reviewContext').mockResolvedValue({ ...context, allowed_actions: [], blocked_reason: '退款授权已消费，输入已冻结' })
    const wrapper = mount(ReviewerWorkspace, { props: { token: 't', snapshot, busy: false } })
    await flushPromises()
    expect(wrapper.find('[data-test="manual-proposal"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="handoff-reject"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('输入已冻结')
    expect(wrapper.text()).toContain('物流丢失退款')
    wrapper.unmount()
  })
  it('does not enable actions when context is from a different version', async () => {
    vi.spyOn(coreApi, 'reviewContext').mockResolvedValue({ ...context, case_version: 8 })
    const wrapper = mount(ReviewerWorkspace, { props: { token: 't', snapshot, busy: false } })
    await flushPromises()
    expect(wrapper.find('[data-test="manual-proposal"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('工单已变化')
    wrapper.unmount()
  })
  it('marks the old proposal stale and states the next step after evidence advances the revision', async () => {
    vi.spyOn(coreApi, 'reviewContext').mockResolvedValue({ ...context, case_version: 8, input_revision: 3 })
    const revised: CaseSnapshot = {
      ...snapshot,
      case: { ...snapshot.case, status: 'QUEUED', input_revision: 3, version: 8 },
      proposal: { input_revision: 2, status: 'STALE', origin: 'AGENT' },
    }
    const wrapper = mount(ReviewerWorkspace, { props: { token: 't', snapshot: revised, busy: false } })
    await flushPromises()
    const progress = wrapper.get('[data-test="revision-progress"]')
    expect(progress.text()).toContain('旧版建议（第 2 版）已失效')
    expect(progress.text()).toContain('第 3 版')
    expect(progress.text()).toContain('新调查已排队')
    wrapper.unmount()
  })
})
