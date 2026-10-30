import { fulfillmentApi } from '../src/fulfillment-client'
import { supportApi } from '../src/support-client'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AdminOverview from '../src/ui/AdminOverview.vue'
import AdminPolicies from '../src/ui/AdminPolicies.vue'
import { ApiError, coreApi, type AdminPolicy, type AdminPolicyDetail, type LoginResponse, type MerchantOverview } from '../src/client'

const account: LoginResponse = { access_token: 'admin', role: 'MERCHANT_ADMIN', merchant_id: 'M-1', merchant_name: '合成商家', expires_in: 3600 }
const wrappers: VueWrapper[] = []
function overview(): MerchantOverview { return { unclaimed: 42, mine: 3, attention: 1, enabled_staff: 2, coordination_total: 43,
  observed_at: '2026-10-02T01:00:00Z', items: [{ case_id: 'case-unknown', description: '合成协调事项', status: 'RECONCILING', owner_name: '售后甲', owner_username: 'worker', updated_at: '2026-10-02T01:00:00Z', reasons: ['RESULT_UNKNOWN', 'OWNER_UNAVAILABLE'] }] } }
function policy(bundle: string): AdminPolicy { return { bundle_id: bundle, version: bundle, manifest_hash: 'a'.repeat(64), safety_epoch: 1,
  effective_from: '2026-01-01T00:00:00Z', effective_to: null, imported_at: '2026-10-02T01:00:00Z', rule_count: 1 } }
function detail(bundle: string): AdminPolicyDetail { return { policy: policy(bundle), rules: [{ rule_id: 'R1', title: '原始规则', text: bundle + '条件与例外原文', chunk_id: bundle + ':0', content_hash: 'b'.repeat(64) }], index: { status: 'UNAVAILABLE' } } }
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.restoreAllMocks(); vi.useRealTimers() })

describe('merchant overview', () => {
  it('uses complete server counts, explicit reasons and existing case actions; failed reads keep data', async () => {
    vi.spyOn(coreApi, 'merchantOverview').mockResolvedValue(overview())
    const w = mount(AdminOverview, { props: { account } }); wrappers.push(w); await flushPromises()
    expect(w.get('.overview-metrics').text()).toContain('42'); expect(w.text()).toContain('1 / 43')
    expect(w.text()).toContain('负责人不可用'); expect(w.text()).toContain('退款结果待确认')
    await w.get('[aria-label="查看工单 case-unknown"]').trigger('click')
    expect(w.emitted('open')?.[0]).toEqual(['case-unknown'])
    expect(w.findAll('button').some(b => b.text().includes('批准'))).toBe(false)
    vi.mocked(coreApi.merchantOverview).mockRejectedValue(new Error('offline'))
    await w.findAll('button').find(b => b.text() === '刷新概览')!.trigger('click'); await flushPromises()
    expect(w.text()).toContain('保留上次读取'); expect(w.text()).toContain('42')
  })
  it('polls while visible, stops on unmount and ignores late responses', async () => {
    vi.useFakeTimers(); vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
    const read = vi.spyOn(coreApi, 'merchantOverview').mockResolvedValue(overview())
    const w = mount(AdminOverview, { props: { account } }); wrappers.push(w); await flushPromises()
    await vi.advanceTimersByTimeAsync(30000); await flushPromises(); expect(read).toHaveBeenCalledTimes(2)
    let resolve!: (value: MerchantOverview) => void
    read.mockReturnValue(new Promise(r => { resolve = r }))
    await w.findAll('button').find(b => b.text() === '刷新概览')!.trigger('click')
    w.unmount(); resolve(overview()); await flushPromises()
    await vi.advanceTimersByTimeAsync(30000); expect(read).toHaveBeenCalledTimes(3)
    expect(w.emitted('expired')).toBeUndefined()
  })
  it('reports invalid sessions without pretending there are zero cases', async () => {
    vi.spyOn(coreApi, 'merchantOverview').mockRejectedValue(new ApiError(401, 'UNAUTHENTICATED', 'expired'))
    const w = mount(AdminOverview, { props: { account } }); wrappers.push(w); await flushPromises()
    expect(w.emitted('expired')).toHaveLength(1); expect(w.get('.overview-metrics').text()).toContain('—')
  })
})

describe('read-only policies', () => {
  it('keeps exact original text and rejects late selection responses; unavailable is never READY', async () => {
    vi.spyOn(coreApi, 'adminPolicies').mockResolvedValue({ items: [policy('old'), policy('new')], truncated: false })
    let resolve!: (value: AdminPolicyDetail) => void
    vi.spyOn(coreApi, 'adminPolicy').mockImplementation((_token, bundle) => bundle === 'old' ? new Promise(r => { resolve = r }) : Promise.resolve(detail(bundle)))
    const w = mount(AdminPolicies, { props: { account } }); wrappers.push(w); await flushPromises()
    await w.findAll('.policy-version')[1].trigger('click'); await flushPromises()
    resolve(detail('old')); await flushPromises()
    expect(w.get('[aria-label="政策原文"]').text()).toContain('new条件与例外原文')
    expect(w.get('[aria-label="政策原文"]').text()).not.toContain('old条件与例外原文')
    expect(w.text()).toContain('索引状态暂不可用'); expect(w.text()).not.toContain('索引已就绪')
    expect(w.text()).toContain('固定政策版本')
    expect(w.findAll('button').map(b => b.text()).join()).not.toMatch(/发布|撤销政策|编辑政策/)
  })
  it('separates failed reads from a successful empty policy list and permits retry', async () => {
    const read = vi.spyOn(coreApi, 'adminPolicies').mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ items: [], truncated: false })
    const w = mount(AdminPolicies, { props: { account } }); wrappers.push(w); await flushPromises()
    expect(w.text()).toContain('无法读取'); expect(w.text()).not.toContain('尚未导入政策')
    await w.findAll('button').find(b => b.text() === '刷新政策')!.trigger('click'); await flushPromises()
    expect(read).toHaveBeenCalledTimes(2); expect(w.text()).toContain('尚未导入政策')
  })
})

it('turns the single merchant overview into scoped work lists and opens the chosen buyer', async () => {
  vi.spyOn(coreApi, 'merchantOverview').mockResolvedValue(overview())
  vi.spyOn(coreApi, 'reviewQueue').mockResolvedValue({ items: [], page: { limit: 8 }, counts: { total: 9, public: 9, mine: 9, unclaimed: 0, stages: {} } })
  vi.spyOn(fulfillmentApi, 'orders').mockResolvedValue({ items: [], next_cursor: null })
  vi.spyOn(supportApi, 'tickets').mockResolvedValue({ items: [{ conversation_id: 'c', merchant_id: 'M-1', store_name: '店铺', order_id: 'o', line_id: 'l', product: { name: '耳机', variant: '黑色', asset_key: 'headphones', quantity: 1, amount_minor: 32900, currency: 'CNY' }, version: 1, buyer: { display_name: '卡皮巴拉', avatar_id: null }, ticket: { ticket_id: 'ticket-1', summary: '请核查物流', status: 'PENDING', shared_messages: [] }, messages: [], next_before_sequence: null }], next_before: null, counts: { ALL: 30, PENDING: 12, WAITING_CUSTOMER: 16, ANSWERED: 2 } })
  const w = mount(AdminOverview, { props: { account: { ...account, single_operator: true } } }); wrappers.push(w); await flushPromises()
  expect(w.get('[data-metric="review"]').text()).toContain('9')
  expect(w.get('[data-metric="support"]').text()).toContain('12')
  expect(w.get('[aria-label="待回复咨询"]').text()).toContain('卡皮巴拉')
  await w.get('[data-overview-ticket="ticket-1"]').trigger('click')
  expect(w.emitted('support')?.[0]).toEqual(['ticket-1'])
  expect(w.text()).toContain('暂无待发货订单')
  await w.findAll('button').find(b => b.text() === '全部售后')!.trigger('click')
  expect(w.emitted('queue')?.[0]).toEqual(['ALL', 'PUBLIC'])
  await w.get('.merchant-attention-task').trigger('click')
  expect(w.emitted('open')?.[0]).toEqual(['case-unknown'])
  vi.mocked(supportApi.tickets).mockRejectedValue(new Error('offline'))
  await w.findAll('button').find(b => b.text() === '刷新概览')!.trigger('click'); await flushPromises()
  expect(w.get('[data-metric="support"]').text()).toContain('—')
  expect(w.get('[aria-label="待回复咨询"]').text()).toContain('暂时无法读取')
})

it('pages policy versions without losing any original clauses', async () => {
  vi.spyOn(coreApi, 'adminPolicies').mockResolvedValue({ items: Array.from({ length: 9 }, (_, i) => policy('version-' + i)), truncated: false })
  vi.spyOn(coreApi, 'adminPolicy').mockImplementation(async (_token, id) => detail(id))
  const w = mount(AdminPolicies, { props: { account } }); wrappers.push(w); await flushPromises()
  expect(w.findAll('.policy-version')).toHaveLength(6)
  await w.findAll('button').find(b => b.text() === '下一页')!.trigger('click'); await flushPromises()
  expect(w.findAll('.policy-version')).toHaveLength(3)
  expect(w.get('[aria-label="政策原文"]').text()).toContain('version-6条件与例外原文')
  expect(w.get('h1').text()).toBe('退款规则')
  await w.findAll('button').find(b => b.text() === '上一页')!.trigger('click'); await flushPromises()
  expect(w.findAll('.policy-version')).toHaveLength(6)
})
