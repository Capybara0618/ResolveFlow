import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PolicyCitations from '../src/ui/PolicyCitations.vue'
import { policyKey } from '../src/ui/investigation-format'

const rule = {
  bundle_id: 'policy-logistics-2026.09', version: '2026.09', rule_id: 'R-LOST-001', title: '承运商判定丢失',
  text: '承运商结论为 LOST 且无有效签收记录时，可按该订单行支付金额全额退款。', chunk_id: 'c-01',
  content_hash: 'a'.repeat(64),
}
const ref = {
  bundle_id: rule.bundle_id, version: rule.version, rule_id: rule.rule_id, chunk_id: rule.chunk_id,
  content_hash: rule.content_hash,
}

describe('proposal citations', () => {
  it('opens a clause only for a citation that matches on all five members', async () => {
    const wrapper = mount(PolicyCitations, { props: { policyRefs: [ref], policyRules: [rule], policyStatus: 'PINNED' } })
    const button = wrapper.get('[data-test="policy-citation"]')
    expect(button.text()).toContain('承运商判定丢失')
    expect(button.text()).toContain('c-01')
    await button.trigger('click')
    expect(wrapper.emitted('focus')?.[0]).toEqual([policyKey(rule)])
  })

  it('says a citation that names nothing bound cannot be matched, and offers no link', () => {
    const other = { ...ref, bundle_id: 'policy-logistics-2026.08', version: '2026.08', content_hash: 'b'.repeat(64) }
    const wrapper = mount(PolicyCitations, { props: { policyRefs: [other], policyRules: [rule], policyStatus: 'PINNED' } })
    expect(wrapper.find('[data-test="policy-citation"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="policy-citation-mismatch"]').text()).toContain('该引用未能匹配当前绑定政策')
    expect(wrapper.text()).toContain('bundle_id=policy-logistics-2026.08')
  })

  it('names the members a historical citation never recorded', () => {
    const wrapper = mount(PolicyCitations, {
      props: { policyRefs: [{ bundle_id: ref.bundle_id, rule_id: ref.rule_id }], policyRules: [rule], policyStatus: 'PINNED' },
    })
    const warning = wrapper.get('[data-test="policy-citation-incomplete"]').text()
    expect(warning).toContain('缺少')
    expect(warning).toContain('chunk_id')
    expect(warning).toContain('content_hash')
    expect(wrapper.text()).not.toContain('承运商结论为 LOST')
  })

  it('tells the reviewer when there is no bound policy to compare against', () => {
    const wrapper = mount(PolicyCitations, { props: { policyRefs: [ref], policyRules: [], policyStatus: 'UNAVAILABLE' } })
    expect(wrapper.get('[data-test="policy-unavailable"]').text()).toContain('暂无可读取的绑定政策')
  })

  it('flags an evidence citation that is missing any of its four members', () => {
    const wrapper = mount(PolicyCitations, {
      props: {
        evidenceRefs: [
          { observation_id: 'obs-1', source_ref: 'line:1/shipment', source_version: '2' },
          { observation_id: 'obs-2', source_ref: 'line:1/order', source_version: '1', content_hash: 'c'.repeat(64) },
        ],
        policyRefs: [], policyRules: [],
      },
    })
    expect(wrapper.get('[data-test="evidence-citation-incomplete"]').text()).toContain('content_hash')
    expect(wrapper.text()).toContain('line:1/shipment')
    expect(wrapper.text()).toContain('line:1/order')
    expect(wrapper.findAll('[data-test="evidence-citation-incomplete"]')).toHaveLength(1)
  })
})
