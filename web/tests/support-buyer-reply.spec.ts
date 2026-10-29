import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import SupportBuyerReply from '../src/ui/SupportBuyerReply.vue'
import type { SupportMessage } from '../src/support-client'
import { buyerParts } from '../src/support-view'

function message(): SupportMessage {
  return { message_id: 'one', sequence: 2, author: 'ASSISTANT', recipient: 'CUSTOMER', ticket_id: null, created_at: '', text: '商家还需要核实情况。\n\n你可以选择要共享的原文。', assistant: {
    run_id: 'run', mode: 'mock', citations: [], handoff_summary: null,
    buyer_view: { version: 'buyer-view-v1', parts: [{ task_id: 'trace', text: '商家还需要核实情况。', guidance: '你可以选择要共享的原文。' }] },
  } }
}

it('keeps requested guidance distinct without inventing action controls or repeating the body', () => {
  const input = message(), wrapper = mount(SupportBuyerReply, { props: { message: input } })
  expect(wrapper.findAll('p').map(p => p.text())).toEqual(['商家还需要核实情况。', '你可以选择要共享的原文。'])
  expect(wrapper.get('.support-reply-guidance').text()).toBe('你可以选择要共享的原文。')
  expect(wrapper.find('button').exists()).toBe(false)
  wrapper.unmount()
})

it('cannot hide history text behind a replacement presentation and never parses HTML', () => {
  const input = message()
  input.text = '原始答复 <img src=x onerror="alert(1)">，需要核实后才能处理。'
  expect(buyerParts(input)).toBeNull()
  const wrapper = mount(SupportBuyerReply, { props: { message: input } })
  expect(wrapper.text()).toBe(input.text)
  expect(wrapper.find('img').exists()).toBe(false)
  expect(wrapper.find('.support-reply-guidance').exists()).toBe(false)
  wrapper.unmount()
})

it('preserves legacy text and line breaks when a presentation is absent', () => {
  const input = message()
  delete input.assistant!.buyer_view
  const wrapper = mount(SupportBuyerReply, { props: { message: input } })
  expect(wrapper.findAll('p').map(p => p.element.textContent).join('\n\n')).toBe(input.text)
  expect(wrapper.find('.support-reply-part').exists()).toBe(false)
  wrapper.unmount()
})
