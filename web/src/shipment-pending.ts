import type { LoginResponse } from './client'

export interface ShipmentPending { order: string; key: string; request: { expected_version: number } }
// Decoding is only for segregating local recovery receipts. All permissions come from the server.
export function shipmentOwner(account: LoginResponse): string {
  if (account.role !== 'MERCHANT_ADMIN' || !account.merchant_id) throw new Error('当前账号无法发货。')
  try {
    const payload = JSON.parse(atob(account.access_token.split('.')[1]!.replace(/-/g, '+').replace(/_/g, '/')))
    if (typeof payload.sub !== 'string' || !/^[A-Za-z0-9_-]{1,120}$/.test(payload.sub)) throw new Error('invalid')
    return `${account.merchant_id}:${payload.sub}`
  } catch { throw new Error('无法识别原发货请求的账号，请重新登录。') }
}
const name = (owner: string) => `resolveflow.shipment.pending.${owner}`
export function readShipmentPending(owner: string): ShipmentPending | null {
  const raw = sessionStorage.getItem(name(owner))
  if (!raw) return null
  try {
    const p = JSON.parse(raw)
    if (Object.keys(p).sort().join(',') !== 'key,order,request' || typeof p.order !== 'string'
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(p.order) || typeof p.key !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(p.key)
      || !p.request || Object.keys(p.request).join(',') !== 'expected_version'
      || !Number.isSafeInteger(p.request.expected_version) || p.request.expected_version < 1) throw new Error('invalid')
    return p
  } catch { throw new Error('保存的发货请求无法读取。请保留浏览器会话，先核对原订单；暂不能发起新的发货。') }
}
export function saveShipmentPending(owner: string, value: ShipmentPending) { sessionStorage.setItem(name(owner), JSON.stringify(value)) }
export function clearShipmentPending(owner: string, key: string) {
  if (readShipmentPending(owner)?.key === key) sessionStorage.removeItem(name(owner))
}
