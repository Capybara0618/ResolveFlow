import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import SupportWorkspace from '../src/ui/SupportWorkspace.vue'
import { supportApi, type SupportConversation } from '../src/support-client'
import { coreApi, ApiError } from '../src/client'
import fixture from '../../contracts/core/fixtures/support.json'
import assistantFixture from '../../contracts/core/fixtures/support-assistant.json'
import * as streamEvents from '../src/support-events'
import type { SupportStreamEvent } from '../src/support-events'
import { refundApi } from '../src/support-refund'
import type { RefundView } from '../src/support-refund'
import refundFixture from '../../contracts/core/fixtures/support-refund.json'

const buyer = { access_token: 'buyer-token', role: 'CUSTOMER' as const, buyer_id: 'B-1', expires_in: 3600 }
let wrapper: VueWrapper
const original = (): SupportConversation => ({ ...structuredClone(fixture.Conversation), ticket: null } as SupportConversation)
beforeEach(() => {
  sessionStorage.clear()
  vi.spyOn(refundApi, 'read').mockResolvedValue({ draft: null, application: null })
  vi.spyOn(streamEvents, 'watchSupportEvents').mockImplementation(async (_id, _token, _event, signal, connected) => {
    connected?.(true)
    await new Promise<void>(resolve => signal.addEventListener('abort', () => resolve(), { once: true }))
  })
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
  expect(wrapper.get('.support-message.assistant').text()).toContain('物流记录')
  expect(wrapper.get<HTMLDetailsElement>('.support-message.assistant .buyer-evidence').element.open).toBe(false)
  await wrapper.get('[data-action="handoff"]').trigger('click')
  expect((wrapper.get('[aria-label="核查摘要"]').element as HTMLTextAreaElement).value).toBe(conversation.messages[1].assistant!.handoff_summary)
  expect(mutate).not.toHaveBeenCalled()
  expect((wrapper.get('[data-share-report]').element as HTMLInputElement).checked).toBe(false)
  await wrapper.get('[data-share-report]').setValue(true)
  await wrapper.get('[aria-label="核查摘要"]').setValue('我确认：只核查')
  await wrapper.get('[data-action="confirm-handoff"]').trigger('click'); await flushPromises()
  expect(mutate.mock.calls[0][1]).toMatchObject({ kind: 'handoff', body: { summary: '我确认：只核查', assistant_message_id: conversation.messages[1].message_id, shared_message_ids: [] } })
})

it('renders a buyer-requested guide separately without creating an action or sharing messages', async () => {
  const conversation = original()
  conversation.messages = [{ message_id: 'guide', sequence: conversation.version, author: 'ASSISTANT', recipient: 'CUSTOMER', ticket_id: null, created_at: '', text: '可以请商家核查。\n\n先核对共享的原文。', assistant: {
    run_id: 'guide-run', mode: 'mock', citations: [], handoff_summary: null,
    buyer_view: { version: 'buyer-view-v1', parts: [{ task_id: 'how', text: '可以请商家核查。', guidance: '先核对共享的原文。' }] },
  } }]
  vi.mocked(supportApi.read).mockResolvedValue(conversation)
  const mutate = vi.spyOn(supportApi, 'mutate').mockResolvedValue(conversation)
  await open()
  expect(wrapper.get('.support-reply-part > p').text()).toBe('可以请商家核查。')
  expect(wrapper.get('.support-reply-guidance').text()).toBe('先核对共享的原文。')
  expect(wrapper.find('.support-handoff-card').exists()).toBe(false)
  expect(mutate).not.toHaveBeenCalled()
})

it.each([true, false])('reveals a delayed refund summary while respecting whether the buyer is at the bottom: %s', async atBottom => {
  let release!: (value: RefundView) => void
  vi.mocked(refundApi.read).mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
  wrapper = mount(SupportWorkspace, { props: { account: buyer } }); await flushPromises()
  const pane = wrapper.get<HTMLElement>('.support-messages')
  Object.defineProperties(pane.element, { scrollHeight: { value: 1600, configurable: true }, clientHeight: { value: 500, configurable: true } })
  pane.element.scrollTop = atBottom ? 1100 : 30
  await pane.trigger('scroll')
  release({ draft: { ...structuredClone(refundFixture.Draft), expected_version: original().version, expires_at: new Date(Date.now() + 1800000).toISOString(), status: 'DRAFT' }, application: null })
  await flushPromises()
  expect(wrapper.get('[data-refund="confirm"]').attributes('disabled')).toBeUndefined()
  if (atBottom) expect(pane.element.scrollTop).toBe(1600)
  else {
    expect(pane.element.scrollTop).toBe(30)
    await wrapper.get('[data-action="latest-messages"]').trigger('click')
    expect(pane.element.scrollTop).toBe(1600)
  }
})

it.each([true, false])('respects the reading position after webfonts finish loading: %s', async atBottom => {
  const previousFonts = Object.getOwnPropertyDescriptor(document, 'fonts')
  const fonts = new EventTarget()
  Object.defineProperty(document, 'fonts', { configurable: true, value: fonts })
  try {
    await open()
    const pane = wrapper.get<HTMLElement>('.support-messages')
    Object.defineProperties(pane.element, { scrollHeight: { value: 1000, configurable: true }, clientHeight: { value: 500, configurable: true } })
    pane.element.scrollTop = atBottom ? 500 : 30
    await pane.trigger('scroll')
    Object.defineProperty(pane.element, 'scrollHeight', { value: 1200, configurable: true })
    fonts.dispatchEvent(new Event('loadingdone'))
    await flushPromises()
    expect(pane.element.scrollTop).toBe(atBottom ? 1200 : 30)
  } finally {
    wrapper?.unmount()
    if (previousFonts) Object.defineProperty(document, 'fonts', previousFonts)
    else Reflect.deleteProperty(document, 'fonts')
  }
})

it('keeps corrections and human handoff available while the assistant is running', async () => {
  const conversation = { ...original(), assistant_turn: { run_id: 'running', status: 'RUNNING' as const, reason: null } }
  vi.mocked(supportApi.read).mockResolvedValue(conversation)
  const mutate = vi.spyOn(supportApi, 'mutate').mockResolvedValue(conversation)
  await open()
  expect(wrapper.get('[data-buyer-waiting]').text()).toContain('正在帮你查看，请稍候')
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
  expect(wrapper.text()).toContain('客户已确认共享')
  expect(wrapper.text()).toContain('物流事实')
  expect(wrapper.find('.support-message.assistant').exists()).toBe(false)
  expect(streamEvents.watchSupportEvents).not.toHaveBeenCalled()
  expect(refundApi.read).not.toHaveBeenCalled()
})
async function open() {
  wrapper = mount(SupportWorkspace, { props: { account: buyer } }); await flushPromises()
  await wrapper.get('[data-conversation]').trigger('click'); await flushPromises()
}

it('restores the selected conversation after remount using reads only', async () => {
  const second = { ...original(), conversation_id: 'second-conversation', line_id: 'second-line' }
  vi.mocked(supportApi.conversations).mockResolvedValue({ items: [original(), second], next_before: null })
  vi.mocked(supportApi.read).mockImplementation(async (_token, id) => id === second.conversation_id ? second : original())
  const mutate = vi.spyOn(supportApi, 'mutate')
  await open()
  await wrapper.findAll('[data-conversation]')[1]!.trigger('click'); await flushPromises()
  wrapper.unmount()
  wrapper = mount(SupportWorkspace, { props: { account: buyer } }); await flushPromises()
  expect(wrapper.get('[aria-current="true"]').attributes('data-line-id')).toBe('second-line')
  expect(mutate).not.toHaveBeenCalled()
})

function completed(c: SupportConversation): SupportStreamEvent {
  return { event_id: '3', conversation_id: c.conversation_id, run_id: c.assistant_turn!.run_id,
    input_version: c.version, attempt_id: null, kind: 'answer.committed', created_at: '2026-10-23T04:00:00Z',
    payload: { message_id: 'stream-message', sequence: c.version + 1, text: '已收到实时发布的回答。',
      assistant: { run_id: c.assistant_turn!.run_id, mode: 'mock', citations: [], handoff_summary: null } } }
}

it.each([
  ['ORDER', '正在核对订单'], ['SHIPMENT', '正在查看物流'], ['POLICY', '正在查阅售后政策'],
  ['FUTURE_INTERNAL_TOOL', '正在帮你查看'],
])('shows buyer-facing activity for %s without exposing tool names or invented completion', async (category, label) => {
  const c: SupportConversation = { ...original(), assistant_turn: { run_id: 'stream-run', status: 'RUNNING', reason: null } }
  vi.mocked(supportApi.read).mockResolvedValue(c)
  await open()
  const deliver = vi.mocked(streamEvents.watchSupportEvents).mock.calls.at(-1)![2]
  deliver({ ...completed(c), kind: 'activity.started', payload: { category } }); await flushPromises()
  expect(wrapper.get('[data-buyer-waiting]').text()).toContain(label)
  expect(wrapper.get('[data-buyer-waiting]').text()).not.toContain(category)
  expect(wrapper.find('[role="progressbar"]').exists()).toBe(false)
  deliver({ ...completed(c), kind: 'answer.failed', payload: {} }); await flushPromises()
  expect(wrapper.find('[data-buyer-waiting]').exists()).toBe(false)
  expect(wrapper.text()).toContain('可重新提问或请商家核查')
})

it('shows one provisional bubble, clears rejected text and replaces it with the committed answer', async () => {
  const c: SupportConversation = { ...original(), assistant_turn: { run_id: 'stream-run', status: 'RUNNING', reason: null } }
  vi.mocked(supportApi.read).mockResolvedValue(c)
  await open()
  const deliver = vi.mocked(streamEvents.watchSupportEvents).mock.calls.at(-1)![2]
  const event = (kind: SupportStreamEvent['kind'], payload: Record<string, unknown>, attempt: string | null = 'model-3') =>
    deliver({ ...completed(c), kind, payload, attempt_id: attempt })
  event('activity.started', { category: 'SHIPMENT' }, null); await flushPromises()
  expect(wrapper.text()).toContain('正在查看物流')
  event('activity.completed', { category: 'SHIPMENT' }, null)
  event('answer.started', {})
  event('answer.delta', { part_id: 'part-0', offset: 0, text: '第一段生成文字' }); await flushPromises()
  expect(wrapper.get('[data-generation]').text()).toContain('第一段生成文字')
  expect(wrapper.findAll('.support-message.assistant')).toHaveLength(1)
  expect(wrapper.find('[data-action="preview-handoff"]').exists()).toBe(false)
  event('answer.reset', {}, 'model-4'); await flushPromises()
  expect(wrapper.text()).not.toContain('第一段生成文字')
  expect(wrapper.find('[data-generation]').exists()).toBe(false)
  expect(wrapper.get('[data-buyer-waiting]').text()).toContain('正在完善回答')
  event('answer.started', {}, 'model-4')
  event('answer.delta', { part_id: 'part-0', offset: 0, text: '修复后的生成文字' }, 'model-4')
  deliver(completed(c)); await flushPromises()
  expect(wrapper.find('[data-generation]').exists()).toBe(false)
  expect(wrapper.findAll('.support-message.assistant')).toHaveLength(1)
  expect(wrapper.text()).toContain('已收到实时发布的回答。')
  expect(wrapper.text()).not.toContain('修复后的生成文字')
})

it('receives a committed answer without an extra read or resubmitting the question', async () => {
  const c: SupportConversation = { ...original(), assistant_turn: { run_id: 'active-run', status: 'RUNNING', reason: null } }
  vi.mocked(supportApi.read).mockResolvedValue(c)
  const mutate = vi.spyOn(supportApi, 'mutate')
  await open()
  const call = vi.mocked(streamEvents.watchSupportEvents).mock.calls.at(-1)!
  const before = vi.mocked(supportApi.read).mock.calls.length
  call[2](completed(c)); await flushPromises()
  expect(wrapper.text()).toContain('已收到实时发布的回答。')
  expect(wrapper.text()).not.toContain('助手正在处理你的问题')
  expect(supportApi.read).toHaveBeenCalledTimes(before)
  expect(mutate).not.toHaveBeenCalled()
  wrapper.unmount()
  expect(call[3].aborted).toBe(true)
})

it('ignores a late event from a previous product after aborting its subscription', async () => {
  const a: SupportConversation = { ...original(), assistant_turn: { run_id: 'run-A', status: 'RUNNING', reason: null } }
  const b = { ...original(), conversation_id: 'product-B', product: { ...original().product, name: 'B商品' } }
  vi.mocked(supportApi.conversations).mockResolvedValue({ items: [a, b], next_before: null })
  vi.mocked(supportApi.read).mockImplementation(async (_token, id) => id === a.conversation_id ? a : b)
  await open()
  const previous = vi.mocked(streamEvents.watchSupportEvents).mock.calls.at(-1)!
  await wrapper.findAll('[data-conversation]').find(item => item.attributes('data-line-id') === b.line_id && item.text().includes('B商品'))!.trigger('click')
  await flushPromises()
  expect(previous[3].aborted).toBe(true)
  previous[2](completed(a)); await flushPromises()
  expect(wrapper.get('.support-product').text()).toContain('B商品')
  expect(wrapper.text()).not.toContain('已收到实时发布的回答。')
})

it('preserves the reading position for a new answer and offers a jump to latest', async () => {
  const c: SupportConversation = { ...original(), assistant_turn: { run_id: 'reading-run', status: 'RUNNING', reason: null } }
  vi.mocked(supportApi.read).mockResolvedValue(c)
  await open()
  const pane = wrapper.get('.support-messages').element as HTMLElement
  Object.defineProperties(pane, { scrollHeight: { value: 1000, configurable: true }, clientHeight: { value: 100, configurable: true } })
  pane.scrollTop = 200
  await wrapper.get('.support-messages').trigger('scroll')
  vi.mocked(streamEvents.watchSupportEvents).mock.calls.at(-1)![2](completed(c)); await flushPromises()
  expect(pane.scrollTop).toBe(200)
  await wrapper.get('[data-action="latest-messages"]').trigger('click')
  expect(pane.scrollTop).toBe(1000)
})

it('uses read-only fallback for an active disconnected turn and never retries a write', async () => {
  vi.useFakeTimers()
  try {
    const c: SupportConversation = { ...original(), assistant_turn: { run_id: 'offline-run', status: 'RUNNING', reason: null } }
    vi.mocked(supportApi.read).mockResolvedValue(c)
    const mutate = vi.spyOn(supportApi, 'mutate')
    await open()
    vi.mocked(streamEvents.watchSupportEvents).mock.calls.at(-1)![4]?.(false)
    const before = vi.mocked(supportApi.read).mock.calls.length
    await vi.advanceTimersByTimeAsync(2000)
    expect(supportApi.read).toHaveBeenCalledTimes(before + 1)
    expect(mutate).not.toHaveBeenCalled()
  } finally { vi.useRealTimers() }
})
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
  await wrapper.findAll('.support-recipient button').find(b => b.text() === '请求客户补充')!.trigger('click'); await wrapper.get('[aria-label="咨询消息"]').setValue('请补充是否授权代收')
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

it('opens the first real conversation automatically and keeps an order chooser separate from the draft', async () => {
  const openOrder = vi.spyOn(supportApi, 'open')
  wrapper = mount(SupportWorkspace, { props: { account: buyer } }); await flushPromises()
  expect(wrapper.get('.support-product').text()).toContain('合成商品')
  await wrapper.get('[aria-label="咨询消息"]').setValue('未发出的补充')
  await wrapper.findAll('button').find(b => b.text().includes('选择订单'))!.trigger('click')
  expect(wrapper.get('[role="dialog"]').attributes('aria-modal')).toBe('true')
  expect(openOrder).not.toHaveBeenCalled()
  await wrapper.get('[aria-label="关闭弹层"]').trigger('click')
  expect((wrapper.get('[aria-label="咨询消息"]').element as HTMLTextAreaElement).value).toBe('未发出的补充')
})

it('searches only loaded conversations and does not show another store as the current context', async () => {
  const a = original(), b = { ...original(), conversation_id: 'b-search', store_name: '拾光家居', product: { ...original().product, name: '桌面台灯' } }
  vi.mocked(supportApi.conversations).mockResolvedValue({ items: [a, b], next_before: 12 })
  await open()
  await wrapper.get('[aria-label="搜索已加载咨询"]').setValue('拾光')
  expect(wrapper.findAll('[data-conversation]')).toHaveLength(1)
  expect(wrapper.get('[data-conversation]').text()).toContain('桌面台灯')
  expect(wrapper.get('.support-product').text()).toContain('合成商品')
  expect(wrapper.text()).toContain('加载更多咨询')
})

it('uses real loaded status counts and filters the merchant queue', async () => {
  const first = structuredClone(fixture.TicketDetail) as SupportConversation
  const second = { ...structuredClone(first), conversation_id: 'waiting', ticket: { ...first.ticket!, ticket_id: 'waiting-ticket', status: 'WAITING_CUSTOMER' as const } }
  vi.spyOn(supportApi, 'tickets').mockResolvedValue({ items: [first, second], next_before: null })
  vi.mocked(supportApi.read).mockResolvedValue(first)
  wrapper = mount(SupportWorkspace, { props: { account: { access_token: 'merchant-token', role: 'MERCHANT_ADMIN', merchant_id: 'M-1001', expires_in: 3600 } } }); await flushPromises()
  const waiting = wrapper.findAll('.support-filters button').find(b => b.text().includes('待补充'))!
  expect(waiting.text()).toContain('1')
  await waiting.trigger('click')
  expect(wrapper.findAll('[data-conversation]')).toHaveLength(1)
  expect(wrapper.get('[data-conversation]').text()).toContain('待客户补充')
})

it('keeps the assistant recipient after a private follow-up on a transferred conversation', async () => {
  const c = structuredClone(fixture.Conversation) as SupportConversation
  vi.mocked(supportApi.read).mockResolvedValue(c)
  const mutate = vi.spyOn(supportApi, 'mutate').mockResolvedValue(c)
  await open()
  await wrapper.findAll('.support-recipient button').find(b => b.text() === '询问智能助手')!.trigger('click')
  for (const text of ['第一条私人追问', '第二条私人追问']) {
    await wrapper.get('[aria-label="咨询消息"]').setValue(text)
    await wrapper.get('[data-action="send"]').trigger('click'); await flushPromises()
  }
  expect(mutate.mock.calls.map(c => c[1].body)).toEqual([expect.objectContaining({ recipient: 'ASSISTANT' }), expect.objectContaining({ recipient: 'ASSISTANT' })])
})

it('does not send on Chinese composition confirmation, but sends once on the following Enter', async () => {
  const mutate = vi.spyOn(supportApi, 'mutate').mockResolvedValue(original())
  await open(); const input = wrapper.get('[aria-label="咨询消息"]')
  await input.setValue('签收情况需要核查')
  await input.trigger('keydown', { key: 'Enter', isComposing: true })
  expect(mutate).not.toHaveBeenCalled()
  await input.trigger('keydown', { key: 'Enter', isComposing: false }); await flushPromises()
  expect(mutate).toHaveBeenCalledTimes(1)
})

it('keeps an order read failure distinct from an empty purchase history and allows retry in the chooser', async () => {
  vi.mocked(coreApi.orders).mockRejectedValueOnce(new ApiError(503, 'UNAVAILABLE', '订单服务暂不可用')).mockRejectedValueOnce(new ApiError(503, 'UNAVAILABLE', '订单服务暂不可用')).mockResolvedValueOnce({ items: [], page: { limit: 20 } })
  wrapper = mount(SupportWorkspace, { props: { account: buyer } }); await flushPromises()
  expect(wrapper.text()).toContain('订单服务暂不可用')
  await wrapper.findAll('button').find(b => b.text().includes('选择订单'))!.trigger('click'); await flushPromises()
  expect(wrapper.get('[role="dialog"]').text()).toContain('订单读取失败')
  expect(wrapper.get('[role="dialog"]').text()).not.toContain('暂无已付款订单')
  await wrapper.get('[role="dialog"]').findAll('button').find(b => b.text() === '重试读取订单')!.trigger('click'); await flushPromises()
  expect(wrapper.get('[role="dialog"]').text()).toContain('暂无已付款订单')
})
