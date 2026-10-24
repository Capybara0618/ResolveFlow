import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import SupportRefundCard from '../src/ui/SupportRefundCard.vue'
import { refundApi, type RefundView } from '../src/support-refund'
import type { CustomerCaseDetail } from '../src/client'
import type { SupportConversation } from '../src/support-client'
import fixture from '../../contracts/core/fixtures/support.json'
import refundFixture from '../../contracts/core/fixtures/support-refund.json'

let wrapper: VueWrapper
const current = () => ({ draft: { ...structuredClone(refundFixture.Draft), expires_at: new Date(Date.now() + 1800000).toISOString() }, application: null }) as RefundView
const props = () => ({ token: 'token', owner: 'buyer-1', conversation: { ...structuredClone(fixture.Conversation), version: 1 } as SupportConversation })
const application = (status = 'QUEUED') => ({ case: { case_id: 'one-case', status, description: '已确认原因' }, result: { status, message: '核查处理中' }, timeline: [], materials: [], questions: [], allowed_actions: [], blocked_reason: '' }) as unknown as CustomerCaseDetail
beforeEach(() => { sessionStorage.clear(); vi.spyOn(refundApi, 'read').mockResolvedValue(current()) })
afterEach(() => { wrapper?.unmount(); vi.restoreAllMocks(); sessionStorage.clear() })

it.each(['等待商家核验申请情况', '本次调查未完成，已转商家继续核查', '退款方案已生成，等待商家审批'])('shows the server-projected pending-review stage: %s', async message => {
  const view = application('PENDING_REVIEW'); view.result.message = message
  vi.mocked(refundApi.read).mockResolvedValue({ draft: null, application: view })
  wrapper = mount(SupportRefundCard, { props: props() }); await flushPromises()
  expect(wrapper.get('.refund-progress header strong').text()).toBe(message)
  expect(wrapper.find('[data-refund="confirm"]').exists()).toBe(false)
  expect(wrapper.text()).not.toContain('退款完成')
})

it('requires an explicit confirm and displays the same application after submission', async () => {
  const result = { ...current(), draft: { ...current().draft!, status: 'CONFIRMED' as const, case_id: 'one-case' }, application: application() }
  const mutate = vi.spyOn(refundApi, 'mutate').mockResolvedValue(result)
  wrapper = mount(SupportRefundCard, { props: props() }); await flushPromises()
  expect(wrapper.text()).toContain('329.00')
  expect(mutate).not.toHaveBeenCalled()
  await wrapper.get('[data-refund="confirm"]').trigger('click'); await flushPromises()
  expect(mutate.mock.calls[0][1]).toMatchObject({ kind: 'confirm', body: { revision: 1, expected_version: 1 } })
  expect(wrapper.text()).toContain('申请已提交')
  expect(wrapper.get('a').attributes('href')).toBe('#/customer/applications/one-case')
})

it('edits and saves the reason before allowing confirmation', async () => {
  const mutate = vi.spyOn(refundApi, 'mutate').mockResolvedValue({ ...current(), draft: { ...current().draft!, reason: '客户修改原因', revision: 2 } })
  wrapper = mount(SupportRefundCard, { props: props() }); await flushPromises()
  await wrapper.get('[data-refund="edit"]').trigger('click')
  await wrapper.get('textarea').setValue('客户修改原因')
  expect(wrapper.find('[data-refund="confirm"]').exists()).toBe(false)
  await wrapper.get('[data-refund="save"]').trigger('click'); await flushPromises()
  expect(mutate.mock.calls[0][1]).toMatchObject({ kind: 'edit', body: { revision: 1, reason: '客户修改原因' } })
  expect(wrapper.text()).toContain('客户修改原因')
})

it('keeps the exact request after a lost confirmation response and remount', async () => {
  const mutate = vi.spyOn(refundApi, 'mutate').mockRejectedValueOnce(new Error('lost response'))
  wrapper = mount(SupportRefundCard, { props: props() }); await flushPromises()
  await wrapper.get('[data-refund="confirm"]').trigger('click'); await flushPromises()
  const sent = JSON.parse(JSON.stringify(mutate.mock.calls[0][1]))
  wrapper.unmount(); wrapper = mount(SupportRefundCard, { props: props() }); await flushPromises()
  expect(wrapper.text()).toContain('提交结果尚未确认')
  expect(mutate).toHaveBeenCalledTimes(1)
  mutate.mockResolvedValueOnce({ ...current(), application: application() })
  await wrapper.get('[data-refund="retry"]').trigger('click'); await flushPromises()
  expect(mutate.mock.calls[1][1]).toEqual(sent)
})

it('distinguishes unknown results and supports a fresh application after cancellation', async () => {
  vi.mocked(refundApi.read).mockResolvedValue({ ...current(), application: application('RECONCILING') })
  wrapper = mount(SupportRefundCard, { props: props() }); await flushPromises()
  expect(wrapper.text()).toContain('退款结果待确认')
  expect(wrapper.text()).not.toContain('退款完成')
  expect(wrapper.find('[data-refund="confirm"]').exists()).toBe(false)
  wrapper.unmount()
  vi.mocked(refundApi.read).mockResolvedValue({ ...current(), draft: null, application: application('CANCELLED') })
  wrapper = mount(SupportRefundCard, { props: props() }); await flushPromises()
  expect(wrapper.find('[data-refund="start"]').exists()).toBe(true)
})

it('never lets an old conversation read populate a new product card', async () => {
  let release!: (v: RefundView) => void
  vi.mocked(refundApi.read).mockImplementationOnce(() => new Promise(r => { release = r }))
  wrapper = mount(SupportRefundCard, { props: props() }); await flushPromises()
  wrapper.unmount()
  const next = props(); next.conversation.conversation_id = 'other-conversation'
  vi.mocked(refundApi.read).mockResolvedValue({ draft: null, application: null })
  wrapper = mount(SupportRefundCard, { props: next }); await flushPromises()
  release({ ...current(), application: application() }); await flushPromises()
  expect(wrapper.text()).not.toContain('one-case')
})

it('keeps cancelled reasons available and rejects stale confirmation in the UI', async () => {
  const view = current()
  const mutate = vi.spyOn(refundApi, 'mutate').mockResolvedValue({ ...view, draft: { ...view.draft!, status: 'CANCELLED', revision: 2 } })
  wrapper = mount(SupportRefundCard, { props: props() }); await flushPromises()
  await wrapper.get('.refund-summary footer button').trigger('click'); await flushPromises()
  expect(mutate.mock.calls[0][1].kind).toBe('cancel')
  await wrapper.get('[data-refund="start"]').trigger('click')
  expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe(view.draft!.reason)
  wrapper.unmount()
  const next = props(); next.conversation.version = 9
  wrapper = mount(SupportRefundCard, { props: next }); await flushPromises()
  expect(wrapper.text()).toContain('请重新核对')
  expect(wrapper.find('[data-refund="confirm"]').exists()).toBe(false)
})

it('prepares only the accepted current assistant summary and never auto-confirms it', async () => {
  vi.mocked(refundApi.read).mockResolvedValue({ draft: null, application: null })
  const mutate = vi.spyOn(refundApi, 'mutate').mockResolvedValue(current())
  const input = props()
  input.conversation.messages = [{ message_id: 'accepted-offer', sequence: 1, author: 'ASSISTANT', recipient: 'CUSTOMER', text: '请核对摘要', ticket_id: null, created_at: '', assistant: { run_id: 'run', mode: 'mock', citations: [], handoff_summary: null, refund_summary: '客户反馈未收到商品，请核实后处理退款。' } }]
  wrapper = mount(SupportRefundCard, { props: input }); await flushPromises()
  expect(mutate).toHaveBeenCalledTimes(1)
  expect(mutate.mock.calls[0][1]).toMatchObject({ kind: 'prepare', body: { reason: '客户反馈未收到商品，请核实后处理退款。', expected_version: 1 } })
  expect(wrapper.find('[data-refund="confirm"]').exists()).toBe(true)
  wrapper.unmount()
  input.conversation.version = 2
  wrapper = mount(SupportRefundCard, { props: input }); await flushPromises()
  expect(mutate).toHaveBeenCalledTimes(1)
})
