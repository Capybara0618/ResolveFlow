import { afterEach, describe, expect, it, vi } from 'vitest'
import { consumeCaseEvents, parseEventFrames } from '../src/events'

afterEach(() => vi.unstubAllGlobals())

describe('authenticated case event stream', () => {
  it('parses events across chunks and ignores heartbeat comments', () => {
    const parser = parseEventFrames()
    expect(parser.push(': keep-alive\n\nid: ev-1\nevent: CASE_')).toEqual([])
    expect(parser.push('CREATED\ndata: {"summary":"opened"}\n\n')).toEqual([
      { id: 'ev-1', event: 'CASE_CREATED', data: '{"summary":"opened"}' },
    ])
  })

  it('uses Authorization and Last-Event-ID headers on reconnect, never URL credentials', async () => {
    const frames = new TextEncoder().encode('id: ev-2\nevent: CASE_UPDATED\ndata: {"summary":"done"}\n\n')
    const fetcher = vi.fn().mockResolvedValue(new Response(new ReadableStream({
      start(controller) { controller.enqueue(frames); controller.close() },
    }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } }))
    vi.stubGlobal('fetch', fetcher)
    const seen: string[] = []
    await consumeCaseEvents('case-1', 'test-token', 'ev-1', (frame) => seen.push(frame.id))
    expect(seen).toEqual(['ev-2'])
    const [url, options] = fetcher.mock.calls[0]
    expect(url).toBe('/api/v1/cases/case-1/events')
    expect(options.headers.Authorization).toBe('Bearer test-token')
    expect(options.headers['Last-Event-ID']).toBe('ev-1')
  })
})
