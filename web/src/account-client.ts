import { apiRequest, ApiError } from './client'

export interface AccountProfile { username: string; display_name: string; avatar_id: string | null; version: number }
export interface Address { address_id: string; recipient: string; phone: string; province: string; city: string; district: string; detail: string; is_default: boolean; version: number }
export type AddressInput = Omit<Address, 'address_id' | 'version'> & { expected_version?: number }
export interface ShippingSelection { address_id: string; expected_version: number }
export interface ShippingSnapshot { address_id: string; version: number; recipient: string; phone: string; province: string; city: string; district: string; detail: string }
const post = <T>(path: string, token: string, body: unknown) => apiRequest<T>(path, token, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
export const accountApi = {
  profile: (token: string) => apiRequest<AccountProfile>('/api/v1/account/profile', token),
  save: (token: string, name: string, version: number) => post<AccountProfile>('/api/v1/account/profile', token, { display_name: name, expected_version: version }),
  upload: (token: string, file: File, version: number) => {
    const data = new FormData(); data.append('file', file); data.append('expected_version', String(version))
    return apiRequest<AccountProfile>('/api/v1/account/avatar', token, { method: 'POST', body: data })
  },
  reset: (token: string, version: number) => post<AccountProfile>('/api/v1/account/avatar/reset', token, { expected_version: version }),
  addresses: (token: string) => apiRequest<{ items: Address[] }>('/api/v1/account/addresses', token),
  saveAddress: (token: string, id: string | null, body: AddressInput) => post<Address>(`/api/v1/account/addresses${id ? `/${encodeURIComponent(id)}` : ''}`, token, body),
  deleteAddress: (token: string, row: Address) => post<void>(`/api/v1/account/addresses/${encodeURIComponent(row.address_id)}/delete`, token, { expected_version: row.version }),
}
export async function avatarBlob(token: string, path: string): Promise<Blob> {
  const response = await fetch(path, { headers: { Authorization: `Bearer ${token}` } })
  if (!response.ok) throw new ApiError(response.status, 'AVATAR_UNAVAILABLE', '头像暂时无法读取')
  return response.blob()
}
