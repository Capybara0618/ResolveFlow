/** Authenticated SSE reader. Native EventSource cannot send the required bearer header. */

export interface EventFrame { id: string; event: string; data: string }

export function parseEventFrames() {
  let pending = ''
  return {
    push(chunk: string): EventFrame[] {
      pending += chunk
      const events: EventFrame[] = []
      while (true) {
        const normalized = pending.replace(/\r\n/g, '\n')
        const boundary = normalized.indexOf('\n\n')
        if (boundary < 0) break
        const block = normalized.slice(0, boundary)
        pending = normalized.slice(boundary + 2)
        const fields = block.split('\n').filter((line) => line && !line.startsWith(':'))
        const value = (key: string) => fields.find((line) => line.startsWith(`${key}:`))?.slice(key.length + 1).trimStart()
        const data = fields.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n')
        if (data) events.push({ id: value('id') ?? '', event: value('event') ?? 'message', data })
      }
      return events
    },
  }
}

export async function consumeEventStream(
  path: string, token: string, lastEventId: string | null,
  onEvent: (frame: EventFrame) => void, signal?: AbortSignal, onOpen?: () => void,
): Promise<string | null> {
  const headers: Record<string, string> = { Accept: 'text/event-stream', Authorization: `Bearer ${token}` }
  if (lastEventId) headers['Last-Event-ID'] = lastEventId
  const response = await fetch(path, { headers, signal })
  if (!response.ok || !response.body) throw new Error(`Event stream refused: HTTP ${response.status}`)
  onOpen?.()
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  const parser = parseEventFrames()
  let cursor = lastEventId
  try {
    while (!signal?.aborted) {
      const { value, done } = await reader.read()
      if (done) break
      for (const frame of parser.push(decoder.decode(value, { stream: true }))) {
        if (frame.id) cursor = frame.id
        onEvent(frame)
      }
    }
    for (const frame of parser.push(decoder.decode())) {
      if (frame.id) cursor = frame.id
      onEvent(frame)
    }
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
  return cursor
}

export function consumeCaseEvents(
  caseId: string, token: string, lastEventId: string | null,
  onEvent: (frame: EventFrame) => void, signal?: AbortSignal,
): Promise<string | null> {
  return consumeEventStream(`/api/v1/cases/${encodeURIComponent(caseId)}/events`, token, lastEventId, onEvent, signal)
}

export async function watchCaseEvents(
  caseId: string, token: string, onEvent: (frame: EventFrame) => void, signal: AbortSignal,
  initialEventId: string | null = null,
): Promise<void> {
  let cursor = initialEventId
  let delay = 500
  while (!signal.aborted) {
    try {
      cursor = await consumeCaseEvents(caseId, token, cursor, onEvent, signal)
      delay = 500
    } catch (error) {
      if (signal.aborted) return
      if (error instanceof Error && /HTTP (401|403|404)/.test(error.message)) throw error
    }
    if (!signal.aborted) await new Promise((resolve) => setTimeout(resolve, delay))
    delay = Math.min(delay * 2, 5000)
  }
}
