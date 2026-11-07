import type { LoginResponse } from './client'

const key = 'resolveflow.tab-session.v1'
const selectionKey = (owner: string) => `resolveflow.support-selection.v1:${owner}`
const roles = ['CUSTOMER', 'REVIEWER', 'MERCHANT_ADMIN', 'OPERATOR', 'PLATFORM_ADMIN']
function valid(value: unknown): value is LoginResponse {
  if (!value || typeof value !== 'object') return false
  const session = value as Record<string, unknown>
  return typeof session.access_token === 'string' && session.access_token.length > 0
    && roles.includes(String(session.role)) && typeof session.expires_in === 'number'
    && Number.isFinite(session.expires_in) && session.expires_in > 0
    && ['merchant_id', 'buyer_id', 'display_name', 'merchant_name'].every(
      field => session[field] === undefined || typeof session[field] === 'string')
    && (session.single_operator === undefined || typeof session.single_operator === 'boolean')
}

export function clearTabSession(): void {
  try { sessionStorage.removeItem(key) } catch { /* In-memory login still works when storage is disabled. */ }
}
export function saveTabSession(session: LoginResponse): void {
  if (!valid(session)) { clearTabSession(); return }
  const { access_token, role, expires_in, merchant_id, buyer_id, display_name, merchant_name, single_operator } = session
  try {
    sessionStorage.setItem(key, JSON.stringify({ expires_at: Date.now() + expires_in * 1000,
      session: { access_token, role, expires_in, merchant_id, buyer_id, display_name, merchant_name, single_operator } }))
  } catch { /* Do not fail a successful login just because tab storage is unavailable. */ }
}
export function readTabSession(): LoginResponse | null {
  try {
    const stored = JSON.parse(sessionStorage.getItem(key) || 'null')
    if (stored && valid(stored.session) && Number.isFinite(stored.expires_at) && stored.expires_at > Date.now()) return stored.session
  } catch { /* Invalid/disabled storage requires an ordinary login. */ }
  clearTabSession(); return null
}
export function saveSupportSelection(owner: string, id: string): void {
  try { sessionStorage.setItem(selectionKey(owner), id) } catch { /* Selection is optional tab state. */ }
}
export function readSupportSelection(owner: string): string | null {
  try { return sessionStorage.getItem(selectionKey(owner)) } catch { return null }
}
