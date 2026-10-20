import { apiRequest } from './client'

export interface SupportMessage { message_id: string; sequence: number; author: 'CUSTOMER' | 'MERCHANT'; recipient: 'ASSISTANT' | 'MERCHANT' | 'CUSTOMER'; text: string; ticket_id: string | null; created_at: string }
export interface SupportTicket { ticket_id: string; status: 'PENDING' | 'WAITING_CUSTOMER' | 'REPLIED' | 'RESOLVED'; summary: string; shared_messages: SupportMessage[] }
export interface SupportConversation {
  conversation_id: string; merchant_id: string; store_name: string; order_id: string; line_id: string
  product: { name: string; variant: string | null; asset_key: string | null; quantity: number; amount_minor: number; currency: string }
  version: number; ticket: SupportTicket | null; messages: SupportMessage[]; next_before_sequence: number | null
}
export interface SupportPage { items: SupportConversation[]; next_before: number | null }
export type SupportCommand =
  | { kind: 'send'; id: string; body: { expected_version: number; text: string; recipient: 'ASSISTANT' | 'MERCHANT' } }
  | { kind: 'handoff'; id: string; body: { expected_version: number; summary: string; shared_message_ids: string[] } }
  | { kind: 'reply'; id: string; body: { expected_version: number; text: string; kind: 'REPLY' | 'REQUEST_INFO' } }
  | { kind: 'resolve'; id: string; body: { expected_version: number } }
export type SupportPending = SupportCommand & { key: string; label: string }
const base = '/api/v1/support'
const query = (key: string, value?: number | null) => value ? `?${key}=${value}` : ''
function post<T>(token: string, path: string, body: unknown, key?: string) {
  return apiRequest<T>(base + path, token, { method: 'POST', headers: { 'Content-Type': 'application/json', ...(key ? { 'Idempotency-Key': key } : {}) }, body: JSON.stringify(body) })
}
export const supportApi = {
  open: (token: string, line: string) => post<SupportConversation>(token, '/conversations', { line_id: line }),
  conversations: (token: string, before?: number | null) => apiRequest<SupportPage>(`${base}/conversations${query('before', before)}`, token),
  tickets: (token: string, before?: number | null) => apiRequest<SupportPage>(`${base}/tickets${query('before', before)}`, token),
  read: (token: string, id: string, merchant = false, before?: number | null) => apiRequest<SupportConversation>(`${base}/${merchant ? 'tickets' : 'conversations'}/${encodeURIComponent(id)}${query('before_sequence', before)}`, token),
  mutate: (token: string, p: SupportPending) => {
    const suffix = p.kind === 'handoff' ? 'tickets' : p.kind === 'resolve' ? 'resolve' : 'messages'
    return post<SupportConversation>(token, `/${p.kind === 'reply' ? 'tickets' : 'conversations'}/${encodeURIComponent(p.id)}/${suffix}`, p.body, p.key)
  },
}
const pendingKey = (owner: string) => `resolveflow-support-v1:${owner}`
export function saveSupportPending(owner: string, pending: SupportPending) { sessionStorage.setItem(pendingKey(owner), JSON.stringify(pending)) }
export function readSupportPending(owner: string): SupportPending | null {
  try {
    const raw = sessionStorage.getItem(pendingKey(owner))
    if (!raw) return null
    const p = JSON.parse(raw)
    if (!['send', 'handoff', 'reply', 'resolve'].includes(p.kind) || typeof p.id !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(p.key) || typeof p.label !== 'string' || !p.body || !Number.isSafeInteger(p.body.expected_version) || p.body.expected_version < 1) throw Error('invalid')
    return p as SupportPending
  } catch { sessionStorage.removeItem(pendingKey(owner)); return null }
}
export function clearSupportPending(owner: string) { sessionStorage.removeItem(pendingKey(owner)) }
