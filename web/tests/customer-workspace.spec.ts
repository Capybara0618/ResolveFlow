import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CustomerWorkspace from '../src/ui/CustomerWorkspace.vue'
import { ApiError, coreApi, type CustomerCaseDetail, type LoginResponse, type OrderLine } from '../src/client'

const account: LoginResponse = { access_token: 'customer-token', role: 'CUSTOMER', merchant_id: 'M-1001',
  customer_id: 'C-2002', expires_in: 3600, display_name: '客户甲' }
const line: OrderLine = { order_id: 'order-1', line_id: '7001', sku: 'SKU-CUP', product_name: '保温杯',
  variant_text: '蓝色', category: 'home', quantity: 1, line_paid_amount: 2599, currency: 'CNY', status: 'PAID' }
function detail(id = 'case-1'): CustomerCaseDetail {
  return { case: { case_id: id, line_id: '7001', order_id: 'order-1', description: '包裹未收到',
    status: 'WAITING_CUSTOMER', version: 7, created_at: '2026-10-01T01:00:00Z', updated_at: '2026-10-01T02:00:00Z' },
    input_revision: 2, allowed_actions: ['ANSWER', 'CANCEL'], blocked_reason: '', materials: [],
    questions: [{ question_id: 'question-1', prompts: ['请补充承运商反馈'], status: 'PENDING',
      asked_at: new Date().toISOString(), expires_at: new Date(Date.now() + 3600000).toISOString(), answers: [] }],
    result: { status: 'WAITING_CUSTOMER', message: '商家需要您补充说明', amount_minor: null, currency: 'CNY', public_reason: null }, timeline: [] }
}
const wrappers: VueWrapper[] = []
function open() { const w = mount(CustomerWorkspace, { props: { account } }); wrappers.push(w); return w }
beforeEach(() => {
  window.history.replaceState(null, '', '/#/customer/orders')
  vi.spyOn(coreApi, 'orders').mockResolvedValue({ items: [line], page: { limit: 20 } })
  vi.spyOn(coreApi, 'customerCases').mockResolvedValue({ items: [detail().case], page: { limit: 20 } })
  vi.spyOn(coreApi, 'customerOrderLine').mockResolvedValue({ order_line: line, application: null, can_apply: true, blocked_reason: '' })
  vi.spyOn(coreApi, 'customerCase').mockResolvedValue(detail())
})
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('customer application workspace', () => {
  it('answers the server question with the reviewed version and preserves the original request', async () => {
    window.history.replaceState(null, '', '/#/customer/applications/case-1')
    const answered = detail(); answered.case.status = 'QUEUED'; answered.case.version = 8
    answered.allowed_actions = ['APPEND_EVIDENCE', 'CANCEL']; answered.questions[0].status = 'ANSWERED'
    answered.questions[0].answers = [{ id: 'ev-1', text: '承运商反馈丢失', question_id: 'question-1',
      submitted_at: new Date().toISOString(), verification_result: null }]
    vi.spyOn(coreApi, 'answerQuestion').mockResolvedValue(answered)
    const w = open(); await flushPromises()
    expect(w.text()).toContain('包裹未收到'); expect(w.text()).toContain('请补充承运商反馈')
    expect(w.find('input[name="question-id"]').exists()).toBe(false)
    await w.get('[data-test="answer-text"]').setValue('承运商反馈丢失')
    await w.get('form').trigger('submit'); await flushPromises()
    expect(coreApi.answerQuestion).toHaveBeenCalledWith('customer-token', expect.objectContaining({ case: expect.objectContaining({ version: 7 }) }), 'question-1', '承运商反馈丢失')
    expect(w.text()).toContain('承运商反馈丢失'); expect(w.text()).toContain('包裹未收到')
    expect(w.find('[data-test="submit-answer"]').exists()).toBe(false)
  })

  it('keeps consumed UNKNOWN read-only and never claims a successful refund', async () => {
    window.history.replaceState(null, '', '/#/customer/applications/case-1')
    const view = detail(); view.case.status = 'RECONCILING'; view.allowed_actions = []
    view.blocked_reason = '退款已进入执行阶段，不能撤销或修改材料'
    view.result = { status: 'RECONCILING', message: '退款结果待确认，请勿重复申请', amount_minor: 2599, currency: 'CNY', public_reason: null }
    vi.mocked(coreApi.customerCase).mockResolvedValue(view)
    const w = open(); await flushPromises()
    expect(w.text()).toContain('结果待确认'); expect(w.text()).not.toContain('模拟退款已完成')
    expect(w.find('textarea').exists()).toBe(false); expect(w.find('[data-test="cancel-case"]').exists()).toBe(false)
  })

  it('disables an expired pending question without extending its deadline', async () => {
    window.history.replaceState(null, '', '/#/customer/applications/case-1')
    const view = detail(); view.questions[0].expires_at = new Date(Date.now() - 1000).toISOString()
    vi.mocked(coreApi.customerCase).mockResolvedValue(view)
    const w = open(); await flushPromises()
    expect(w.text()).toContain('补证期限已过'); expect(w.find('[data-test="submit-answer"]').exists()).toBe(false)
  })

  it('retries only the unsaved initial material after creation succeeds', async () => {
    vi.spyOn(coreApi, 'createCase').mockResolvedValue({ case_id: 'case-1' })
    vi.spyOn(coreApi, 'appendEvidence').mockRejectedValueOnce(new ApiError(422, 'SEMANTIC_INVALID', '材料未保存')).mockResolvedValue({ input_revision: 2 })
    const view = detail(); view.case.status = 'QUEUED'; view.allowed_actions = ['APPEND_EVIDENCE', 'CANCEL']; view.questions = []
    vi.mocked(coreApi.customerCase).mockResolvedValue(view)
    const w = open(); await flushPromises()
    await w.get('[data-test="apply-7001"]').trigger('click'); await flushPromises()
    await w.get('[data-test="application-description"]').setValue('包裹未收到')
    await w.get('[data-test="initial-material"]').setValue('物流三天未更新')
    await w.get('form').trigger('submit'); await flushPromises()
    expect(w.text()).toContain('申请已创建'); expect(w.get('[data-test="material-text"]').element).toHaveProperty('value', '物流三天未更新')
    await w.get('form').trigger('submit'); await flushPromises()
    expect(coreApi.createCase).toHaveBeenCalledTimes(1); expect(coreApi.appendEvidence).toHaveBeenCalledTimes(2)
  })

  it('replays an uncertain creation with the same key and frozen body', async () => {
    vi.stubGlobal('crypto', { randomUUID: () => 'stable-create-key' })
    vi.spyOn(coreApi, 'createCase').mockRejectedValueOnce(new TypeError('connection lost')).mockResolvedValue({ case_id: 'case-1' })
    const w = open(); await flushPromises()
    await w.get('[data-test="apply-7001"]').trigger('click'); await flushPromises()
    await w.get('[data-test="application-description"]').setValue('包裹未收到')
    await w.get('form').trigger('submit'); await flushPromises()
    expect(w.text()).toContain('结果尚未确认'); expect(w.get('[data-test="application-description"]').attributes('readonly')).toBeDefined()
    await w.get('form').trigger('submit'); await flushPromises()
    expect(vi.mocked(coreApi.createCase).mock.calls).toEqual([
      ['customer-token', '7001', '包裹未收到', 'stable-create-key'], ['customer-token', '7001', '包裹未收到', 'stable-create-key'],
    ])
  })

  it('discards a late detail response after navigating back to the list', async () => {
    window.history.replaceState(null, '', '/#/customer/applications/case-1')
    let finish!: (d: CustomerCaseDetail) => void
    vi.mocked(coreApi.customerCase).mockReturnValue(new Promise(resolve => { finish = resolve }))
    const w = open(); await flushPromises()
    await w.get('[data-test="nav-applications"]').trigger('click'); await flushPromises()
    finish(detail()); await flushPromises()
    expect(w.find('[data-test="application-detail"]').exists()).toBe(false)
    expect(w.find('[data-test="applications-list"]').exists()).toBe(true)
  })

  it('reconciles a lost material response on refresh without duplicating the write', async () => {
    window.history.replaceState(null, '', '/#/customer/applications/case-1')
    const view = detail(); view.case.status = 'QUEUED'; view.allowed_actions = ['APPEND_EVIDENCE']; view.questions = []
    vi.mocked(coreApi.customerCase).mockResolvedValue(view)
    vi.spyOn(coreApi, 'appendEvidence').mockRejectedValue(new TypeError('response lost'))
    const w = open(); await flushPromises()
    await w.get('[data-test="material-text"]').setValue('新的运输说明')
    await w.get('form').trigger('submit'); await flushPromises()
    expect(w.get('[data-test="append-evidence"]').attributes('disabled')).toBeDefined()
    const saved = structuredClone(view); saved.case.version = 8
    saved.materials = [{ id: 'new-material', text: '新的运输说明', question_id: null,
      submitted_at: new Date().toISOString(), verification_result: null }]
    vi.mocked(coreApi.customerCase).mockResolvedValue(saved)
    await w.findAll('button').find(b => b.text() === '刷新')!.trigger('click'); await flushPromises()
    expect(w.text()).toContain('已核对：材料已保存')
    expect(w.get('[data-test="material-text"]').element).toHaveProperty('value', '')
    expect(coreApi.appendEvidence).toHaveBeenCalledTimes(1)
  })

  it('refreshes a stale answer while keeping the draft and emits expired on an invalid session', async () => {
    window.history.replaceState(null, '', '/#/customer/applications/case-1')
    vi.spyOn(coreApi, 'answerQuestion').mockRejectedValue(new ApiError(409, 'CONFLICT', '版本已变化'))
    const w = open(); await flushPromises()
    const newer = detail(); newer.case.version = 8
    vi.mocked(coreApi.customerCase).mockResolvedValue(newer)
    await w.get('[data-test="answer-text"]').setValue('仍需核对的回答')
    await w.get('form').trigger('submit'); await flushPromises()
    expect(w.text()).toContain('申请状态已更新')
    expect(w.get('[data-test="answer-text"]').element).toHaveProperty('value', '仍需核对的回答')
    vi.mocked(coreApi.customerCase).mockRejectedValue(new ApiError(401, 'UNAUTHORIZED', '会话过期'))
    await w.findAll('button').find(b => b.text() === '刷新')!.trigger('click'); await flushPromises()
    expect(w.emitted('expired')).toHaveLength(1)
  })
})
