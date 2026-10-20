import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import SupportWorkspace from '../src/ui/SupportWorkspace.vue'
import { supportApi, type SupportConversation } from '../src/support-client'
import { coreApi, ApiError } from '../src/client'
import fixture from '../../contracts/core/fixtures/support.json'
import assistantFixture from '../../contracts/core/fixtures/support-assistant.json'

const buyer = { access_token: 'buyer-token', role: 'CUSTOMER' as const, buyer_id: 'B-1', expires_in: 3600 }
let wrapper: VueWrapper
const original = (): SupportConversation => ({ ...structuredClone(fixture.Conversation), ticket: null } as SupportConversation)
beforeEach(() => {
  sessionStorage.clear()
  vi.spyOn(coreApi, 'orders').mockResolvedValue({ items: [], page: { limit: 20 } })
  vi.spyOn(supportApi, 'conversations').mockResolvedValue({ items: [original()], next_before: null })
  vi.spyOn(supportApi, 'read').mockResolvedValue(original())
})
afterEach(() => { wrapper?.unmount(); vi.restoreAllMocks(); sessionStorage.clear() })

it('renders assistant sources and shares its editable summary only after explicit confirmation', async () => {
  const conversation = { ...structuredClone(assistantFixture.Conversation), ticket: null } as SupportConversation
  vi.mocked(supportApi.read).mockResolvedValue(conversation)
  const mutate = vi.spyOn(supportApi, 'mutate').mockResolvedValue(conversation)
  await open()
  expect(wrapper.text()).toContain('售后助手')
  expect(wrapper.text()).toContain('脚本模型演示')
  expect(wrapper.get('.support-message.assistant').text()).toContain('物流事实')
  await wrapper.get('[data-action="handoff"]').trigger('click')
  expect((wrapper.get('[aria-label="核查摘要"]').element as HTMLTextAreaElement).value).toBe(conversation.messages[1].assistant!.handoff_summary)
  expect(mutate).not.toHaveBeenCalled()
  expect((wrapper.get('[data-share-report]').element as HTMLInputElement).checked).toBe(false)
  await wrapper.get('[data-share-report]').setValue(true)
  await wrapper.get('[aria-label="核查摘要"]').setValue('我确认：只核查')
  await wrapper.get('[data-action="confirm-handoff"]').trigger('click'); await flushPromises()
  expect(mutate.mock.calls[0][1]).toMatchObject({ kind: 'handoff', body: { summary: '我确认：只核查', assistant_message_id: conversation.messages[1].message_id, shared_message_ids: [] } })
})

it('keeps corrections and human handoff available while the assistant is running', async () => {
  const conversation = { ...original(), assistant_turn: { run_id: 'running', status: 'RUNNING' as const, reason: null } }
  vi.mocked(supportApi.read).mockResolvedValue(conversation)
  const mutate = vi.spyOn(supportApi, 'mutate').mockResolvedValue(conversation)
  await open()
  expect(wrapper.text()).toContain('助手正在查阅资料')
  expect(wrapper.get('[data-action="handoff"]').attributes('disabled')).toBeUndefined()
  await wrapper.get('[aria-label="咨询消息"]').setValue('更正，已经找到了')
  await wrapper.get('[data-action="send"]').trigger('click'); await flushPromises()
  expect(mutate.mock.calls[0][1]).toMatchObject({ body: { recipient: 'ASSISTANT', text: '更正，已经找到了' } })
})

it('shows a confirmed report in the merchant workbench without private assistant messages', async () => {
  const ticket = { ...structuredClone(assistantFixture.TicketDetail), messages: [] } as SupportConversation
  vi.spyOn(supportApi, 'tickets').mockResolvedValue({ items: [ticket], next_before: null })
  vi.mocked(supportApi.read).mockResolvedValue(ticket)
  wrapper = mount(SupportWorkspace, { props: { account: { access_token: 'merchant-token', role: 'MERCHANT_ADMIN', merchant_id: 'M-1001', expires_in: 3600 } } })
  await flushPromises(); await wrapper.get('[data-conversation]').trigger('click'); await flushPromises()
  expect(wrapper.text()).toContain('客户确认共享的调查依据')
  expect(wrapper.text()).toContain('物流事实')
  expect(wrapper.find('.support-message.assistant').exists()).toBe(false)
})
async function open() {
  wrapper = mount(SupportWorkspace, { props: { account: buyer } }); await flushPromises()
  await wrapper.get('[data-conversation]').trigger('click'); await flushPromises()
}
it('requires preview confirmation and passes selected original ids instead of text copies', async () => {
  const mutate = vi.spyOn(supportApi, 'mutate').mockResolvedValue(fixture.Conversation as SupportConversation)
  await open(); await wrapper.get('[data-action="handoff"]').trigger('click'); await flushPromises()
  expect(mutate).not.toHaveBeenCalled()
  await wrapper.get('[aria-label="核查摘要"]').setValue('只核查，不退款')
  await wrapper.get('input[type="checkbox"]').setValue(true)
  await wrapper.get('[data-action="confirm-handoff"]').trigger('click'); await flushPromises()
  expect(mutate.mock.calls[0][1]).toMatchObject({ kind: 'handoff', body: { summary: '只核查，不退款', expected_version: 3, shared_message_ids: [fixture.Conversation.messages[0].message_id] } })
  expect(wrapper.text()).toContain('补充给商家')
})
it('retries an uncertain write with the original request even after draft changes', async () => {
  const mutate = vi.spyOn(supportApi, 'mutate').mockRejectedValueOnce(new TypeError('lost')).mockResolvedValueOnce(original())
  await open(); await wrapper.get('[aria-label="咨询消息"]').setValue('原消息')
  await wrapper.get('[data-action="send"]').trigger('click'); await flushPromises()
  await wrapper.get('[data-action="retry"]').trigger('click'); await flushPromises()
  expect(mutate.mock.calls[0]).toEqual(mutate.mock.calls[1])
})
it('does not send an old draft after a version conflict and keeps the text for review', async () => {
  const mutate = vi.spyOn(supportApi, 'mutate').mockRejectedValue(new ApiError(409, 'STATE_CONFLICT', '请刷新后重新确认'))
  await open(); await wrapper.get('[aria-label="咨询消息"]').setValue('保留我的问题')
  await wrapper.get('[data-action="send"]').trigger('click'); await flushPromises()
  expect(wrapper.text()).toContain('请刷新后重新确认')
  expect(wrapper.find('[data-action="retry"]').exists()).toBe(false)
  expect((wrapper.get('[aria-label="咨询消息"]').element as HTMLTextAreaElement).value).toBe('保留我的问题')
  expect(mutate).toHaveBeenCalledTimes(1)
})
it('shows only the shared merchant projection and submits a merchant-authored question', async () => {
  const ticket = { ...structuredClone(fixture.TicketDetail), messages: [] } as SupportConversation
  vi.spyOn(supportApi, 'tickets').mockResolvedValue({ items: [ticket], next_before: null })
  vi.mocked(supportApi.read).mockResolvedValue(ticket)
  const mutate = vi.spyOn(supportApi, 'mutate').mockResolvedValue(ticket)
  wrapper = mount(SupportWorkspace, { props: { account: { access_token: 'merchant-token', role: 'MERCHANT_ADMIN', merchant_id: 'M-1001', expires_in: 3600 } } })
  await flushPromises(); await wrapper.get('[data-conversation]').trigger('click'); await flushPromises()
  expect(supportApi.read).toHaveBeenCalledWith('merchant-token', ticket.ticket!.ticket_id, true)
  expect(wrapper.text()).toContain('客户共享原文')
  expect(wrapper.find('[data-action="handoff"]').exists()).toBe(false)
  await wrapper.get('select').setValue('REQUEST_INFO'); await wrapper.get('[aria-label="咨询消息"]').setValue('请补充是否授权代收')
  await wrapper.get('[data-action="send"]').trigger('click'); await flushPromises()
  expect(mutate.mock.calls[0][1]).toMatchObject({ kind: 'reply', id: ticket.ticket!.ticket_id, body: { kind: 'REQUEST_INFO', text: '请补充是否授权代收' } })
})
it('ignores a late A conversation response after the buyer chooses B', async () => {
  const a = original(), b = { ...original(), conversation_id: 'B-id', merchant_id: 'M-1002', store_name: 'B店', product: { ...original().product, name: 'B商品' } }
  vi.mocked(supportApi.conversations).mockResolvedValue({ items: [a, b], next_before: null })
  let completeA!: (value: SupportConversation) => void
  vi.mocked(supportApi.read).mockImplementation((_token, id) => id === a.conversation_id ? new Promise(resolve => { completeA = resolve }) : Promise.resolve(b))
  wrapper = mount(SupportWorkspace, { props: { account: buyer } }); await flushPromises()
  await wrapper.findAll('[data-conversation]')[0].trigger('click')
  await wrapper.findAll('[data-conversation]')[1].trigger('click'); await flushPromises()
  completeA(a); await flushPromises()
  expect(wrapper.get('.support-product').text()).toContain('B商品')
  expect(wrapper.get('.support-product').text()).not.toContain('合成商品')
})
