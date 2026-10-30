import { apiRequest } from './client'

export interface PlatformMerchant { merchant_id: string; name: string; description: string; enabled: boolean; desired_enabled: boolean; version: number; sync_state: 'READY' | 'PENDING'; policy_ready: boolean }
export interface PlatformBuyer { username: string; display_name: string; enabled: boolean; version: number }
export interface ManagedSku { sku_id: string; variant: string; unit_amount: number; max_quantity: number; listed: boolean; version: number }
export interface ManagedProduct { product_id: string; store_id: string; name: string; description: string; category: string; asset_key: string; listed: boolean; version: number; skus: ManagedSku[] }
export interface ProductWrite { name: string; description: string; category: string; asset_key: string; listed: boolean; expected_version: number | null; skus: Array<{ sku_id: string | null; variant: string; unit_amount: number; max_quantity: number; listed: boolean }> }
function post<T>(path: string, token: string, body: unknown) { return apiRequest<T>(path, token, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) }
export const managementApi = {
  merchants: (token: string) => apiRequest<{ items: PlatformMerchant[] }>('/api/v1/platform/merchants', token),
  buyers: (token: string) => apiRequest<{ items: PlatformBuyer[] }>('/api/v1/platform/buyers', token),
  createMerchant: (token: string, body: { merchant_id: string; name: string; description: string; username: string; display_name: string; password: string; reason: string }) => post<PlatformMerchant>('/api/v1/platform/merchants', token, body),
  updateMerchant: (token: string, row: PlatformMerchant) => post<PlatformMerchant>(`/api/v1/platform/merchants/${encodeURIComponent(row.merchant_id)}`, token, { name: row.name, description: row.description, enabled: !row.desired_enabled, expected_version: row.version, reason: '平台管理员调整商家状态' }),
  syncMerchant: (token: string, id: string) => post<PlatformMerchant>(`/api/v1/platform/merchants/${encodeURIComponent(id)}/sync`, token, {}),
  createBuyer: (token: string, body: { username: string; display_name: string; password: string; reason: string }) => post<PlatformBuyer>('/api/v1/platform/buyers', token, body),
  updateBuyer: (token: string, row: PlatformBuyer, password?: string) => post<PlatformBuyer>(`/api/v1/platform/buyers/${encodeURIComponent(row.username)}`, token, { display_name: row.display_name, enabled: password ? row.enabled : !row.enabled, password: password || null, expected_version: row.version, reason: password ? '平台管理员重置买家密码' : '平台管理员调整买家状态' }),
  products: (token: string, after?: string) => apiRequest<{ items: ManagedProduct[]; next_after: string | null }>(`/api/v1/merchant/products?limit=8${after ? `&after=${encodeURIComponent(after)}` : ''}`, token),
  saveProduct: (token: string, id: string | null, body: ProductWrite) => post<ManagedProduct>(`/api/v1/merchant/products${id ? `/${encodeURIComponent(id)}` : ''}`, token, body),
}
