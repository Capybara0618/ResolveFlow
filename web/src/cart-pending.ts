import type { CartRequest, CartDraftRequest, CartQuote } from './shop-client'

export type CartPending = { kind: 'mutation'; key: string; store: string; request: CartRequest }
  | { kind: 'draft'; key: string; store: string; request: CartDraftRequest; quote: CartQuote }
const storageKey = (buyer: string) => `resolveflow.cart.pending.${buyer}`
export function readCartPending(buyer: string): CartPending | null {
  const raw = sessionStorage.getItem(storageKey(buyer))
  if (!raw) return null
  try {
    const p = JSON.parse(raw)
    if (!['mutation', 'draft'].includes(p.kind) || typeof p.key !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(p.key)
      || typeof p.store !== 'string' || !/^[A-Za-z0-9_-]{1,64}$/.test(p.store) || !p.request) throw new Error('invalid')
    if (p.kind === 'mutation' && (typeof p.request.sku_id !== 'string' || !Number.isInteger(p.request.quantity)
      || !Number.isSafeInteger(p.request.expected_revision))) throw new Error('invalid')
    if (p.kind === 'draft' && (!p.quote || p.quote.store_id !== p.store || !Array.isArray(p.quote.lines)
      || !Array.isArray(p.request.lines) || !Number.isSafeInteger(p.request.expected_revision))) throw new Error('invalid')
    return p as CartPending
  } catch { throw new Error('保存的购物车请求无法读取，请保留当前页面并检查浏览器会话存储。') }
}
export function saveCartPending(buyer: string, pending: CartPending) {
  sessionStorage.setItem(storageKey(buyer), JSON.stringify(pending))
}
export function clearCartPending(buyer: string, key: string) {
  const saved = readCartPending(buyer)
  if (saved?.key === key) sessionStorage.removeItem(storageKey(buyer))
}
