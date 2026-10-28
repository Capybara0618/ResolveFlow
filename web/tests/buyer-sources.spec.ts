import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import BuyerSources from '../src/ui/BuyerSources.vue'
import type { SupportCitation } from '../src/support-client'

const source = (type: SupportCitation['source_type'], data: Record<string, unknown> = {}): SupportCitation => ({
  source_id: 'O-internal', source_type: type, content_hash: 'hash-internal', version: 'v-internal', data,
})
it('offers one closed buyer explanation without internal IDs, versions or guide dumps', () => {
  const wrapper = mount(BuyerSources, { props: { citations: [source('SHIPMENT', { status: 'DELIVERED' }), source('KNOWLEDGE', { text: 'INTERNAL-GUIDE' })] } })
  expect(wrapper.get<HTMLDetailsElement>('details').element.open).toBe(false)
  expect(wrapper.get('summary').text()).toBe('查看依据')
  expect(wrapper.text()).toContain('记录显示已签收')
  expect(wrapper.text()).not.toMatch(/internal|INTERNAL-GUIDE|DELIVERED/)
})
it('keeps policy conditions available in full and unknown logistics honest', () => {
  const wrapper = mount(BuyerSources, { props: { citations: [source('POLICY', { text: '符合条件后仍需商家核实。' }), source('SHIPMENT', { status: 'PENDING_CHECK' })] } })
  expect(wrapper.text()).toContain('符合条件后仍需商家核实。')
  expect(wrapper.text()).toContain('暂未确认')
  expect(wrapper.text()).not.toContain('PENDING_CHECK')
})
it('renders no empty explanation for a guide-only answer', () => {
  expect(mount(BuyerSources, { props: { citations: [source('KNOWLEDGE')] } }).find('details').exists()).toBe(false)
})
