import { afterEach, expect, it, vi } from 'vitest'
import { applySupportEvent, watchSupportEvents, type SupportStreamEvent } from '../src/support-events'
import fixture from '../../contracts/core/fixtures/support-stream.json'
import type { SupportConversation } from '../src/support-client'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })
const original = () => structuredClone(fixture.snapshot.payload.conversation) as SupportConversation
const accepted = (): SupportStreamEvent => structuredClone(fixture.accepted) as SupportStreamEvent
const encoded = (event: SupportStreamEvent) => new TextEncoder().encode(`id: ${event.event_id}\nevent: ${event.kind}\ndata: ${JSON.stringify(event)}\n\n`)

it('applies current status and committed message once while rejecting old run/input/conversation', () => {
  const c = { ...original(), version: 2, assistant_turn: { run_id: accepted().run_id!, status: 'PENDING' as const, reason: null } }
  const running = { ...accepted(), kind: 'turn.started' as const }
  expect(applySupportEvent(c, running)?.assistant_turn?.status).toBe('RUNNING')
  const done: SupportStreamEvent = { ...accepted(), event_id: '3', kind: 'answer.committed', payload: {
    message_id: 'assistant-message', sequence: 3, text: '当前已审核回答', assistant: { run_id: c.assistant_turn.run_id, mode: 'mock', citations: [], handoff_summary: null },
  } }
  const committed = applySupportEvent(c, done)!
  expect(committed.messages.at(-1)?.text).toBe('当前已审核回答')
  expect(committed.version).toBe(3)
  expect(applySupportEvent(committed, done)).toBe(committed)
  expect(applySupportEvent(c, { ...running, conversation_id: 'other' })).toBe(c)
  expect(applySupportEvent(c, { ...running, run_id: 'old' })).toBe(c)
  expect(applySupportEvent(c, { ...running, input_version: 1 })).toBe(c)
  expect(applySupportEvent(c, { ...running, input_version: 4 })).toBeNull() // Fetch missing messages; never invent inputs.
})

it('restores snapshots, preserves loaded older history and refuses regressing versions', () => {
  const c = original()
  c.messages.unshift({ ...c.messages[0], message_id: 'older', sequence: 1 })
  const snapshot = fixture.snapshot as SupportStreamEvent
  const next = applySupportEvent(c, snapshot)!
  expect(next.messages.map(m => m.message_id)).toContain('older')
  expect(applySupportEvent({ ...c, version: 99 }, snapshot)?.version).toBe(99)
})

it('reconnects with the last delivered cursor after a broken stream and never posts messages', async () => {
  vi.useFakeTimers()
  const abort = new AbortController(), seen: string[] = []
  let reads = 0
  const first = new ReadableStream<Uint8Array>({ pull(controller) {
    if (reads++ === 0) controller.enqueue(encoded(accepted()))
    else controller.error(new Error('synthetic disconnect'))
  } })
  const next = { ...accepted(), event_id: '2', kind: 'turn.started' as const }
  const fetcher = vi.fn().mockResolvedValueOnce(new Response(first, { headers: { 'Content-Type': 'text/event-stream' } }))
    .mockResolvedValueOnce(new Response(new ReadableStream({ start(controller) {
      controller.enqueue(encoded(accepted())); controller.enqueue(encoded(next)); controller.close()
    } }), { headers: { 'Content-Type': 'text/event-stream' } }))
  vi.stubGlobal('fetch', fetcher)
  const task = watchSupportEvents(next.conversation_id, 'buyer-token', event => {
    seen.push(event.event_id); if (event.event_id === '2') abort.abort()
  }, abort.signal)
  await vi.advanceTimersByTimeAsync(500)
  await task
  expect(seen).toEqual(['1', '2'])
  expect(fetcher.mock.calls[1][1].headers['Last-Event-ID']).toBe('1')
  for (const [url, options] of fetcher.mock.calls) {
    expect(url).toBe(`/api/v1/support/conversations/${next.conversation_id}/events`)
    expect(options.headers.Authorization).toBe('Bearer buyer-token')
    expect(options.method).toBeUndefined()
  }
})

it('stops on authentication refusal instead of retrying or dispatching a model', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response('', { status: 401 }))
  vi.stubGlobal('fetch', fetcher)
  await expect(watchSupportEvents(accepted().conversation_id, 'old-token', () => {}, new AbortController().signal)).rejects.toThrow('401')
  expect(fetcher).toHaveBeenCalledTimes(1)
})

it('keeps streamed text provisional, handles code point offsets, resets and commits one final message', () => {
  let c: SupportConversation = { ...original(), version: 2,
    assistant_turn: { run_id: accepted().run_id!, status: 'RUNNING', reason: null } }
  const e = (kind: SupportStreamEvent['kind'], payload: Record<string, unknown>, attempt = 'model-3'): SupportStreamEvent =>
    ({ ...accepted(), kind, payload, attempt_id: attempt })
  c = applySupportEvent(c, e('answer.started', {}))!
  c = applySupportEvent(c, e('answer.delta', { part_id: 'part-0', offset: 0, text: '您好😀' }))!
  c = applySupportEvent(c, e('answer.delta', { part_id: 'part-0', offset: 3, text: '，核查中' }))!
  expect(c.generation?.parts['part-0']).toBe('您好😀，核查中')
  expect(c.messages).toHaveLength(1)
  c = applySupportEvent(c, e('answer.reset', {}, 'model-4'))!
  expect(c.generation?.parts).toEqual({})
  expect(applySupportEvent(c, e('answer.delta', { part_id: 'part-0', offset: 0, text: '旧片段' }))).toBe(c)
  c = applySupportEvent(c, e('answer.started', {}, 'model-4'))!
  c = applySupportEvent(c, e('answer.delta', { part_id: 'part-0', offset: 0, text: '修正正文' }, 'model-4'))!
  c = applySupportEvent(c, e('answer.committed', { message_id: 'final-id', sequence: 3, text: '最终审核正文',
    assistant: { run_id: accepted().run_id, mode: 'mock', citations: [], handoff_summary: null } }))!
  expect(c.generation).toBeUndefined()
  expect(c.messages).toHaveLength(2)
  expect(c.messages.at(-1)?.text).toBe('最终审核正文')
})

it('restores a current draft snapshot and clears it on failure or new input', () => {
  const c: SupportConversation = { ...original(), version: 2,
    assistant_turn: { run_id: accepted().run_id!, status: 'RUNNING', reason: null } }
  const snapshot: SupportStreamEvent = { ...accepted(), kind: 'stream.snapshot', payload: { conversation: c,
    generation: { run_id: accepted().run_id, input_version: 2, view: { attempt_id: 'model-3', parts: { 'part-0': '恢复文字' } } } } }
  const restored = applySupportEvent(c, snapshot)!
  expect(restored.generation?.parts['part-0']).toBe('恢复文字')
  expect(applySupportEvent(restored, { ...accepted(), kind: 'answer.failed' })?.generation).toBeUndefined()
  const next = { ...original(), version: 3 }
  expect(applySupportEvent(restored, { ...snapshot, payload: { conversation: next, generation: null } })?.generation).toBeUndefined()
})
