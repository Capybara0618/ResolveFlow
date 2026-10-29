import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MerchantCaseDetail from '../src/ui/MerchantCaseDetail.vue'
import type { CaseSnapshot, ReviewContext } from '../src/client'

function inputs() {
  const snapshot: CaseSnapshot = {
    case: { case_id: 'case-1', version: 7, input_revision: 2, status: 'PENDING_REVIEW', line_id: 'line-1', description: '买错尺寸，希望退款。' },
    authorization: { authorization_id: 'auth-1', authorization_version: 3, input_revision: 2, status: 'PENDING_REVIEW' },
    proposal: { origin: 'AGENT', status: 'VALIDATED', input_revision: 2, recommended_action: 'REFUND', summary: '订单尚未发货，建议核对政策后退款。', policy_refs: [{ rule_id: 'r-1' }] },
    evidence: [], timeline: [],
  }
  const context: ReviewContext = { case_version: 7, input_revision: 2, allowed_actions: [], blocked_reason: '', policy_rules: [], policy_status: 'PINNED' }
  return { token: 'test-token', snapshot, context, collaboration: { case_id: 'case-1', version: 1, is_owner: true, owner: null, allowed_actions: [], history: [] },
    line: { order_id: 'order-1', line_id: 'line-1', sku: 'sku-1', product_name: '无线降噪耳机', asset_key: 'headphones', variant_text: '黑色', category: 'electronics', quantity: 1, line_paid_amount: 32900, currency: 'CNY', status: 'PAID' },
    busy: false, productState: 'idle', fulfillment: '未发货', tradeState: 'idle', contextLoading: false, contextError: '', statusLabel: '待人工审核' }
}

describe('merchant detail design and permissions', () => {
  it('makes verification the current step and keeps alternatives available behind one disclosure', async () => {
    const props = inputs()
    props.snapshot.authorization = undefined
    props.snapshot.proposal!.recommended_action = 'MANUAL_REVIEW'
    props.snapshot.evidence = [{ observation_id: 'statement-1', evidence_kind: 'CUSTOMER_STATEMENT', content: '没有收到商品' }]
    props.context.allowed_actions = ['MANUAL_PROPOSAL', 'REQUEST_INFO', 'REJECT']
    const w = mount(MerchantCaseDetail, { props })
    expect(w.get('.merchant-detail-heading .status-tag').text()).toBe('待核验')
    expect(w.get<HTMLDetailsElement>('.merchant-alternative-actions').element.open).toBe(false)
    expect(w.find('[data-test="approve"]').exists()).toBe(false)
    expect(w.get('[data-test="verify-application"]').text()).toBe('核验申请陈述')
    await w.get('.merchant-alternative-actions summary').trigger('click')
    expect(w.find('[data-test="manual-proposal"]').exists()).toBe(true)
    w.unmount()
  })

  beforeEach(() => vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ case_version: 7, input_revision: 2, availability: 'NOT_SCHEDULED', investigation: null })))))

  it('opens the confirmed customer statement for verification without granting refund approval', async () => {
    const props = inputs(); delete props.snapshot.authorization
    props.snapshot.proposal = { origin: 'AGENT', status: 'VALIDATED', input_revision: 2, recommended_action: 'MANUAL_REVIEW', summary: '承运丢失记录已查，等待商家核验客户陈述。', policy_refs: [{ rule_id: 'lost' }] }
    props.snapshot.evidence = [{ observation_id: 'claim-1', evidence_kind: 'CUSTOMER_STATEMENT', content: '本人未收到商品，请核实后退款。', input_revision: 1 }]
    const wrapper = mount(MerchantCaseDetail, { props, slots: { materials: '<p>本人未收到商品，等待核验</p>' } })
    expect(wrapper.get('.merchant-detail-heading .status-tag').text()).toBe('待核验')
    expect(wrapper.find('[data-test="approve"]').exists()).toBe(false)
    await wrapper.get('[data-test="verify-application"]').trigger('click')
    expect(wrapper.get('[aria-label="详细依据"]').text()).toContain('本人未收到商品，等待核验')
    expect(wrapper.find('[data-test="approve"]').exists()).toBe(false)
    await wrapper.setProps({ snapshot: { ...props.snapshot, authorization: inputs().snapshot.authorization,
      proposal: inputs().snapshot.proposal } })
    expect(wrapper.find('[data-test="verify-application"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="approve"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('labels an actual current investigation failure and does not inherit it into a new revision', async () => {
    const props = inputs(); delete props.snapshot.authorization; delete props.snapshot.proposal
    props.snapshot.timeline = [{ event_id: 'failed-2', type: 'AGENT_FAILED', occurred_at: '', summary: '调查失败', revision: 2 }]
    const wrapper = mount(MerchantCaseDetail, { props })
    expect(wrapper.get('.merchant-advice-title').text()).toContain('本次调查未完成')
    expect(wrapper.get('.merchant-advice-title').text()).not.toContain('等待调查建议')
    expect(wrapper.find('[data-test="approve"]').exists()).toBe(false)
    await wrapper.setProps({ snapshot: { ...props.snapshot, case: { ...props.snapshot.case, input_revision: 3 } } })
    expect(wrapper.get('.merchant-advice-title').text()).toContain('等待调查建议')
    wrapper.unmount()
  })

  it('shows four business areas with provenance while keeping audit detail behind one entry', async () => {
    const wrapper = mount(MerchantCaseDetail, { props: inputs(), slots: { materials: '<p>原始材料及核验操作</p>' } })
    for (const label of ['商品与订单', '客户申请', '调查建议', '退款处理']) expect(wrapper.find(`[aria-label="${label}"]`).exists()).toBe(true)
    expect(wrapper.text()).toContain('无线降噪耳机')
    expect(wrapper.text()).toContain('329.00')
    expect(wrapper.text()).not.toContain('case-1')
    expect(wrapper.text()).not.toContain('人工接管与政策依据')
    await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('当前材料没有关联调查记录')
    await wrapper.get('.merchant-details-link').trigger('click'); await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[aria-label="详细依据"]').text()).toContain('原始材料及核验操作')
    await wrapper.get('[data-test="approve"]').trigger('click')
    expect(wrapper.emitted('review')).toEqual([['APPROVE']])
    wrapper.unmount()
  })

  it('keeps the full original recommendation accessible without crowding the decision area', async () => {
    const props = inputs()
    const original = '订单尚未发货，具体条件仍需结合政策核对。'.repeat(20)
    props.snapshot.proposal!.summary = original
    const wrapper = mount(MerchantCaseDetail, { props })
    const disclosure = wrapper.get('details.merchant-full-advice')
    expect(disclosure.attributes('open')).toBeUndefined()
    expect(disclosure.get('p').text()).toBe(original)
    expect(wrapper.find('[data-test="approve"]').exists()).toBe(true)
    expect(wrapper.get('.merchant-product').element.parentElement).toBe(wrapper.element)
    await wrapper.setProps({ snapshot: { ...props.snapshot, proposal: { ...props.snapshot.proposal, input_revision: 1 } } })
    expect(wrapper.find('details.merchant-full-advice').exists()).toBe(false)
    expect(wrapper.text()).toContain('旧建议已失效')
    wrapper.unmount()
  })

  it('opens the exact bound policy from the decision overview without substituting a newer clause', async () => {
    const props = inputs()
    const identity = { bundle_id: 'logistics', version: 'v1', rule_id: 'lost', chunk_id: 'c1', content_hash: 'hash-1' }
    props.snapshot.proposal!.policy_refs = [identity]
    props.context.policy_rules = [{ ...identity, title: '物流丢失处理', text: '核实丢失后处理。' }]
    const wrapper = mount(MerchantCaseDetail, { props })
    expect(wrapper.find('[aria-label="详细依据"]').exists()).toBe(false)
    await wrapper.get('.merchant-advice [data-test="policy-citation"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[aria-label="详细依据"]').text()).toContain('核实丢失后处理')
    expect(wrapper.get('.merchant-advice [data-test="policy-citation"]').text()).toContain('物流丢失处理')
    await wrapper.setProps({ context: { ...props.context, policy_rules: [{ ...props.context.policy_rules[0]!,
      version: 'v2', content_hash: 'hash-2', title: '新政策不得替代' }] } })
    expect(wrapper.find('.merchant-advice [data-test="policy-citation"]').exists()).toBe(false)
    expect(wrapper.get('.merchant-advice').text()).not.toContain('新政策不得替代')
    expect(wrapper.get('.merchant-advice').text()).toContain('未能匹配')
    wrapper.unmount()
  })

  it.each(['old-auth', 'old-proposal', 'other-owner', 'old-context', 'loading', 'context-error', 'consumed', 'unknown', 'closed'])('prevents approval for %s', kind => {
    const props = inputs()
    if (kind === 'old-auth') props.snapshot.authorization!.input_revision = 1
    if (kind === 'old-proposal') props.snapshot.proposal!.input_revision = 1
    if (kind === 'other-owner') props.collaboration.is_owner = false
    if (kind === 'old-context') props.context.case_version = 6
    if (kind === 'loading') props.contextLoading = true
    if (kind === 'context-error') props.contextError = '读取失败'
    if (kind === 'consumed') props.snapshot.authorization!.status = 'CONSUMED'
    if (kind === 'unknown') props.context.execution = { case_status: 'RECONCILING', outcome: 'UNKNOWN', operation_id: 'op-1', amount_minor: 32900, reason_code: null }
    if (kind === 'closed') props.snapshot.case.status = 'CLOSED_SUCCESS'
    const wrapper = mount(MerchantCaseDetail, { props })
    expect(wrapper.find('[data-test="approve"]').exists()).toBe(false)
    if (kind === 'unknown') expect(wrapper.text()).toContain('请勿重复发起')
    wrapper.unmount()
  })

  it('keeps stale advice, conflicts, missing evidence and server refusal visible before details', () => {
    const props = inputs()
    props.snapshot.proposal = { origin: 'AGENT', input_revision: 1, summary: '旧摘要不能当当前结论', recommended_action: 'REFUND', refusal_reason: '引用不一致',
      review_findings: [{ kind: 'CONFLICT', text: '客户描述与物流记录不一致' }], missing_evidence: ['需要核对签收'] }
    const wrapper = mount(MerchantCaseDetail, { props })
    for (const text of ['旧建议已失效', '引用不一致', '客户描述与物流记录不一致', '需要核对签收']) expect(wrapper.text()).toContain(text)
    expect(wrapper.text()).not.toContain('旧摘要不能当当前结论')
    expect(wrapper.find('[aria-label="详细依据"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('offers manual actions without inventing a refund approval or policy eligibility', () => {
    const props = inputs(); delete props.snapshot.authorization
    props.snapshot.proposal = { origin: 'AGENT', input_revision: 2, recommended_action: 'REJECT', summary: '需要核对是否适用。' }
    props.context.allowed_actions = ['MANUAL_PROPOSAL', 'REQUEST_INFO', 'REJECT']
    const wrapper = mount(MerchantCaseDetail, { props })
    expect(wrapper.find('[data-test="approve"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="manual-proposal"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('未引用政策')
    expect(wrapper.text()).not.toContain('符合本店')
    wrapper.unmount()
  })

  it('keeps the manual action dialog on the version reviewed before a refresh', async () => {
    const props = inputs(); delete props.snapshot.authorization; props.context.allowed_actions = ['REJECT']
    const wrapper = mount(MerchantCaseDetail, { props })
    await wrapper.get('[data-test="handoff-reject"]').trigger('click')
    await wrapper.setProps({ snapshot: { ...props.snapshot, case: { ...props.snapshot.case, version: 8 } }, collaboration: { ...props.collaboration, version: 2 } })
    await wrapper.get('[role="dialog"] textarea').setValue('核对政策后拒绝')
    await wrapper.get('[data-test="submit-handoff"]').trigger('click'); await flushPromises()
    const request = vi.mocked(fetch).mock.calls.find(([url]) => String(url).endsWith('/review-actions'))!
    expect(new Headers(request[1]?.headers).get('If-Match')).toBe('"7"')
    expect(new Headers(request[1]?.headers).get('If-Collaboration-Match')).toBe('"1"')
    wrapper.unmount()
  })
})
