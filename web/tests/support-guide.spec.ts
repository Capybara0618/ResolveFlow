import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import SupportSources from '../src/ui/SupportSources.vue'
import SupportContext from '../src/ui/SupportContext.vue'
import type { SupportConversation } from '../src/support-client'
import fixture from '../../contracts/core/fixtures/support-assistant.json'

it('renders application instructions as a versioned guide rather than store policy or order facts', () => {
  const c = structuredClone(fixture.Conversation) as SupportConversation
  const source = c.messages.flatMap(m => m.assistant?.citations ?? []).find(s => s.source_type === 'KNOWLEDGE')!
  const wrapper = mount(SupportSources, { props: { citations: [source] } })
  expect(wrapper.text()).toContain('使用指南')
  expect(wrapper.text()).toContain('2026.10.21-v1')
  expect(wrapper.text()).toContain('请商家核查不需要先申请退款')
  expect(wrapper.text()).not.toContain('店铺政策')
  expect(wrapper.text()).not.toContain('订单状态')
})

it('shows the buyer cited guide and the merchant confirmed guide with the same source text', () => {
  const c = structuredClone(fixture.Conversation) as SupportConversation
  for (const merchant of [false, true]) {
    const wrapper = mount(SupportContext, { props: { conversation: c, merchant } })
    expect(wrapper.text()).toContain('使用指南')
    expect(wrapper.text()).toContain('请商家核查不需要先申请退款')
  }
})
