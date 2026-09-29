import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import InvestigationFindings from '../src/ui/InvestigationFindings.vue'
import type { CaseSnapshot, InvestigationObservation } from '../src/client'

const HASH = 'a'.repeat(64)
const material = {
  observation_id: 'ev-1', evidence_kind: 'CUSTOMER_STATEMENT', content: '原始客户陈述：未收到包裹',
  source_ref: 'customer:C-2002', source_version: '2', content_hash: HASH,
}
function snapshotWith(proposal: Record<string, unknown>): CaseSnapshot {
  return {
    case: { case_id: 'c', line_id: 'l', input_revision: 2, version: 3, status: 'PENDING_REVIEW' },
    evidence: [material], timeline: [], proposal,
  }
}
const finding = (ids: string[]) => [{ kind: 'FACT' as const, text: '客户称未收到', observation_ids: ids }]

describe('investigation evidence', () => {
  it('shows material text only when the citation matches all four members', () => {
    const wrapper = mount(InvestigationFindings, {
      props: {
        snapshot: snapshotWith({
          origin: 'AGENT', status: 'VALIDATED', input_revision: 2, review_findings: finding(['ev-1']),
          evidence_refs: [{ observation_id: 'ev-1', source_ref: 'customer:C-2002', source_version: '2', content_hash: HASH }],
        }),
      },
    })
    expect(wrapper.text()).toContain('来源陈述 · Agent 整理')
    expect(wrapper.text()).toContain('原始客户陈述：未收到包裹')
    expect(wrapper.text()).toContain('四项引用与本条材料一致')
    expect(wrapper.text()).not.toContain('真实性已核验：是')
  })

  it('refuses to borrow today’s material when the citation names another version or hash', () => {
    const wrapper = mount(InvestigationFindings, {
      props: {
        snapshot: snapshotWith({
          origin: 'AGENT', status: 'VALIDATED', input_revision: 2, review_findings: finding(['ev-1']),
          evidence_refs: [{ observation_id: 'ev-1', source_ref: 'customer:C-2002', source_version: '2', content_hash: 'b'.repeat(64) }],
        }),
      },
    })
    expect(wrapper.text()).toContain('该引用与当前材料或已保存记录的来源、版本或内容摘要不一致')
    expect(wrapper.text()).not.toContain('原始客户陈述：未收到包裹')
  })

  it('says a historical proposal with an incomplete citation cannot be cross-checked', () => {
    const wrapper = mount(InvestigationFindings, {
      props: {
        snapshot: snapshotWith({
          origin: 'AGENT', status: 'STALE', input_revision: 2, review_findings: finding(['ev-1']),
          evidence_refs: [{ observation_id: 'ev-1', source_ref: 'customer:C-2002', source_version: '2' }],
        }),
      },
    })
    expect(wrapper.text()).toContain('此历史方案未记录完整引用，无法与当前材料核对')
    expect(wrapper.text()).not.toContain('原始客户陈述：未收到包裹')
    expect(wrapper.text()).toContain('已过期')
  })

  it('falls back to the saved tool record and summarises it without replacing the raw result', () => {
    const observations: InvestigationObservation[] = [{
      call_id: 'tool-0', observation_id: 'obs-ship', tool_name: 'get_shipment_trace',
      source_type: 'SHIPMENT', source_ref: 'commerce:/internal/v1/order-lines/l/shipment',
      source_version: '2', content_hash: 'c'.repeat(64), observed_at: '2026-09-28T00:00:00Z',
      result: { carrier_conclusion: 'LOST', status: 'LOST', synthetic: true,
        events: [{ code: 'CARRIER_LOST', occurred_at: '2026-09-12T07:30:00Z', source_version: 2 }] },
      body_omitted: false, error_code: null,
    }]
    const wrapper = mount(InvestigationFindings, {
      props: {
        snapshot: snapshotWith({
          origin: 'AGENT', status: 'VALIDATED', input_revision: 2, review_findings: finding(['obs-ship']),
          evidence_refs: [{ observation_id: 'obs-ship', source_ref: 'commerce:/internal/v1/order-lines/l/shipment',
            source_version: '2', content_hash: 'c'.repeat(64) }],
        }),
        observations,
      },
    })
    expect(wrapper.text()).toContain('承运商确认丢失')
    expect(wrapper.text()).toContain('合成数据')
    expect(wrapper.text()).toContain('四项引用与已保存记录一致')
    expect(wrapper.text()).toContain('展开完整原始结果')
    expect(wrapper.text()).toContain('CARRIER_LOST')
  })

  it('keeps the missing-evidence list and shows no verification tick', () => {
    const wrapper = mount(InvestigationFindings, {
      props: {
        snapshot: snapshotWith({
          origin: 'AGENT', status: 'STALE', missing_evidence: ['补充签收争议材料'],
          review_findings: [{ kind: 'CONFLICT', text: '签收状态与客户陈述不一致', observation_ids: ['ev-1', 'ship-1'] }],
          evidence_refs: [{ observation_id: 'ship-1', source_ref: 'line:l/shipment', source_version: '2' }],
        }),
      },
    })
    expect(wrapper.text()).toContain('信息冲突')
    expect(wrapper.text()).toContain('补充签收争议材料')
    expect(wrapper.text()).toContain('此历史方案未记录完整引用')
    expect(wrapper.text()).not.toContain('原始客户陈述：未收到包裹')
    expect(wrapper.text()).not.toContain('真实性已核验：是')
  })
})
