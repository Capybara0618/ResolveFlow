import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { beforeEach, afterEach, it, expect, vi } from 'vitest'
import CartWorkspace from '../src/ui/CartWorkspace.vue'
import { shopApi, type CartGroup, type CartQuote, type Purchase } from '../src/shop-client'
import { ApiError } from '../src/client'
import { readCartPending, saveCartPending } from '../src/cart-pending'

const account = { access_token: 'buyer-token', role: 'CUSTOMER' as const, buyer_id: 'B-3001', expires_in: 3600 }
const item = { sku_id: 'ear', product_id: 'P1', product_name: '无线降噪耳机', variant: '黑色', asset_key: 'headphones', quantity: 1, unit_amount: 32900, total_amount: 32900, max_quantity: 10, sku_version: 1, price_changed: false, availability: 'AVAILABLE' as const }
const groups: CartGroup[] = [{ store_id: 'M-1001', store_name: '松间数码', revision: 2, currency: 'CNY', items: [item, { ...item, sku_id: 'key', product_id: 'P2', product_name: '机械键盘', asset_key: 'keyboard', variant: '白色', quantity: 2, unit_amount: 19900, total_amount: 39800 }] }, { store_id: 'M-1002', store_name: '拾光家居', revision: 2, currency: 'CNY', items: [{ ...item, sku_id: 'lamp', product_id: 'P3', product_name: '桌面台灯', asset_key: 'lamp', unit_amount: 12900, total_amount: 12900 }, { ...item, sku_id: 'cup', product_id: 'P4', product_name: '保温杯', asset_key: 'cup', unit_amount: 8900, total_amount: 8900 }] }]
const quote: CartQuote = { store_id: 'M-1001', store_name: '松间数码', revision: 2, currency: 'CNY', lines: groups[0].items.map(i => ({ sku_id: i.sku_id, product_id: i.product_id, product_name: i.product_name, variant: i.variant, asset_key: i.asset_key, category: 'electronics', quantity: i.quantity, unit_amount: i.unit_amount, line_amount: i.total_amount, sku_version: i.sku_version })), total_amount: 72700 }
const purchase: Purchase = { purchase_id: 'draft:owned', draft_id: 'owned', store_id: 'M-1001', store_name: '松间数码', status: 'WAITING_PAYMENT', total_amount: 72700, currency: 'CNY', created_at: '2026-10-03T04:00:00Z', expires_at: '2099-10-03T04:15:00Z', paid_at: null, order_id: null, lines: quote.lines.map(i => ({ ...i, sku: i.sku_id, line_id: null })), payment: null }
let w: VueWrapper
beforeEach(() => {
  sessionStorage.clear()
  vi.spyOn(shopApi, 'cart').mockResolvedValue({ stores: structuredClone(groups) })
  vi.spyOn(shopApi, 'cartWrite').mockResolvedValue({ store_id: 'M-1001', revision: 3 })
  vi.spyOn(shopApi, 'cartQuote').mockResolvedValue(structuredClone(quote))
  vi.spyOn(shopApi, 'cartDraft').mockResolvedValue(purchase)
})
afterEach(() => { w?.unmount(); vi.restoreAllMocks() })
async function open() { w = mount(CartWorkspace, { props: { account } }); await flushPromises() }
async function confirm() { await open(); await w.findAll('.cart-checkout')[0].trigger('click'); await flushPromises() }
it('groups stores with explicit unit quantity and subtotal columns and submits only selected store rows', async () => {
  vi.mocked(shopApi.cartQuote).mockResolvedValue({ ...quote, lines: quote.lines.slice(0, 1), total_amount: 32900 })
  await open(); expect(w.text()).toContain('727.00'); expect(w.text()).toContain('218.00')
  await w.get('[aria-label="选择机械键盘"]').setValue(false)
  await w.findAll('.cart-checkout')[0].trigger('click'); await flushPromises()
  expect(shopApi.cartQuote).toHaveBeenCalledWith('buyer-token', 'M-1001', 2, ['ear'])
  expect(w.findAll('.checkout-line')).toHaveLength(1)
  await w.get('.cart-submit').trigger('click'); await flushPromises()
  expect(shopApi.cartDraft).toHaveBeenCalledWith('buyer-token', 'M-1001', { expected_revision: 2, lines: [{ sku_id: 'ear', quantity: 1, expected_sku_version: 1 }] }, expect.any(String))
  expect(w.emitted('navigate')?.[0]).toEqual(['#/shop/drafts/owned'])
  expect(readCartPending('B-3001')).toBeNull()
})
it('sets absolute quantity with original revision and disables competing writes while outcome is unknown', async () => {
  vi.mocked(shopApi.cartWrite).mockRejectedValueOnce(new TypeError('connection lost'))
  await open(); await w.get('[aria-label="增加无线降噪耳机数量"]').trigger('click'); await flushPromises()
  const original = vi.mocked(shopApi.cartWrite).mock.calls[0]
  expect(original.slice(0, 3)).toEqual(['buyer-token', 'M-1001', { sku_id: 'ear', quantity: 2, expected_revision: 2, expected_sku_version: 1 }])
  expect(w.get('[aria-label="增加机械键盘数量"]').attributes('disabled')).toBeDefined()
  expect(w.findAll('.cart-checkout')[1].attributes('disabled')).toBeDefined()
  await w.get('.cart-recovery button').trigger('click'); await flushPromises()
  expect(vi.mocked(shopApi.cartWrite).mock.calls[1]).toEqual(original)
})
it('restores uncertain cart mutation after remount without automatic writes or a new key', async () => {
  vi.mocked(shopApi.cartWrite).mockRejectedValueOnce(new TypeError('lost'))
  await open(); await w.get('[aria-label="移除无线降噪耳机"]').trigger('click'); await flushPromises()
  const original = vi.mocked(shopApi.cartWrite).mock.calls[0]; w.unmount(); await open()
  expect(shopApi.cartWrite).toHaveBeenCalledTimes(1); expect(w.text()).toContain('结果待确认')
  await w.get('.cart-recovery button').trigger('click'); await flushPromises()
  expect(vi.mocked(shopApi.cartWrite).mock.calls[1]).toEqual(original)
  expect(original[2].expected_sku_version).toBeNull()
})
it('restores original multiline draft after remount and blocks a replacement submission', async () => {
  vi.mocked(shopApi.cartDraft).mockRejectedValueOnce(new TypeError('lost'))
  await confirm(); await w.get('.cart-submit').trigger('click'); await flushPromises()
  const original = vi.mocked(shopApi.cartDraft).mock.calls[0]; w.unmount(); await open()
  expect(w.findAll('.checkout-line')).toHaveLength(2); expect(w.find('.cart-submit').exists()).toBe(false)
  expect(shopApi.cartDraft).toHaveBeenCalledTimes(1)
  await w.get('.cart-recovery button').trigger('click'); await flushPromises()
  expect(vi.mocked(shopApi.cartDraft).mock.calls[1]).toEqual(original)
})
it('price conflict removes stale confirmation and requires a fresh quote instead of resubmission', async () => {
  vi.mocked(shopApi.cartDraft).mockRejectedValue(new ApiError(409, 'PRICE_CHANGED', '商品已更新，请重新确认报价'))
  await confirm(); await w.get('.cart-submit').trigger('click'); await flushPromises()
  expect(w.text()).toContain('重新确认报价'); expect(w.find('.checkout-panel').exists()).toBe(false)
  expect(w.find('.cart-recovery').exists()).toBe(false); expect(readCartPending('B-3001')).toBeNull()
  expect(shopApi.cartQuote).toHaveBeenCalledTimes(1)
})
it('delisted cart rows stay visible and removable but cannot be selected or incremented', async () => {
  const unavailable = structuredClone(groups); unavailable[0].items[0].availability = 'DELISTED'
  vi.mocked(shopApi.cart).mockResolvedValue({ stores: unavailable })
  await open(); expect(w.text()).toContain('商品已下架')
  expect(w.get('[aria-label="选择无线降噪耳机"]').attributes('disabled')).toBeDefined()
  await w.get('[aria-label="移除无线降噪耳机"]').trigger('click'); await flushPromises()
  expect(vi.mocked(shopApi.cartWrite).mock.calls[0][2]).toEqual({ sku_id: 'ear', quantity: 0, expected_revision: 2, expected_sku_version: null })
})
it('failed complete read never claims an empty cart and can be refreshed', async () => {
  vi.mocked(shopApi.cart).mockRejectedValueOnce(new ApiError(503, 'UNAVAILABLE', '店铺服务暂不可用'))
  await open(); expect(w.text()).toContain('暂不可用'); expect(w.text()).not.toContain('还没有商品')
  await w.get('.cart-heading button').trigger('click'); await flushPromises(); expect(w.findAll('.cart-store')).toHaveLength(2)
})
it('login expiry requests logout and leaves uncertain request recoverable for the same buyer', async () => {
  vi.mocked(shopApi.cartWrite).mockRejectedValue(new ApiError(401, 'UNAUTHENTICATED', 'expired'))
  await open(); await w.get('[aria-label="移除无线降噪耳机"]').trigger('click'); await flushPromises()
  expect(w.emitted('expired')).toHaveLength(1); expect(readCartPending('B-3001')).not.toBeNull()
})
it('different buyer cannot restore or clear another buyers pending request', async () => {
  saveCartPending('other-buyer', { kind: 'mutation', store: 'M-1001', key: 'original', request: { sku_id: 'ear', quantity: 1, expected_revision: 0, expected_sku_version: 1 } })
  await open(); expect(w.find('.cart-recovery').exists()).toBe(false)
  expect(readCartPending('other-buyer')?.key).toBe('original')
})
it('late quote after unmount cannot submit, navigate or persist a draft', async () => {
  let resolve!: (q: CartQuote) => void
  vi.mocked(shopApi.cartQuote).mockReturnValue(new Promise(r => { resolve = r }))
  await open(); await w.findAll('.cart-checkout')[0].trigger('click'); w.unmount(); resolve(quote); await flushPromises()
  expect(shopApi.cartDraft).not.toHaveBeenCalled(); expect(w.emitted('navigate')).toBeUndefined(); expect(readCartPending('B-3001')).toBeNull()
})
