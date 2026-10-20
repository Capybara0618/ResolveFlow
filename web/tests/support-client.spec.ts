import { afterEach, expect, it, vi } from 'vitest'
import { supportApi, saveSupportPending, readSupportPending, clearSupportPending, type SupportPending } from '../src/support-client'
import fixture from '../../contracts/core/fixtures/support.json'

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear() })
it('keeps the original request and key across a reload and sends no authority fields', async () => {
  const pending: SupportPending = { kind: 'handoff', id: 'conversation-A', key: 'original', label: 'A商品', body: fixture.Handoff }
  saveSupportPending('buyer-A', pending)
  expect(readSupportPending('buyer-B')).toBeNull()
  const restored = readSupportPending('buyer-A')!
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(fixture.Conversation), { status: 200 }))
  vi.stubGlobal('fetch', fetch)
  await supportApi.mutate('user-token', restored)
  expect(fetch.mock.calls[0][0]).toBe('/api/v1/support/conversations/conversation-A/tickets')
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual(fixture.Handoff)
  const headers = new Headers(fetch.mock.calls[0][1].headers)
  expect(headers.get('Authorization')).toBe('Bearer user-token')
  expect(headers.get('Idempotency-Key')).toBe('original')
  clearSupportPending('buyer-A'); expect(readSupportPending('buyer-A')).toBeNull()
})
it('uses merchant ticket paths and an explicit history cursor', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(fixture.TicketDetail), { status: 200 }))
  vi.stubGlobal('fetch', fetch)
  await supportApi.read('token', 'ticket/1', true, 50)
  expect(fetch.mock.calls[0][0]).toBe('/api/v1/support/tickets/ticket%2F1?before_sequence=50')
})
