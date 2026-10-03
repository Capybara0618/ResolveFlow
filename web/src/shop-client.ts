import { apiRequest } from './client'

export interface ShopStore { store_id: string; name: string; description: string }
export interface ShopSku { sku_id: string; variant: string; unit_amount: number; max_quantity: number; version: number }
export interface ShopProduct { product_id: string; store_id: string; store_name: string; name: string; description: string
  category: 'electronics' | 'home'; asset_key: string; from_amount: number; currency: 'CNY'; skus: ShopSku[] }
export interface ShopProducts { items: ShopProduct[]; next_after: string | null }
export interface ShopQuote { product: ShopProduct; sku: ShopSku; quantity: number; total_amount: number; currency: 'CNY' }
export interface ShopDraftRequest { sku_id: string; quantity: number; expected_sku_version: number }
export interface ShopDraft { draft_id: string; store_id: string; store_name: string; product_id: string; product_name: string
  asset_key: string; sku_id: string; variant: string; quantity: number; unit_amount: number; total_amount: number
  currency: 'CNY'; status: PurchaseStatus; created_at: string; expires_at: string }
export type PurchaseStatus = 'WAITING_PAYMENT' | 'PAYMENT_PENDING' | 'PAID' | 'CANCELLED' | 'EXPIRED'
export interface CheckoutPayment { attempt_id: string; draft_id: string; status: 'UNKNOWN' | 'SUCCEEDED' | 'FAILED'
  total_amount: number; currency: 'CNY'; created_at: string; finished_at: string | null; order_id: string | null; line_id: string | null; paid_at: string | null }
export interface PurchaseLine { line_id: string | null; sku: string; product_name: string | null; variant: string | null
  asset_key: string | null; quantity: number; unit_amount: number | null; line_amount: number }
export interface Purchase { purchase_id: string; draft_id: string | null; store_id: string; store_name: string; status: PurchaseStatus
  total_amount: number; currency: 'CNY'; created_at: string; expires_at: string | null; paid_at: string | null
  order_id: string | null; lines: PurchaseLine[]; payment: CheckoutPayment | null }
function post<T>(path: string, token: string | null, body: unknown, key?: string) {
  return apiRequest<T>(path, token, { method: 'POST', headers: { 'Content-Type': 'application/json', ...(key ? { 'Idempotency-Key': key } : {}) }, body: JSON.stringify(body) })
}
export const shopApi = {
  stores: () => apiRequest<ShopStore[]>('/api/v1/shop/stores', null),
  store: (id: string) => apiRequest<ShopStore>(`/api/v1/shop/stores/${encodeURIComponent(id)}`, null),
  products: (filter: { query?: string; category?: string; store_id?: string; after?: string } = {}) => {
    const params = new URLSearchParams({ ...filter, limit: '24' })
    return apiRequest<ShopProducts>(`/api/v1/shop/products?${params}`, null)
  },
  product: (id: string) => apiRequest<ShopProduct>(`/api/v1/shop/products/${encodeURIComponent(id)}`, null),
  quote: (sku: string, quantity: number) => post<ShopQuote>('/api/v1/shop/quote', null, { sku_id: sku, quantity }),
  draft: (token: string, body: ShopDraftRequest, key: string) => post<ShopDraft>('/api/v1/shop/drafts', token, body, key),
  readDraft: (token: string, id: string) => apiRequest<ShopDraft>(`/api/v1/shop/drafts/${encodeURIComponent(id)}`, token),
  pay: (token: string, id: string, key: string) => post<CheckoutPayment>(`/api/v1/shop/drafts/${encodeURIComponent(id)}/payment`, token, {}, key),
  payment: (token: string, id: string) => apiRequest<{ payment: CheckoutPayment | null }>(`/api/v1/shop/drafts/${encodeURIComponent(id)}/payment`, token),
  cancel: (token: string, id: string) => post<ShopDraft>(`/api/v1/shop/drafts/${encodeURIComponent(id)}/cancel`, token, {}),
  purchase: (token: string, id: string) => apiRequest<Purchase>(`/api/v1/shop/purchases/${encodeURIComponent(id)}`, token),
  purchases: (token: string, filter: { store_id?: string; status?: PurchaseStatus; cursor?: string } = {}) =>
    apiRequest<{ items: Purchase[]; next_cursor: string | null }>(`/api/v1/shop/purchases?${new URLSearchParams({ ...filter, limit: '24' })}`, token),
}
