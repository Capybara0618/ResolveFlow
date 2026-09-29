import { describe, expect, it } from 'vitest'
import {
  evidenceKey,
  matchEvidenceReference,
  matchPolicyReference,
  missingEvidenceMembers,
  policyKey,
  sourceOf,
  splitPolicySpans,
  summarizeObservation,
  toolLabel,
} from '../src/ui/investigation-format'

const rule = {
  bundle_id: 'policy-logistics-2026.09', version: '2026.09', rule_id: 'R-LOST-001',
  title: '承运商判定丢失', text: '承运商结论为 LOST 且无有效签收记录时，可按该订单行支付金额全额退款。',
  chunk_id: 'c-01', content_hash: 'a'.repeat(64),
}
const sameNameOtherVersion = {
  ...rule, bundle_id: 'policy-logistics-2026.08', version: '2026.08', chunk_id: 'c-01', content_hash: 'b'.repeat(64),
}
const citation = {
  observation_id: 'obs-1', source_ref: 'commerce:/internal/v1/order-lines/1/shipment',
  source_version: '2', content_hash: 'c'.repeat(64),
}

describe('policy citation identity', () => {
  it('requires all five members before a citation can be located at all', () => {
    expect(policyKey(rule)).not.toBeNull()
    for (const member of ['bundle_id', 'version', 'rule_id', 'chunk_id', 'content_hash'] as const) {
      const partial: Record<string, unknown> = { ...rule }
      delete partial[member]
      expect(policyKey(partial)).toBeNull()
      expect(matchPolicyReference(partial, [rule]).state).toBe('INCOMPLETE')
      expect(missingPolicy(partial)).toContain(member)
    }
  })

  it('does not locate a clause when any single member differs', () => {
    for (const member of ['bundle_id', 'version', 'rule_id', 'chunk_id', 'content_hash'] as const) {
      const changed = { ...rule, [member]: `${rule[member]}-changed` }
      expect(matchPolicyReference(changed, [rule]).state).toBe('MISMATCH')
    }
  })

  it('does not match a same-named rule from another bundle version', () => {
    expect(policyKey(sameNameOtherVersion)).not.toBe(policyKey(rule))
    expect(matchPolicyReference(rule, [sameNameOtherVersion]).state).toBe('MISMATCH')
  })

  it('locates the clause only when every member is equal', () => {
    const match = matchPolicyReference({ ...rule }, [sameNameOtherVersion, rule])
    expect(match.state).toBe('MATCHED')
    if (match.state === 'MATCHED') expect(match.rule.title).toBe('承运商判定丢失')
  })
})

function missingPolicy(reference: unknown): string[] {
  const result = matchPolicyReference(reference, [])
  return result.state === 'INCOMPLETE' ? result.missing : []
}

describe('evidence citation identity', () => {
  it('requires all four members', () => {
    expect(evidenceKey(citation)).not.toBeNull()
    expect(missingEvidenceMembers({ observation_id: 'obs-1', source_ref: 'x', source_version: '2' })).toEqual(['content_hash'])
    expect(matchEvidenceReference({ observation_id: 'obs-1' }, [citation]).state).toBe('INCOMPLETE')
  })

  it('does not treat the same observation id at another version or hash as the cited record', () => {
    const reread = { ...citation, source_version: '3' }
    expect(matchEvidenceReference(reread, [citation]).state).toBe('MISMATCH')
    const rehashed = { ...citation, content_hash: 'd'.repeat(64) }
    expect(matchEvidenceReference(rehashed, [citation]).state).toBe('MISMATCH')
    expect(matchEvidenceReference({ ...citation }, [citation]).state).toBe('MATCHED')
  })
})

describe('source projection', () => {
  const snapshot = {
    evidence: [{ observation_id: 'obs-1', content: '客户材料正文', source_ref: citation.source_ref,
      source_version: '2', content_hash: citation.content_hash, evidence_kind: 'CUSTOMER_STATEMENT' }],
    proposal: { evidence_refs: [{ ...citation }] },
  }

  it('shows material text when the citation matches on all four members', () => {
    expect(sourceOf('obs-1', snapshot, []).state).toBe('MATERIAL')
  })
  it('refuses the material when the recorded hash differs, and says so', () => {
    const changed = { ...snapshot, evidence: [{ ...snapshot.evidence[0], content_hash: 'e'.repeat(64) }] }
    const view = sourceOf('obs-1', changed, [])
    expect(view.state).toBe('VERSION_MISMATCH')
    if (view.state === 'VERSION_MISMATCH') expect(view).not.toHaveProperty('text')
  })
  it('reports a proposal that recorded no full citation instead of borrowing current material', () => {
    const historical = { ...snapshot, proposal: { evidence_refs: [{ observation_id: 'obs-1', source_ref: citation.source_ref }] } }
    expect(sourceOf('obs-1', historical, []).state).toBe('UNCITED')
  })
})

describe('tool summaries', () => {
  it('formats integer minor units and keeps zero distinct from absent', () => {
    const facts = summarizeObservation('get_order_context', {
      line_id: '9-1', sku: 'SKU', category: 'electronics', quantity: 1,
      line_paid_amount: 32900, refunded_amount: 0, currency: 'CNY',
    })
    expect(facts.map(fact => fact.value)).toContain('329.00 CNY')
    expect(facts.find(fact => fact.label === '已退金额')?.value).toBe('0.00 CNY')
    expect(facts.find(fact => fact.label === '预留金额')).toBeUndefined()
  })

  it('reports a carrier conclusion and the events that support it, without calling SIGNED receipt', () => {
    const facts = summarizeObservation('get_shipment_trace', {
      status: 'DELIVERED', carrier_conclusion: 'DELIVERED', synthetic: true, next_cursor: null,
      events: [{ code: 'DELIVERED', occurred_at: '2026-09-13T16:20:00Z', source_version: 3 }],
    })
    expect(facts.find(fact => fact.label === '承运商结论')?.value).toBe('已送达')
    expect(facts.find(fact => fact.label === '关键事件')?.value).toContain('2026-09-13T16:20:00Z')
    expect(facts.map(fact => fact.value).join(' ')).not.toContain('客户认可')
  })

  it('reports relevance as relevance and never as entitlement or confidence', () => {
    const facts = summarizeObservation('search_policy', {
      query: '丢失', hit_count: 1,
      hits: [{ title: '承运商判定丢失', bundle_id: 'b', version: '2026.09', rule_id: 'R-LOST-001', score: 0.677452 }],
    })
    const text = facts.map(fact => `${fact.label}=${fact.value}`).join(' ')
    expect(text).toContain('相关度 0.677')
    expect(text).toContain('不代表退款资格或模型置信度')
  })

  it('says the evidence tool returns citations rather than material text', () => {
    const facts = summarizeObservation('get_case_evidence', { input_revision: 2, evidence: [{ observation_id: 'e' }] })
    expect(facts.find(fact => fact.label === '材料条数')?.value).toBe('1')
    expect(facts.map(fact => fact.value).join(' ')).toContain('引用不等于已核验')
  })

  it('leaves an unknown or empty result to the raw view and keeps tool labels honest', () => {
    expect(summarizeObservation('some_future_tool', { a: 1 })).toEqual([])
    expect(summarizeObservation('get_shipment_trace', null)).toEqual([])
    expect(toolLabel('search_policy')).toBe('检索政策片段')
    expect(toolLabel('some_future_tool')).toBe('some_future_tool')
    expect(toolLabel(undefined)).toBe('未知工具')
  })
})

describe('clause text', () => {
  it('splits original sentences and marks only those containing limiting phrasing', () => {
    const spans = splitPolicySpans(rule.text + '\n例外：本规则不适用于超过 500000 分的订单行，必须转人工。')
    expect(spans).toHaveLength(2)
    expect(spans[0].limiting).toBe(false)
    expect(spans[1].limiting).toBe(true)
    // The stored characters are preserved exactly; marking adds no words of its own.
    expect(spans[1].text).toBe('例外：本规则不适用于超过 500000 分的订单行，必须转人工。')
    expect(spans.map(span => span.text).join('')).toBe(rule.text + '例外：本规则不适用于超过 500000 分的订单行，必须转人工。')
  })
  it('handles a clause that is absent rather than guessing one', () => {
    expect(splitPolicySpans(null)).toEqual([])
    expect(splitPolicySpans('')).toEqual([])
  })
})
