import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { beforeEach, afterEach, it, expect, vi } from 'vitest'
import { fulfillmentApi } from '../src/fulfillment-client'
import BuyerOrders from '../src/ui/BuyerOrders.vue'
import MarketplaceWorkspace from '../src/ui/MarketplaceWorkspace.vue'
import CustomerWorkspace from '../src/ui/CustomerWorkspace.vue'
import { shopApi, type Purchase, type CheckoutPayment } from '../src/shop-client'
import { ApiError, coreApi, type CustomerOrderLine } from '../src/client'
import { reviewApi } from '../src/review-client'

const buyer = { access_token: 'buyer-token', role: 'CUSTOMER' as const, buyer_id: 'B-3001', expires_in: 3600 }
const item: Purchase = { purchase_id: 'draft:one', draft_id: 'one', store_id: 'M-1001', store_name: '松间数码', status: 'WAITING_PAYMENT', total_amount: 65800, currency: 'CNY', created_at: '2026-10-03T04:00:00Z', expires_at: '2099-10-03T04:15:00Z', paid_at: null, order_id: null, payment: null, lines: [{ line_id: null, sku: 'SKU', product_name: '无线降噪耳机', variant: '黑色', asset_key: 'headphones', quantity: 2, unit_amount: 32900, line_amount: 65800 }] }
const success: CheckoutPayment = { attempt_id: 'original-attempt', draft_id: 'one', status: 'SUCCEEDED', total_amount: 65800, currency: 'CNY', created_at: item.created_at, finished_at: '2026-10-03T04:01:00Z', order_id: 'order-one', line_id: 'line-one', paid_at: '2026-10-03T04:01:00Z' }
const paid: Purchase = { ...item, status: 'PAID', paid_at: success.paid_at, order_id: success.order_id, payment: success, lines: [{ ...item.lines[0], line_id: success.line_id }] }
const context: CustomerOrderLine = { order_line: { order_id: 'order-one', line_id: 'line-one', sku: 'SKU', product_name: '无线降噪耳机', variant_text: '黑色', category: 'electronics', quantity: 2, line_paid_amount: 65800, currency: 'CNY', paid_at: paid.paid_at!, status: 'PAID' }, application: null, can_apply: true, blocked_reason: '' }
let w: VueWrapper
beforeEach(() => {
  window.sessionStorage.clear(); window.history.replaceState(null, '', '/#/shop/drafts/one')
  vi.spyOn(fulfillmentApi, 'buyer').mockResolvedValue({ order_id: 'order-one', status: 'NOT_SHIPPED', synthetic: true, version: 1, updated_at: paid.paid_at, lines: [{ line_id: 'line-one', status: 'NOT_SHIPPED', carrier_conclusion: 'UNKNOWN', source_version: 1, events: [{ code: 'ORDER_PAID', occurred_at: paid.paid_at!, source_version: 1 }] }] })
  vi.spyOn(shopApi, 'purchase').mockResolvedValue(item)
  vi.spyOn(shopApi, 'purchases').mockResolvedValue({ items: [item], next_cursor: null })
  vi.spyOn(shopApi, 'stores').mockResolvedValue([{ store_id: 'M-1001', name: '松间数码', description: '数码' }])
  vi.spyOn(shopApi, 'pay').mockResolvedValue(success)
  vi.spyOn(shopApi, 'payment').mockResolvedValue({ payment: null })
  vi.spyOn(shopApi, 'cancel').mockResolvedValue({ ...item, draft_id: 'one', product_id: 'P1', product_name: '耳机', asset_key: 'headphones', sku_id: 'SKU', variant: '黑色', quantity: 2, unit_amount: 32900, expires_at: item.expires_at!, status: 'CANCELLED' })
  vi.spyOn(coreApi, 'customerOrderLine').mockResolvedValue(context)
})
afterEach(() => { w?.unmount(); vi.restoreAllMocks(); vi.useRealTimers(); window.sessionStorage.clear() })
async function open() { w = mount(BuyerOrders, { props: { account: buyer } }); await flushPromises() }
it('opens order-line reviews only on demand and displays authoritative delivery eligibility', async () => {
  vi.mocked(shopApi.purchase).mockResolvedValue(paid)
  vi.spyOn(reviewApi, 'own').mockResolvedValue({ can_review: false, blocked_reason: '签收后可评价', review: null })
  await open(); expect(reviewApi.own).not.toHaveBeenCalled()
  await w.get('[data-test="product-review"]').trigger('click'); await flushPromises()
  expect(reviewApi.own).toHaveBeenCalledWith('buyer-token', 'line-one')
  expect(w.text()).toContain('签收后可评价')
})
it('records no client amount and confirms success only after owned purchase is published', async () => {
  await open(); vi.mocked(shopApi.purchase).mockResolvedValue(paid)
  await w.get('[data-test="pay"]').trigger('click'); await flushPromises()
  expect(shopApi.pay).toHaveBeenCalledWith('buyer-token', 'one', expect.any(String)); expect(w.text()).toContain('模拟付款完成于')
  expect(w.find('[data-test="pay"]').exists()).toBe(false); expect(window.sessionStorage.length).toBe(0)
  expect(w.text()).toContain('658.00'); expect(w.text()).toContain('商家审核')
})
it('after a lost response queries the original attempt and never automatically starts another payment', async () => {
  vi.mocked(shopApi.pay).mockRejectedValue(new TypeError('response lost')); await open()
  await w.get('[data-test="pay"]').trigger('click'); await flushPromises()
  const original = vi.mocked(shopApi.pay).mock.calls[0][2]
  expect(w.text()).toContain('结果尚未确认'); expect(window.sessionStorage.getItem('resolveflow:checkout:B-3001:one')).toBe(original)
  vi.mocked(shopApi.payment).mockResolvedValue({ payment: success }); vi.mocked(shopApi.purchase).mockResolvedValue(paid)
  await w.findAll('button').find(b => b.text() === '查询原付款结果')!.trigger('click'); await flushPromises()
  expect(shopApi.pay).toHaveBeenCalledTimes(1); expect(shopApi.payment).toHaveBeenCalledWith('buyer-token', 'one'); expect(w.text()).toContain('已付款')
})
it('remount keeps the same unknown payment key and allows only an explicit original retry', async () => {
  vi.mocked(shopApi.pay).mockRejectedValueOnce(new TypeError('before accept')); await open()
  await w.get('[data-test="pay"]').trigger('click'); await flushPromises()
  const original = vi.mocked(shopApi.pay).mock.calls[0][2]; w.unmount()
  vi.mocked(shopApi.purchase).mockResolvedValue({ ...item, status: 'PAYMENT_PENDING', payment: { ...success, status: 'UNKNOWN', order_id: null, line_id: null, paid_at: null, finished_at: null } })
  await open(); expect(shopApi.pay).toHaveBeenCalledTimes(1)
  vi.mocked(shopApi.purchase).mockResolvedValue(paid); await w.get('[data-test="pay"]').trigger('click'); await flushPromises()
  expect(vi.mocked(shopApi.pay).mock.calls[1][2]).toBe(original)
})
it('an unknown payment without a stored key remains query-only and cannot be cancelled', async () => {
  vi.mocked(shopApi.purchase).mockResolvedValue({ ...item, status: 'PAYMENT_PENDING' }); await open()
  expect(w.find('[data-test="pay"]').exists()).toBe(false); expect(w.text()).not.toContain('取消订单'); expect(w.text()).toContain('查询原付款结果')
  expect(shopApi.pay).not.toHaveBeenCalled(); expect(shopApi.cancel).not.toHaveBeenCalled()
})
it('expiry is enforced in the page and cancellation requires explicit confirmation', async () => {
  vi.mocked(shopApi.purchase).mockResolvedValue({ ...item, expires_at: '2020-01-01T00:00:00Z' }); await open()
  expect(w.find('[data-test="pay"]').exists()).toBe(false); expect(w.text()).not.toContain('取消订单'); w.unmount()
  vi.mocked(shopApi.purchase).mockResolvedValue(item); await open()
  await w.findAll('button').find(b => b.text() === '取消订单')!.trigger('click'); await flushPromises()
  expect(shopApi.cancel).not.toHaveBeenCalled(); expect(w.get('[role="dialog"]').text()).toContain('确认取消')
  vi.mocked(shopApi.purchase).mockResolvedValue({ ...item, status: 'CANCELLED' })
  await w.findAll('button').find(b => b.text() === '确认取消')!.trigger('click'); await flushPromises()
  expect(shopApi.cancel).toHaveBeenCalledTimes(1); expect(w.text()).toContain('已取消'); expect(shopApi.pay).not.toHaveBeenCalled()
})
it('cancel response loss blocks payment until a read confirms the current status', async () => {
  vi.mocked(shopApi.cancel).mockRejectedValue(new TypeError('cancel lost')); await open()
  await w.findAll('button').find(b => b.text() === '取消订单')!.trigger('click'); await flushPromises()
  await w.findAll('button').find(b => b.text() === '确认取消')!.trigger('click'); await flushPromises()
  expect(w.find('[data-test="pay"]').exists()).toBe(false); expect(w.text()).toContain('取消结果尚未确认')
})
it('list filters and details go through real marketplace routing instead of a dead button', async () => {
  window.history.replaceState(null, '', '/#/shop/orders')
  w = mount(MarketplaceWorkspace, { props: { account: buyer } }); await flushPromises()
  expect(shopApi.purchases).toHaveBeenCalledWith('buyer-token', {})
  await w.get('[aria-label="更多订单状态"]').setValue('PAID'); await flushPromises()
  expect(shopApi.purchases).toHaveBeenLastCalledWith('buyer-token', { status: 'PAID' })
  await w.findAll('.purchase-card button')[0].trigger('click'); await flushPromises()
  expect(shopApi.purchase).toHaveBeenCalledWith('buyer-token', item.purchase_id)
})
it('does not apply a late owned purchase response after navigation', async () => {
  let resolve!: (p: Purchase) => void; vi.mocked(shopApi.purchase).mockReturnValue(new Promise(r => { resolve = r }))
  w = mount(BuyerOrders, { props: { account: buyer } }); w.unmount(); resolve(paid); await flushPromises()
  expect(coreApi.customerOrderLine).not.toHaveBeenCalled()
})
it('direct aftercare route re-reads authoritative line eligibility before displaying the form', async () => {
  window.history.replaceState(null, '', '/#/customer/apply/line-one')
  w = mount(CustomerWorkspace, { props: { account: buyer } }); await flushPromises()
  expect(coreApi.customerOrderLine).toHaveBeenCalledWith('buyer-token', 'line-one'); expect(w.text()).toContain('确认申请订单')
  w.unmount(); vi.mocked(coreApi.customerOrderLine).mockResolvedValue({ ...context, can_apply: false, blocked_reason: '该行已完成退款' })
  w = mount(CustomerWorkspace, { props: { account: buyer } }); await flushPromises()
  expect(w.text()).toContain('该行已完成退款'); expect(w.text()).not.toContain('确认申请订单')
})
it('expired session emits logout and never shows a fake successful payment', async () => {
  vi.mocked(shopApi.purchase).mockRejectedValue(new ApiError(401, 'UNAUTHENTICATED', 'disabled')); await open()
  expect(w.emitted('expired')).toHaveLength(1); expect(w.text()).not.toContain('模拟付款完成于')
})

it('cancelled aftercare keeps its history and allows a new application when the server permits it', async () => {
  vi.mocked(shopApi.purchase).mockResolvedValue(paid)
  vi.mocked(coreApi.customerOrderLine).mockResolvedValue({ ...context, application: { case_id: 'cancelled-case', status: 'CANCELLED', line_id: 'line-one', order_id: 'order-one', description: 'previous', version: 2, created_at: item.created_at, updated_at: item.created_at } })
  await open()
  expect(w.text()).toContain('查看上次售后申请')
  await w.findAll('button').find(b => b.text() === '申请售后')!.trigger('click')
  expect(w.emitted('navigate')).toEqual([['#/customer/apply/line-one']])
  expect(shopApi.pay).not.toHaveBeenCalled()
})

it('consumed aftercare offers only the original application and cannot apply again', async () => {
  vi.mocked(shopApi.purchase).mockResolvedValue(paid)
  vi.mocked(coreApi.customerOrderLine).mockResolvedValue({ ...context, can_apply: false, application: { case_id: 'refunded-case', status: 'CLOSED_SUCCESS', line_id: 'line-one', order_id: 'order-one', description: 'refunded', version: 4, created_at: item.created_at, updated_at: item.created_at }, blocked_reason: '已退款' })
  await open()
  expect(w.findAll('button').some(b => b.text() === '申请售后')).toBe(false)
  await w.findAll('button').find(b => b.text() === '查看售后申请')!.trigger('click')
  expect(w.emitted('navigate')).toEqual([['#/customer/applications/refunded-case']])
})

it('paid order displays authoritative unshipped facts and never guesses a missing shipment', async () => {
  vi.mocked(shopApi.purchase).mockResolvedValue(paid); await open()
  expect(fulfillmentApi.buyer).toHaveBeenCalledWith('buyer-token', paid.purchase_id)
  expect(w.get('[aria-label="订单履约"]').text()).toContain('商家尚未发货')
  vi.mocked(fulfillmentApi.buyer).mockRejectedValue(new ApiError(503, 'UNAVAILABLE', 'offline'))
  await w.findAll('button').find(b => b.text() === '刷新状态')!.trigger('click'); await flushPromises()
  expect(w.get('[aria-label="订单履约"]').text()).toContain('未读取成功不表示未发货')
  expect(w.get('[aria-label="订单履约"]').text()).not.toContain('商家尚未发货')
})

it('returns to the same filtered, expanded list and reading position without recreating the orders module', async () => {
  vi.useFakeTimers(); const scroll = vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
  vi.spyOn(window, 'scrollY', 'get').mockReturnValue(480)
  const second = { ...paid, purchase_id: 'second-order', lines: [{ ...paid.lines[0], product_name: '第二笔商品' }] }
  vi.mocked(shopApi.purchases).mockImplementation(async (_token, query) => query?.cursor ? { items: [second], next_cursor: null } : { items: [paid], next_cursor: 'page-two' })
  vi.mocked(shopApi.purchase).mockResolvedValue(second)
  window.history.replaceState(null, '', '/#/shop/orders?status=PAID')
  w = mount(MarketplaceWorkspace, { props: { account: buyer } }); await flushPromises()
  const instance = w.get('.buyer-orders').element
  await w.findAll('button').find(b => b.text() === '加载更多订单')!.trigger('click'); await flushPromises()
  await w.findAll('.purchase-card button')[1].trigger('click'); await flushPromises()
  expect(w.get('.buyer-orders').element).toBe(instance)
  expect(w.text()).toContain('订单详情')
  await w.findAll('button').find(b => b.text() === '返回我的订单')!.trigger('click'); await flushPromises(); await vi.advanceTimersByTimeAsync(40)
  expect(w.findAll('.purchase-card')).toHaveLength(2); expect(w.text()).toContain('第二笔商品')
  expect(shopApi.purchases).toHaveBeenCalledTimes(2)
  expect(w.get('[aria-label="更多订单状态"]').element).toHaveProperty('value', 'PAID')
  expect(scroll).toHaveBeenLastCalledWith({ top: 480, behavior: 'auto' })
  vi.useRealTimers()
})

it('shows a geometry placeholder only for slow initial reads and clears it when the order arrives', async () => {
  vi.useFakeTimers(); let release!: (p: Purchase) => void
  vi.mocked(shopApi.purchase).mockReturnValue(new Promise(r => { release = r }))
  await open(); expect(w.find('[data-order-skeleton]').exists()).toBe(false)
  await vi.advanceTimersByTimeAsync(180); expect(w.find('[data-order-skeleton]').exists()).toBe(true)
  expect(w.find('[data-test="pay"]').exists()).toBe(false)
  release(item); await flushPromises(); expect(w.find('[data-order-skeleton]').exists()).toBe(false)
  expect(w.find('[data-test="pay"]').exists()).toBe(true)
  vi.useRealTimers()
})
