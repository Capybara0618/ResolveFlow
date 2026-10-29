import { apiRequest } from './client'
export interface Specification { name: string; value: string }
export interface ProductPresentation { product_id: string; version: number; images: string[]; specifications: Specification[]; shipping_note: string; aftercare_note: string }
export interface StorePresentation { store_id: string; version: number; introduction: string; logo_id: string | null; contact_phone: string; service_hours: string }
export type ProductPresentationWrite = Omit<ProductPresentation, 'product_id' | 'version'> & { expected_version: number }
export type StorePresentationWrite = Omit<StorePresentation, 'store_id' | 'version'> & { expected_version: number }
const post = <T>(path: string, token: string, body: unknown) => apiRequest<T>(path, token, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
export const presentationApi = {
  product: (id: string, token?: string) => apiRequest<ProductPresentation>(`/api/v1/${token ? 'merchant' : 'shop'}/products/${encodeURIComponent(id)}/presentation`, token ?? null),
  store: (id: string) => apiRequest<StorePresentation>(`/api/v1/shop/stores/${encodeURIComponent(id)}/presentation`, null),
  managedStore: (token: string) => apiRequest<StorePresentation>('/api/v1/merchant/store/presentation', token),
  saveProduct: (token: string, id: string, body: ProductPresentationWrite) => post<ProductPresentation>(`/api/v1/merchant/products/${encodeURIComponent(id)}/presentation`, token, body),
  saveStore: (token: string, body: StorePresentationWrite) => post<StorePresentation>('/api/v1/merchant/store/presentation', token, body),
  upload: (token: string, file: File) => { const body = new FormData(); body.append('file', file); return apiRequest<{ media_id: string }>('/api/v1/merchant/media', token, { method: 'POST', body }) },
}

const storeCache = new Map<string, { at: number; request: Promise<StorePresentation> }>()
export function readStorePresentation(id: string): Promise<StorePresentation> {
  const existing = storeCache.get(id)
  if (existing && Date.now() - existing.at < 30000) return existing.request
  if (storeCache.size >= 100) storeCache.delete(storeCache.keys().next().value!)
  const request = presentationApi.store(id).catch(e => { storeCache.delete(id); throw e })
  storeCache.set(id, { at: Date.now(), request }); return request
}
export function invalidateStorePresentation(id: string) { storeCache.delete(id) }
