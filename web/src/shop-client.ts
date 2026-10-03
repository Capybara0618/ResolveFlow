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
  currency: 'CNY'; status: 'WAITING_PAYMENT' | 'EXPIRED'; created_at: string; expires_at: string }
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
}
