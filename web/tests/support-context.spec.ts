import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import SupportContext from '../src/ui/SupportContext.vue'
import { reportFor, shipmentEvents } from '../src/support-view'
import type { SupportConversation } from '../src/support-client'
import fixture from '../../contracts/core/fixtures/support-assistant.json'

it('uses only the confirmed merchant report, even if a private newer reply exists', () => {
  const c = structuredClone(fixture.Conversation) as SupportConversation
  c.messages[1].assistant!.handoff_summary = 'private-newer-suggestion'
  c.messages[1].assistant!.citations[0].data = { status: 'PRIVATE_NEWER_FACT' }
  const wrapper = mount(SupportContext, { props: { conversation: c, merchant: true } })
  expect(wrapper.text()).toContain('客户已确认共享')
  expect(wrapper.text()).toContain('记录显示已签收')
  expect(wrapper.text()).not.toContain('PRIVATE_NEWER_FACT')
  expect(wrapper.text()).not.toContain('private-newer-suggestion')
  expect(reportFor(c, true)).toEqual(c.ticket!.report)
})
it('does not invent logistics, originals or an investigation when none were shared', () => {
  const c = structuredClone(fixture.TicketDetail) as SupportConversation
  c.ticket!.shared_messages = []; delete c.ticket!.report
  const wrapper = mount(SupportContext, { props: { conversation: c, merchant: true } })
  expect(wrapper.text()).toContain('客户未共享原文')
  expect(wrapper.text()).toContain('本次未共享助手调查依据')
  expect(wrapper.text()).not.toContain('已签收')
})
it('keeps recorded event order and explicit unknown status instead of fabricating a delivery', () => {
  expect(shipmentEvents({ source_id: 'O1', source_type: 'SHIPMENT', content_hash: 'hash', version: 3, data: { lines: [{ events: [{ code: 'IN_TRANSIT', occurred_at: '2026-10-20T10:00:00Z' }, { code: 'UNKNOWN', occurred_at: '2026-10-20T11:00:00Z' }] }] } }).map(e => e.code)).toEqual(['UNKNOWN', 'IN_TRANSIT'])
})
