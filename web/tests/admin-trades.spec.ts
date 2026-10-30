import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { beforeEach, afterEach, it, expect, vi } from 'vitest'
import AdminTrades from '../src/ui/AdminTrades.vue'
import { ApiError } from '../src/client'
import { fulfillmentApi, type MerchantTrade } from '../src/fulfillment-client'
import { shipmentOwner, readShipmentPending, saveShipmentPending } from '../src/shipment-pending'

const id = '00000000-0000-4000-8000-000000000123'
const token = `header.${btoa(JSON.stringify({ sub: 'demo-admin' }))}.signature`
const account = { access_token: token, role: 'MERCHANT_ADMIN' as const, merchant_id: 'M-1001', merchant_name: '松间数码', expires_in: 3600 }
const time = '2026-10-03T04:00:00Z'
const trade: MerchantTrade = { purchase: { purchase_id: 'draft:one', draft_id: 'one', store_id: 'M-1001', store_name: '松间数码', status: 'PAID', total_amount: 72700, currency: 'CNY', created_at: time, paid_at: time, expires_at: null, order_id: id, payment: null, refund_status: 'NONE', lines: [
  { line_id: 'line1', sku: 'SKU1', product_name: '无线降噪耳机', variant: '黑色', asset_key: 'headphones', quantity: 1, unit_amount: 32900, line_amount: 32900 },
  { line_id: 'line2', sku: 'SKU2', product_name: '机械键盘', variant: '白色', asset_key: 'keyboard', quantity: 2, unit_amount: 19900, line_amount: 39800 }] }, fulfillment: { order_id: id, status: 'NOT_SHIPPED', synthetic: true, version: 1, updated_at: time, lines: ['line1','line2'].map(line_id => ({ line_id, status: 'NOT_SHIPPED', carrier_conclusion: 'UNKNOWN', source_version: 1, events: [{ code: 'ORDER_PAID', occurred_at: time, source_version: 1 }] })) }, can_ship: true, blocked_reason: null, line_aftercare: ['line1','line2'].map(line_id => ({ line_id, state: 'FREE', refunded_amount: 0, reserved_amount: 0 })) }
const shipped: MerchantTrade = { ...trade, can_ship: false, blocked_reason: '此订单已发货。', fulfillment: { ...trade.fulfillment, status: 'IN_TRANSIT', version: 2 } }
let w: VueWrapper
beforeEach(() => { sessionStorage.clear(); vi.spyOn(fulfillmentApi, 'orders').mockResolvedValue({ items: [trade], next_cursor: null }); vi.spyOn(fulfillmentApi, 'order').mockResolvedValue(trade); vi.spyOn(fulfillmentApi, 'ship').mockResolvedValue(shipped.fulfillment) })
afterEach(() => { w?.unmount(); vi.restoreAllMocks(); sessionStorage.clear() })
async function open() { w = mount(AdminTrades, { props: { account } }); await flushPromises() }
async function select() { await w.findAll('button').find(b => b.text() === '查看订单')!.trigger('click'); await flushPromises() }
async function confirm() { await w.get('[data-test="open-shipment"]').trigger('click'); await flushPromises(); await w.get('[data-test="confirm-shipment"]').trigger('click'); await flushPromises() }
it('shows all immutable goods and per-line aftercare, navigates to the actual order search', async () => {
  await open(); expect(w.text()).toContain('727.00'); expect(w.text()).toContain('机械键盘'); await select()
  expect(w.text()).toContain('398.00'); expect(w.text()).toContain('无退款占用');
  await w.findAll('button').find(b => b.text().includes('售后工单'))!.trigger('click'); expect(w.emitted('aftercare')).toEqual([[id]])
})
it('explicit confirmation sends only version and an original key, then shows persisted shipping', async () => {
  await open(); await select(); vi.mocked(fulfillmentApi.order).mockResolvedValue(shipped); await confirm()
  expect(fulfillmentApi.ship).toHaveBeenCalledWith(token, id, { expected_version: 1 }, expect.any(String))
  expect(w.text()).toContain('模拟发货已确认'); expect(w.text()).toContain('运输中'); expect(sessionStorage.length).toBe(0)
  expect(w.find('[data-test="open-shipment"]').exists()).toBe(false)
})
it('lost response survives remount and retries the same request without automatic writes', async () => {
  vi.mocked(fulfillmentApi.ship).mockRejectedValue(new TypeError('response lost')); await open(); await select(); await confirm()
  const original = readShipmentPending(shipmentOwner(account))!; expect(original.request).toEqual({ expected_version: 1 });
  w.unmount(); await open(); expect(fulfillmentApi.ship).toHaveBeenCalledTimes(1); expect(w.text()).toContain('发货结果待确认')
  vi.mocked(fulfillmentApi.ship).mockResolvedValue(shipped.fulfillment); vi.mocked(fulfillmentApi.order).mockResolvedValue(shipped)
  await w.get('[data-test="retry-shipment"]').trigger('click'); await flushPromises()
  expect(fulfillmentApi.ship).toHaveBeenLastCalledWith(token, id, original.request, original.key); expect(sessionStorage.length).toBe(0)
})
it('a confirmed shipment remains confirmed when its follow-up read fails', async () => {
  await open(); await select(); vi.mocked(fulfillmentApi.order).mockRejectedValue(new ApiError(503, 'UNAVAILABLE', '读取暂不可用')); await confirm()
  expect(w.text()).toContain('模拟发货已确认'); expect(w.text()).not.toContain('发货结果尚未确认'); expect(w.text()).toContain('运输中'); expect(sessionStorage.length).toBe(0)
})
it('an explicit conflict clears the refused request and requires current state to be reread', async () => {
  vi.mocked(fulfillmentApi.ship).mockRejectedValue(new ApiError(409, 'CONFLICT', '退款金额已占用')); await open(); await select(); await confirm()
  expect(w.text()).toContain('退款金额已占用'); expect(sessionStorage.length).toBe(0); expect(w.find('[data-test="open-shipment"]').exists()).toBe(false)
})
it('session expiry preserves the original receipt for the same administrator', async () => {
  vi.mocked(fulfillmentApi.ship).mockRejectedValue(new ApiError(401, 'UNAUTHENTICATED', 'expired')); await open(); await select(); await confirm()
  expect(w.emitted('expired')).toHaveLength(1); expect(readShipmentPending(shipmentOwner(account))).not.toBeNull()
})
it('invalid saved requests block new writes without destroying recovery information', async () => {
  sessionStorage.setItem(`resolveflow.shipment.pending.${shipmentOwner(account)}`, '{bad'); await open(); await select()
  expect(w.text()).toContain('保存的发货请求无法读取'); expect(w.get('[data-test="open-shipment"]').attributes('disabled')).toBeDefined(); expect(fulfillmentApi.ship).not.toHaveBeenCalled()
})
it('refuses to write if the browser cannot persist the original request', async () => {
  await open(); await select(); vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') }); await confirm()
  expect(w.text()).toContain('无法保存原发货请求'); expect(fulfillmentApi.ship).not.toHaveBeenCalled()
})
it('filters and pagination carry the exact scope filter rather than claiming a total', async () => {
  vi.mocked(fulfillmentApi.orders).mockResolvedValue({ items: [trade], next_cursor: 'next' }); await open()
  await w.findAll('button').find(b => b.text() === '下一页')!.trigger('click'); await flushPromises()
  expect(fulfillmentApi.orders).toHaveBeenLastCalledWith(token, { cursor: 'next' })
  await w.findAll('.trade-filters button').find(b => b.text() === '运输中')!.trigger('click'); await flushPromises()
  expect(fulfillmentApi.orders).toHaveBeenLastCalledWith(token, { status: 'IN_TRANSIT' }); expect(w.text()).toContain('第 1 页'); expect(w.findAll('.trade-order')).toHaveLength(1)
})
it('a different actor or store never consumes another administrators local receipt', async () => {
  saveShipmentPending(shipmentOwner(account), { order: id, key: 'original', request: { expected_version: 1 } })
  const other = { ...account, access_token: `header.${btoa(JSON.stringify({ sub: 'other-admin' }))}.signature` }
  w = mount(AdminTrades, { props: { account: other } }); await flushPromises()
  expect(w.find('[data-test="retry-shipment"]').exists()).toBe(false); expect(readShipmentPending(shipmentOwner(account))?.key).toBe('original')
})

it('replaces order pages, preserves the current page on failed navigation and returns using the original cursor', async () => {
  const second = structuredClone(trade); second.purchase.order_id = 'second'; second.purchase.lines[0].product_name = '第二页商品'
  vi.mocked(fulfillmentApi.orders).mockResolvedValueOnce({ items: [trade], next_cursor: 'cursor-2' })
    .mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ items: [second], next_cursor: null })
    .mockResolvedValueOnce({ items: [trade], next_cursor: 'cursor-2' })
  await open()
  const next = () => w.findAll('button').filter(b => b.text() === '下一页')[0]
  await next().trigger('click'); await flushPromises()
  expect(w.text()).toContain('第 1 页'); expect(w.text()).toContain('无线降噪耳机')
  await next().trigger('click'); await flushPromises()
  expect(fulfillmentApi.orders).toHaveBeenLastCalledWith(token, { cursor: 'cursor-2' })
  expect(w.findAll('.trade-order')).toHaveLength(1); expect(w.text()).toContain('第二页商品'); expect(w.text()).not.toContain('无线降噪耳机')
  await w.findAll('button').filter(b => b.text() === '上一页')[0].trigger('click'); await flushPromises()
  expect(fulfillmentApi.orders).toHaveBeenLastCalledWith(token, {})
  expect(w.text()).toContain('第 1 页'); expect(w.text()).not.toContain('第二页商品')
})
