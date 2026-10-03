import { apiRequest } from './client'
import type { Purchase } from './shop-client'

export type FulfillmentStatus = 'NOT_SHIPPED' | 'IN_TRANSIT' | 'DELIVERED' | 'LOST' | 'UNKNOWN'
export interface FulfillmentEvent { code: string; occurred_at: string; source_version: number }
export interface FulfillmentLine { line_id: string; status: FulfillmentStatus; carrier_conclusion: string; source_version: number | null; events: FulfillmentEvent[] }
export interface OrderFulfillment { order_id: string; status: FulfillmentStatus; synthetic: true; version: number | null; updated_at: string | null; lines: FulfillmentLine[] }
export interface LineAftercare { line_id: string; state: 'FREE' | 'RESERVED' | 'CONSUMED' | 'MISSING'; refunded_amount: number | null; reserved_amount: number | null }
export interface MerchantTrade { purchase: Purchase; fulfillment: OrderFulfillment; line_aftercare: LineAftercare[]; can_ship: boolean; blocked_reason: string | null }
export const fulfillmentLabels: Record<FulfillmentStatus, string> = { NOT_SHIPPED: '待发货', IN_TRANSIT: '运输中', DELIVERED: '已签收', LOST: '物流丢失', UNKNOWN: '物流状态未知' }
export const fulfillmentApi = {
  buyer: (token: string, purchase: string) => apiRequest<OrderFulfillment>(`/api/v1/shop/purchases/${encodeURIComponent(purchase)}/fulfillment`, token),
  orders: (token: string, filter: { status?: FulfillmentStatus; cursor?: string } = {}) => apiRequest<{ items: MerchantTrade[]; next_cursor: string | null }>(`/api/v1/merchant/orders?${new URLSearchParams({ ...filter, limit: '24' })}`, token),
  order: (token: string, id: string) => apiRequest<MerchantTrade>(`/api/v1/merchant/orders/${encodeURIComponent(id)}`, token),
  ship: (token: string, id: string, request: { expected_version: number }, key: string) => apiRequest<OrderFulfillment>(`/api/v1/merchant/orders/${encodeURIComponent(id)}/simulated-shipment`, token,
    { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(request) }),
}
