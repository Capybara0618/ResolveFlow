import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ReviewerWorkspace from '../src/ui/ReviewerWorkspace.vue'
import { ApiError, coreApi, type CaseSnapshot, type CaseCollaboration, type ReviewContext } from '../src/client'

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
const collaboration: CaseCollaboration = { case_id: snapshot.case.case_id, version: 3, is_owner: true,
  owner: { username: 'reviewer', display_name: '专员', role: 'REVIEWER', enabled: true },
  allowed_actions: ['RELEASE', 'TRANSFER'], history: [] }
const mountWorkspace = (overrides: Partial<InstanceType<typeof ReviewerWorkspace>['$props']> = {}) =>
  mount(ReviewerWorkspace, { props: { token: 't', snapshot, busy: false, context, collaboration, ...overrides } })

afterEach(() => vi.restoreAllMocks())
describe('reviewer handoff', () => {
  it('prepares server facts without client checkboxes and submits the frozen case and owner', async () => {
    vi.spyOn(coreApi, 'manualRefundContext').mockResolvedValue({ case_version: 7, input_revision: 2, status: 'READY', message: '已核对', amount_minor: 69900, policy_title: '已付款未发货', checks: ['订单已付款', '商品尚未发货'] })
    const submit = vi.spyOn(coreApi, 'reviewerAction').mockResolvedValue(snapshot)
    const w = mountWorkspace({ mode: 'actions', snapshot: { ...snapshot, evidence: [] } })
    await w.get('[data-test="manual-proposal"]').trigger('click'); await flushPromises()
    const dialog = w.get('[role="dialog"]')
    expect(dialog.text()).toContain('699.00'); expect(dialog.text()).not.toContain('case-handoff')
    expect(dialog.findAll('input[type="checkbox"]')).toHaveLength(0)
    expect(dialog.text()).toContain('生成方案后还需确认批准')
    await w.get('textarea').setValue('买错尺寸，未发货')
    await w.setProps({ snapshot: { ...snapshot, case: { ...snapshot.case, version: 8 } }, collaboration: { ...collaboration, version: 4 } })
    await w.get('[data-test="submit-handoff"]').trigger('click'); await flushPromises()
    expect(submit).toHaveBeenCalledWith('t', { ...snapshot, evidence: [] }, { action: 'MANUAL_PROPOSAL', reason: '买错尺寸，未发货', use_order_facts: true }, collaboration)
    w.unmount()
  })
  it.each(['REQUEST_INFO', 'REJECT'] as const)('shows a customer-readable %s preview without technical IDs', async kind => {
    const submit = vi.spyOn(coreApi, 'reviewerAction').mockResolvedValue(snapshot)
    const w = mountWorkspace({ mode: 'actions' })
    await w.get(kind === 'REJECT' ? '[data-test="handoff-reject"]' : '[data-test="handoff-info"]').trigger('click')
    await w.get('textarea').setValue('清晰的客户说明')
    const dialog = w.get('[role="dialog"]')
    expect(dialog.text()).toContain('客户将看到'); expect(dialog.text()).not.toContain('case-handoff')
    expect(dialog.text()).toContain(kind === 'REJECT' ? '本次申请将结束' : '回答后系统继续调查')
    expect(w.get('[data-test="submit-handoff"]').text()).toBe(kind === 'REJECT' ? '确认拒绝' : '发送问题')
    await w.get('[data-test="submit-handoff"]').trigger('click'); await flushPromises()
    expect(submit).toHaveBeenCalledWith('t', snapshot, { action: kind, reason: '清晰的客户说明' }, collaboration)
    w.unmount()
  })
  it('blocks a changed preview or blocked order instead of manufacturing eligibility', async () => {
    const prepare = vi.spyOn(coreApi, 'manualRefundContext').mockResolvedValue({ case_version: 8, input_revision: 2, status: 'READY', message: '已核对', amount_minor: 69900, policy_title: '未发货', checks: [] })
    const w = mountWorkspace({ mode: 'actions', snapshot: { ...snapshot, evidence: [] } })
    await w.get('[data-test="manual-proposal"]').trigger('click'); await flushPromises()
    await w.get('textarea').setValue('合成理由')
    expect(w.text()).toContain('申请已更新'); expect(w.get('[data-test="submit-handoff"]').attributes('disabled')).toBeDefined()
    prepare.mockResolvedValue({ case_version: 7, input_revision: 2, status: 'BLOCKED', message: '商品已发货', amount_minor: null, policy_title: null, checks: [] })
    await w.get('[aria-label="关闭弹窗"]').trigger('click')
    await w.get('[data-test="manual-proposal"]').trigger('click'); await flushPromises()
    await w.get('textarea').setValue('合成理由')
    expect(w.text()).toContain('商品已发货'); expect(w.text()).toContain('暂不能生成方案')
    expect(w.get('[data-test="submit-handoff"]').attributes('disabled')).toBeDefined()
    w.unmount()
  })
  it('ignores preparation arriving after switching cases, and expires a rejected session', async () => {
    let resolve!: (value: Awaited<ReturnType<typeof coreApi.manualRefundContext>>) => void
    const prepare = vi.spyOn(coreApi, 'manualRefundContext').mockReturnValue(new Promise(r => { resolve = r }))
    const w = mountWorkspace({ mode: 'actions' })
    await w.get('[data-test="manual-proposal"]').trigger('click')
    await w.setProps({ snapshot: { ...snapshot, case: { ...snapshot.case, case_id: 'other' } } })
    resolve({ case_version: 7, input_revision: 2, status: 'READY', message: '旧结果', amount_minor: 69900, policy_title: '未发货', checks: [] }); await flushPromises()
    expect(w.find('[role="dialog"]').exists()).toBe(false)
    prepare.mockRejectedValue(new ApiError(401, 'UNAUTHENTICATED', 'expired'))
    await w.get('[data-test="manual-proposal"]').trigger('click'); await flushPromises()
    expect(w.emitted('expired')).toHaveLength(1); expect(w.find('[role="dialog"]').exists()).toBe(false)
    w.unmount()
  })
  it('permits deliberate alternate evidence selection when automatic preparation is blocked', async () => {
    vi.spyOn(coreApi, 'manualRefundContext').mockResolvedValue({ case_version: 7, input_revision: 2, status: 'BLOCKED', message: '非未发货场景', amount_minor: null, policy_title: null, checks: [] })
    const submit = vi.spyOn(coreApi, 'reviewerAction').mockResolvedValue(snapshot)
    const w = mountWorkspace({ mode: 'actions' })
    await w.get('[data-test="manual-proposal"]').trigger('click'); await flushPromises()
    await w.get('.manual-switch input').setValue(true)
    for (const input of w.findAll('.manual-basis fieldset input')) await input.setValue(true)
    await w.get('textarea').setValue('原始材料和政策支持退款')
    await w.get('[data-test="submit-handoff"]').trigger('click'); await flushPromises()
    expect(submit.mock.calls[0][2].use_order_facts).toBeUndefined()
    expect(submit.mock.calls[0][2].evidence_refs).toHaveLength(1); expect(submit.mock.calls[0][2].policy_refs?.[0].rule_id).toBe('lost')
    w.unmount()
  })
  it('makes consumed UNKNOWN explicit even when an unclaimed owner masks the server blocked reason', async () => {
    const w = mountWorkspace({ snapshot: { ...snapshot, case: { ...snapshot.case, status: 'RECONCILING' },
      authorization: { authorization_id: 'auth', authorization_version: 3, status: 'CONSUMED', input_revision: 2 } },
      context: { ...context, allowed_actions: [], blocked_reason: '当前仅可查看' }, collaboration: { ...collaboration, is_owner: false } })
    await flushPromises()
    expect(w.get('[data-test="revision-progress"]').text()).toContain('输入与人工操作已冻结')
    expect(w.text()).toContain('不要重新发起退款'); expect(w.find('[data-test="handoff-reject"]').exists()).toBe(false)
    w.unmount()
  })
  it('expires a live session and ignores a late refusal after leaving the workspace', async () => {
    const submit = vi.spyOn(coreApi, 'reviewerAction').mockRejectedValue(new ApiError(401, 'UNAUTHENTICATED', 'expired'))
    const first = mountWorkspace(); await flushPromises()
    await first.get('[data-test="handoff-reject"]').trigger('click'); await first.get('textarea').setValue('合成说明')
    await first.get('[data-test="submit-handoff"]').trigger('click'); await flushPromises()
    expect(first.emitted('expired')).toHaveLength(1); expect(first.find('[data-test="submit-handoff"]').exists()).toBe(false)
    first.unmount()
    let reject!: (cause: unknown) => void
    submit.mockReturnValue(new Promise((_resolve, r) => { reject = r }))
    const second = mountWorkspace(); await flushPromises()
    await second.get('[data-test="handoff-reject"]').trigger('click'); await second.get('textarea').setValue('合成旧请求')
    await second.get('[data-test="submit-handoff"]').trigger('click')
    second.unmount(); reject(new ApiError(401, 'UNAUTHENTICATED', 'expired')); await flushPromises()
    expect(second.emitted('expired')).toBeUndefined(); expect(second.emitted('changed')).toBeUndefined()
  })
  it.each(['CLOSED_SUCCESS', 'CLOSED_REJECTED', 'CANCELLED'] as const)(
    'keeps %s terminal when a manual decision advanced the revision', async (status) => {
      const wrapper = mountWorkspace({
        snapshot: { ...snapshot, case: { ...snapshot.case, status, input_revision: 3 },
          proposal: { input_revision: 2, status: 'STALE' } },
        context: { ...context, allowed_actions: [], blocked_reason: '工单已结束，仅可查看记录' },
      })
      await flushPromises()
      expect(wrapper.get('[data-test="revision-progress"]').text()).toContain('工单已结束')
      expect(wrapper.text()).not.toContain('新调查已排队')
      expect(wrapper.find('[data-test="handoff-reject"]').exists()).toBe(false)
      wrapper.unmount()
    },
  )
  it('does not invent a queued investigation for an older proposal in manual review', async () => {
    const wrapper = mountWorkspace({ snapshot: { ...snapshot,
      case: { ...snapshot.case, input_revision: 3 }, proposal: { input_revision: 2, status: 'STALE' } } })
    await flushPromises()
    expect(wrapper.get('[data-test="revision-progress"]').text()).toContain('请查看当前处理状态')
    expect(wrapper.text()).not.toContain('新调查已排队')
    wrapper.unmount()
  })
  it('requires explicit evidence and policy selection and submits the version the reviewer read', async () => {
    const submit = vi.spyOn(coreApi, 'reviewerAction').mockResolvedValue(snapshot)
    const wrapper = mountWorkspace()
    await flushPromises()
    expect(wrapper.text()).toContain('签收争议需人工判断')
    await wrapper.get('[data-test="manual-proposal"]').trigger('click')
    expect(wrapper.get('[data-test="submit-handoff"]').attributes('disabled')).toBeDefined()
    await wrapper.get('textarea').setValue('结合材料与条款申请全额退款')
    for (const input of wrapper.findAll('input[type="checkbox"]')) await input.setValue(true)
    await wrapper.setProps({ snapshot: { ...snapshot, case: { ...snapshot.case, version: 8 } },
      collaboration: { ...collaboration, version: 4, is_owner: false } })
    await flushPromises()
    await wrapper.get('[data-test="submit-handoff"]').trigger('click')
    await flushPromises()
    expect(submit).toHaveBeenCalledWith('t', snapshot, {
      action: 'MANUAL_PROPOSAL', reason: '结合材料与条款申请全额退款',
      evidence_refs: [{ observation_id: 'ev-1', source_ref: snapshot.evidence[0].source_ref, source_version: '1', content_hash: 'a'.repeat(64) }],
      policy_refs: [{ bundle_id: 'policy-1', version: '2026.09', rule_id: 'lost', chunk_id: 'chunk-1', content_hash: 'b'.repeat(64) }],
    }, collaboration)
    expect(wrapper.emitted('changed')).toHaveLength(1)
    expect(wrapper.text()).toContain('仍需单独审批')
    wrapper.unmount()
  })
  it('refreshes after a conflicting decision without keeping an old form open', async () => {
    vi.spyOn(coreApi, 'reviewerAction').mockRejectedValue(new ApiError(409, 'CONFLICT', 'stale'))
    const wrapper = mountWorkspace()
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
    const wrapper = mountWorkspace({ context: { ...context, allowed_actions: [], blocked_reason: '退款授权已消费，输入已冻结' } })
    await flushPromises()
    expect(wrapper.find('[data-test="manual-proposal"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="handoff-reject"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('输入已冻结')
    expect(wrapper.text()).toContain('物流丢失退款')
    wrapper.unmount()
  })
  it('does not enable actions when the parent could not load a context for this version', async () => {
    const wrapper = mountWorkspace({ context: null, contextError: '工单已变化，请刷新后查看当前操作。' })
    await flushPromises()
    expect(wrapper.find('[data-test="manual-proposal"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('工单已变化')
    wrapper.unmount()
  })
  it('marks the old proposal stale and states the next step after evidence advances the revision', async () => {
    const revised: CaseSnapshot = {
      ...snapshot,
      case: { ...snapshot.case, status: 'QUEUED', input_revision: 3, version: 8 },
      proposal: { input_revision: 2, status: 'STALE', origin: 'AGENT' },
    }
    const wrapper = mountWorkspace({ snapshot: revised, context: { ...context, case_version: 8, input_revision: 3 } })
    await flushPromises()
    const progress = wrapper.get('[data-test="revision-progress"]')
    expect(progress.text()).toContain('旧版建议（第 2 版）已失效')
    expect(progress.text()).toContain('第 3 版')
    expect(progress.text()).toContain('新调查已排队')
    wrapper.unmount()
  })
})

describe('bound policy clauses', () => {
  const rules: ReviewContext['policy_rules'] = [
    { bundle_id: 'policy-logistics-2026.09', version: '2026.09', rule_id: 'R-LOST-001', title: '承运商判定丢失',
      text: '承运商结论为 LOST 且无有效签收记录时，可按该订单行支付金额全额退款。', chunk_id: 'c-01', content_hash: 'c'.repeat(64) },
    { bundle_id: 'policy-logistics-2026.09', version: '2026.09', rule_id: 'R-LOST-EXC-001', title: '丢失规则的例外：高价值行',
      text: '例外：本规则不适用于支付金额超过 500000 分的订单行，此类行即使结论为 LOST 也不得自动退款，必须转人工。',
      chunk_id: 'c-07', content_hash: 'd'.repeat(64) },
  ]

  it('separates the stored clause, the model reading and the service re-check', async () => {
    const withProposal: CaseSnapshot = {
      ...snapshot,
      proposal: { origin: 'AGENT', status: 'VALIDATED', input_revision: 2, summary: '合成物流显示已丢失，建议全行退款。' },
    }
    const wrapper = mountWorkspace({ snapshot: withProposal, context: { ...context, policy_rules: rules } })
    await flushPromises()
    expect(wrapper.get('[data-test="agent-reading"]').text()).toContain('合成物流显示已丢失')
    expect(wrapper.text()).toContain('① 原始条款（权威文本）')
    expect(wrapper.text()).toContain('② Agent 解释与适用判断')
    expect(wrapper.text()).toContain('③ 服务端复核结果')
    expect(wrapper.get('[data-test="server-recheck"]').text()).toContain('VALIDATED')
    expect(wrapper.text()).toContain('本页不计算退款资格')
    wrapper.unmount()
  })

  it('labels a human proposal explanation without attributing it to the model', async () => {
    const wrapper = mountWorkspace({ snapshot: { ...snapshot,
      proposal: { origin: 'HUMAN', status: 'VALIDATED', input_revision: 2, summary: '人工核对丢失政策后提出方案。' } } })
    await flushPromises()
    expect(wrapper.text()).toContain('② 人工方案理由与适用判断')
    expect(wrapper.text()).not.toContain('② Agent 解释与适用判断')
    expect(wrapper.get('[data-test="agent-reading"]').text()).toContain('人工核对丢失政策')
    wrapper.unmount()
  })

  it('marks the sentences that carry limiting phrasing in the stored text only', async () => {
    const wrapper = mountWorkspace({ context: { ...context, policy_rules: rules } })
    await flushPromises()
    const marked = wrapper.findAll('[data-limiting="true"]')
    expect(marked).toHaveLength(1)
    expect(marked[0].text()).toContain('不得自动退款')
    expect(marked[0].text()).toContain('必须转人工')
    expect(wrapper.text()).toContain('已按原文标出；是否适用由人判断')
    wrapper.unmount()
  })

  it('marks the clause a proposal cites and opens it when a citation asks for it', async () => {
    const cited: CaseSnapshot = {
      ...snapshot,
      proposal: {
        origin: 'AGENT', status: 'VALIDATED', input_revision: 2,
        policy_refs: [{ bundle_id: 'policy-logistics-2026.09', version: '2026.09', rule_id: 'R-LOST-EXC-001',
          chunk_id: 'c-07', content_hash: 'd'.repeat(64) }],
      },
    }
    const wrapper = mountWorkspace({ snapshot: cited, context: { ...context, policy_rules: rules } })
    await flushPromises()
    const citedTags = wrapper.findAll('[data-test="policy-cited"]')
    expect(citedTags).toHaveLength(1)
    expect(citedTags[0].element.closest('[data-test="bound-policy"]')?.textContent).toContain('丢失规则的例外')
    await wrapper.setProps({ focusKey: `policy-logistics-2026.09\u00002026.09\u0000R-LOST-EXC-001\u0000c-07\u0000${'d'.repeat(64)}`, focusNonce: 1 })
    await flushPromises()
    expect(wrapper.get('.bound-policies').attributes('open')).toBeDefined()
    wrapper.unmount()
  })
})
