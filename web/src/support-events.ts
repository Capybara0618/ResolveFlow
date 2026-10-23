import { consumeEventStream } from './events'
import type { SupportAssistant, SupportConversation, SupportMessage } from './support-client'

const kinds = ['turn.accepted', 'turn.started', 'answer.committed', 'answer.failed', 'answer.stale', 'stream.snapshot',
  'answer.started', 'answer.delta', 'answer.reset', 'activity.started', 'activity.completed'] as const
export interface SupportStreamEvent {
  event_id: string; conversation_id: string; run_id: string | null; input_version: number; attempt_id: string | null
  kind: typeof kinds[number]; payload: Record<string, unknown>; created_at: string
}

const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)

/** Merge server history without discarding older messages the user has already loaded. */
export function mergeSupportConversation(current: SupportConversation, next: SupportConversation): SupportConversation {
  if (next.conversation_id !== current.conversation_id || next.version < current.version) return current
  const messages = new Map(current.messages.map(message => [message.message_id, message]))
  for (const message of next.messages) messages.set(message.message_id, message)
  return { ...next, generation: next.generation ?? (next.version === current.version && next.assistant_turn?.run_id === current.assistant_turn?.run_id && next.assistant_turn?.status === 'RUNNING' ? current.generation : undefined),
    messages: [...messages.values()].sort((a, b) => a.sequence - b.sequence),
    next_before_sequence: current.messages[0]?.sequence < (next.messages[0]?.sequence ?? Infinity) ? current.next_before_sequence : next.next_before_sequence }
}

/** null asks for a read-only refresh because another tab/input has advanced beyond our messages. */
export function applySupportEvent(current: SupportConversation, event: SupportStreamEvent): SupportConversation | null {
  if (event.conversation_id !== current.conversation_id) return current
  if (event.kind === 'stream.snapshot') {
    const next = event.payload.conversation
    if (!object(next) || !Array.isArray(next.messages) || !Number.isSafeInteger(next.version)) return current
    const merged = mergeSupportConversation(current, next as unknown as SupportConversation)
    if (next.version !== merged.version) return merged
    const raw = event.payload.generation
    if (!object(raw) || raw.run_id !== merged.assistant_turn?.run_id || raw.input_version !== merged.version
      || merged.assistant_turn?.status !== 'RUNNING' || !object(raw.view)) return { ...merged, generation: undefined }
    const view = raw.view
    if (!object(view.parts) && view.parts !== undefined) return merged
    const parts = (view.parts ?? {}) as Record<string, unknown>
    if (Object.entries(parts).some(([key, text]) => !/^part-[0-7]$/.test(key) || typeof text !== 'string')) return merged
    return { ...merged, generation: { run_id: raw.run_id as string, input_version: merged.version,
      attempt_id: typeof view.attempt_id === 'string' ? view.attempt_id : null, parts: parts as Record<string, string>,
      activity: object(view.activity) && typeof view.activity.category === 'string' ? view.activity.category : undefined } }
  }
  if (event.input_version < current.version) return current
  if (event.input_version > current.version) return null
  if (!event.run_id || current.assistant_turn && event.run_id !== current.assistant_turn.run_id) return current
  if (event.kind === 'answer.committed') {
    const p = event.payload
    if (p.sequence !== event.input_version + 1 || typeof p.message_id !== 'string' || typeof p.text !== 'string'
      || !object(p.assistant) || p.assistant.run_id !== event.run_id || !Array.isArray(p.assistant.citations)
      || !['mock', 'live'].includes(String(p.assistant.mode))) return null
    const message: SupportMessage = { message_id: p.message_id, sequence: p.sequence as number, text: p.text,
      author: 'ASSISTANT', recipient: 'CUSTOMER', ticket_id: null, created_at: event.created_at, assistant: p.assistant as unknown as SupportAssistant }
    return { ...current, generation: undefined, version: message.sequence, messages: [...current.messages.filter(m => m.message_id !== message.message_id), message],
      assistant_turn: { run_id: event.run_id, status: 'SUCCEEDED', reason: null } }
  }
  if (['answer.started', 'answer.reset', 'answer.delta', 'activity.started', 'activity.completed'].includes(event.kind)) {
    const generation = current.generation ?? { run_id: event.run_id, input_version: event.input_version, attempt_id: null, parts: {} }
    if (event.kind === 'answer.started' || event.kind === 'answer.reset') {
      if (!event.attempt_id) return current
      return { ...current, generation: event.kind === 'answer.started' && generation.attempt_id === event.attempt_id ? generation
        : { ...generation, attempt_id: event.attempt_id, parts: {}, activity: undefined } }
    }
    if (event.kind === 'answer.delta') {
      if (event.attempt_id !== generation.attempt_id) return current
      const { part_id: part, offset, text } = event.payload
      if (typeof part !== 'string' || !/^part-[0-7]$/.test(part) || typeof text !== 'string' || !Number.isSafeInteger(offset)) return null
      const existing = generation.parts[part] ?? ''
      if (Array.from(existing).length !== offset) return null
      const parts = { ...generation.parts, [part]: existing + text }
      if (Object.values(parts).reduce((total, value) => total + Array.from(value).length, 0) > 4000) return null
      return { ...current, generation: { ...generation, parts } }
    }
    return { ...current, generation: { ...generation, activity: event.kind === 'activity.started' && typeof event.payload.category === 'string' ? event.payload.category : undefined } }
  }
  const statuses: Partial<Record<SupportStreamEvent['kind'], NonNullable<SupportConversation['assistant_turn']>['status']>> = {
    'turn.accepted': 'PENDING', 'turn.started': 'RUNNING', 'answer.failed': 'FAILED', 'answer.stale': 'STALE' }
  const status = statuses[event.kind]
  return status ? { ...current, generation: undefined, assistant_turn: { run_id: event.run_id, status, reason: null } } : current
}

function delay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise(resolve => {
    const finish = () => { clearTimeout(timer); signal.removeEventListener('abort', finish); resolve() }
    const timer = setTimeout(finish, milliseconds)
    signal.addEventListener('abort', finish, { once: true })
    if (signal.aborted) finish()
  })
}

/** The cursor advances per delivered frame, including when the socket subsequently breaks. */
export async function watchSupportEvents(
  conversation: string, token: string, onEvent: (event: SupportStreamEvent) => void, signal: AbortSignal,
  onConnection: (connected: boolean) => void = () => {},
): Promise<void> {
  let cursor: string | null = null, backoff = 500
  while (!signal.aborted) {
    try {
      await consumeEventStream(`/api/v1/support/conversations/${encodeURIComponent(conversation)}/events`, token, cursor, frame => {
        if (signal.aborted) return
        const event: unknown = JSON.parse(frame.data)
        if (!object(event) || event.conversation_id !== conversation || event.event_id !== frame.id
          || !/^[0-9]{1,19}$/.test(frame.id) || !kinds.includes(event.kind as SupportStreamEvent['kind'])
          || event.kind !== frame.event || typeof event.created_at !== 'string'
          || !(event.run_id === null || typeof event.run_id === 'string')
          || !(event.attempt_id === null || typeof event.attempt_id === 'string')
          || !Number.isSafeInteger(event.input_version) || Number(event.input_version) < 1 || !object(event.payload)) return
        if (event.kind !== 'stream.snapshot' && cursor !== null && BigInt(frame.id) <= BigInt(cursor)) return
        onEvent(event as unknown as SupportStreamEvent)
        cursor = frame.id
        backoff = 500
      }, signal, () => onConnection(true))
    } catch (error) {
      if (signal.aborted) return
      if (error instanceof Error && /HTTP (401|403|404)/.test(error.message)) throw error
    } finally { onConnection(false) }
    if (!signal.aborted) await delay(backoff, signal)
    backoff = Math.min(backoff * 2, 5000)
  }
}
