import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { coreApi, type CaseSnapshot, type InvestigationView } from '../src/client'
import InvestigationSources from '../src/ui/InvestigationSources.vue'

const snapshot: CaseSnapshot = { case: { case_id: 'case', line_id: 'line', version: 3, input_revision: 1, status: 'PENDING_REVIEW' }, evidence: [], timeline: [],
  proposal: { evidence_refs: [{ observation_id: 'obs', source_ref: 'line:1/shipment', source_version: '1', content_hash: 'hash' }],
    review_findings: [{ kind: 'FACT', text: '物流报告丢失', observation_ids: ['obs'] }] } }
const packet: InvestigationView = { case_version: 3, input_revision: 1, availability: 'AVAILABLE', investigation: {
  run_id: 'run', case_id: 'case', input_revision: 1, status: 'COMPLETED', model_provider: 'mock', model_id: 'script', truncated: false,
  observations: [{ call_id: 'tool-1', observation_id: 'obs', tool_name: 'get_shipment_trace', source_type: 'CARRIER', source_ref: 'line:1/shipment', source_version: '1', content_hash: 'hash', observed_at: '2026-09-29', result: { conclusion: 'LOST' }, error_code: null, body_omitted: false }] } }
afterEach(() => vi.restoreAllMocks())
describe('recorded investigation sources', () => {
  it('shows original tool results, labels mock and matches citation version/hash', async () => {
    vi.spyOn(coreApi, 'investigation').mockResolvedValue(structuredClone(packet))
    const view = mount(InvestigationSources, { props: { token: 'fixture', snapshot } })
    await flushPromises()
    expect(view.text()).toContain('mock 合成决策')
    expect(view.text()).toContain('本方案引用')
    expect(view.text()).toContain('LOST')
    expect(view.text()).not.toContain('原始正文尚未提供')
    view.unmount()
  })
  it('does not pass an observation with mismatched hash off as the cited original', async () => {
    const changed = structuredClone(packet); changed.investigation!.observations[0].content_hash = 'different'
    vi.spyOn(coreApi, 'investigation').mockResolvedValue(changed)
    const view = mount(InvestigationSources, { props: { token: 'fixture', snapshot } }); await flushPromises()
    expect(view.text()).toContain('原始正文尚未提供'); expect(view.text()).not.toContain('本方案引用')
    view.unmount()
  })
  it('discards late results after switching cases and exposes unavailability', async () => {
    let complete!: (value: InvestigationView) => void
    vi.spyOn(coreApi, 'investigation').mockImplementationOnce(() => new Promise(resolve => { complete = resolve }))
      .mockResolvedValueOnce({ case_version: 3, input_revision: 1, availability: 'UNAVAILABLE', investigation: null })
    const view = mount(InvestigationSources, { props: { token: 'fixture', snapshot } })
    await view.setProps({ snapshot: { ...snapshot, case: { ...snapshot.case, case_id: 'other' } } }); await flushPromises()
    complete(packet); await flushPromises()
    expect(view.text()).toContain('调查服务暂不可用'); expect(view.text()).not.toContain('LOST')
    view.unmount()
  })
})
