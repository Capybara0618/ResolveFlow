import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import InvestigationFindings from '../src/ui/InvestigationFindings.vue'
import type { CaseSnapshot } from '../src/client'

describe('investigation evidence', () => {
  it('separates model summaries from raw statements and marks unavailable originals', () => {
    const snapshot: CaseSnapshot = {
      case: { case_id: 'c', line_id: 'l', input_revision: 2, version: 3, status: 'PENDING_REVIEW' },
      evidence: [{ observation_id: 'ev-1', evidence_kind: 'CUSTOMER_STATEMENT', content: '原始客户陈述：未收到包裹' }], timeline: [],
      proposal: { origin: 'AGENT', status: 'STALE', missing_evidence: ['补充签收争议材料'],
        evidence_refs: [{ observation_id: 'ship-1', source_ref: 'line:l/shipment', source_version: '2' }],
        review_findings: [
          { kind: 'FACT', text: '客户称未收到', observation_ids: ['ev-1'] },
          { kind: 'CONFLICT', text: '签收状态与客户陈述不一致', observation_ids: ['ev-1', 'ship-1'] },
        ] },
    }
    const wrapper = mount(InvestigationFindings, { props: { snapshot } })
    expect(wrapper.text()).toContain('来源陈述 · Agent 整理')
    expect(wrapper.text()).toContain('原始客户陈述：未收到包裹')
    expect(wrapper.text()).toContain('原始正文尚未提供')
    expect(wrapper.text()).toContain('信息冲突')
    expect(wrapper.text()).toContain('已过期')
    expect(wrapper.text()).toContain('补充签收争议材料')
    expect(wrapper.text()).not.toContain('真实性已核验：是')
  })
})
