import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { beforeEach, afterEach, it, expect, vi } from 'vitest'
import MarketplaceWorkspace from '../src/ui/MarketplaceWorkspace.vue'
import { shopApi, type ShopProduct, type ShopDraft, type Purchase } from '../src/shop-client'
import { ApiError } from '../src/client'

const product: ShopProduct = { product_id: 'P-1001', store_id: 'M-1001', store_name: '松间数码', name: '无线降噪耳机', description: '日常聆听', category: 'electronics', asset_key: 'headphones', from_amount: 32900, currency: 'CNY', skus: [{ sku_id: 'black', variant: '黑色', unit_amount: 32900, max_quantity: 10, version: 1 }, { sku_id: 'silver', variant: '银色', unit_amount: 34900, max_quantity: 10, version: 2 }] }
const buyer = { access_token: 'buyer-token', role: 'CUSTOMER' as const, buyer_id: 'B-3001', expires_in: 3600 }
const draft: ShopDraft = { draft_id: 'draft-1', store_id: 'M-1001', store_name: '松间数码', product_id: 'P-1001', product_name: product.name, asset_key: 'headphones', sku_id: 'black', variant: '黑色', quantity: 2, unit_amount: 32900, total_amount: 65800, currency: 'CNY', status: 'WAITING_PAYMENT', created_at: '2026-10-03T04:00:00Z', expires_at: '2099-10-03T04:15:00Z' }
const purchase: Purchase = { purchase_id: 'draft:draft-1', draft_id: draft.draft_id, store_id: draft.store_id, store_name: draft.store_name, status: draft.status, total_amount: draft.total_amount, currency: 'CNY', created_at: draft.created_at, expires_at: draft.expires_at, paid_at: null, order_id: null, payment: null, lines: [{ line_id: null, sku: draft.sku_id, product_name: draft.product_name, variant: draft.variant, asset_key: draft.asset_key, quantity: draft.quantity, unit_amount: draft.unit_amount, line_amount: draft.total_amount }] }
let w: VueWrapper
beforeEach(() => {
  sessionStorage.clear()
  window.history.replaceState(null, '', '/#/shop/products/P-1001')
  vi.spyOn(shopApi, 'product').mockResolvedValue(product)
  vi.spyOn(shopApi, 'products').mockResolvedValue({ items: [product], next_after: null })
  vi.spyOn(shopApi, 'stores').mockResolvedValue([{ store_id: 'M-1001', name: '松间数码', description: '日常数码' }])
  vi.spyOn(shopApi, 'store').mockResolvedValue({ store_id: 'M-1001', name: '松间数码', description: '日常数码' })
  vi.spyOn(shopApi, 'quote').mockResolvedValue({ product, sku: product.skus[0], quantity: 2, total_amount: 65800, currency: 'CNY' })
  vi.spyOn(shopApi, 'draft').mockResolvedValue(draft)
  vi.spyOn(shopApi, 'purchase').mockResolvedValue(purchase)
})
it('adds selected quantity to the current cart through an absolute versioned request', async () => {
  vi.spyOn(shopApi, 'cart').mockResolvedValue({ stores: [{ store_id: 'M-1001', store_name: '松间数码', revision: 7, currency: 'CNY', items: [{ sku_id: 'black', product_id: 'P-1001', product_name: product.name, variant: '黑色', asset_key: 'headphones', quantity: 1, unit_amount: 32900, total_amount: 32900, max_quantity: 10, sku_version: 1, price_changed: false, availability: 'AVAILABLE' }] }] })
  vi.spyOn(shopApi, 'cartWrite').mockResolvedValue({ store_id: 'M-1001', revision: 8 })
  await open(); await w.get('[aria-label="购买数量"]').setValue(2); await w.get('.cart-add').trigger('click'); await flushPromises()
  expect(shopApi.cartWrite).toHaveBeenCalledWith('buyer-token', 'M-1001', { sku_id: 'black', quantity: 3, expected_revision: 7, expected_sku_version: 1 }, expect.any(String))
  expect(w.text()).toContain('已加入购物车')
})
it('retries unknown add with frozen request instead of reading and incrementing again', async () => {
  vi.spyOn(shopApi, 'cart').mockResolvedValue({ stores: [{ store_id: 'M-1001', store_name: '松间数码', revision: 0, currency: 'CNY', items: [] }] })
  vi.spyOn(shopApi, 'cartWrite').mockRejectedValueOnce(new TypeError('lost')).mockResolvedValueOnce({ store_id: 'M-1001', revision: 1 })
  await open(); await w.get('.cart-add').trigger('click'); await flushPromises()
  expect(w.get('.buy-button').attributes('disabled')).toBeDefined()
  await w.get('.cart-add').trigger('click'); await flushPromises()
  expect(vi.mocked(shopApi.cartWrite).mock.calls[0]).toEqual(vi.mocked(shopApi.cartWrite).mock.calls[1])
  expect(shopApi.cart).toHaveBeenCalledTimes(1)
})
afterEach(() => { w?.unmount(); vi.restoreAllMocks() })
async function open() { w = mount(MarketplaceWorkspace, { props: { account: buyer } }); await flushPromises() }
it('uses selected variant and bounded quantity for a server quote', async () => {
  await open(); await w.get('[aria-label="购买数量"]').setValue(2)
  await w.findAll('fieldset button')[1].trigger('click'); await w.get('.buy-button').trigger('click'); await flushPromises()
  expect(shopApi.quote).toHaveBeenCalledWith('silver', 2); expect(w.text()).toContain('658.00')
})
it('retries an uncertain creation with the exact same key and immutable payload', async () => {
  vi.mocked(shopApi.draft).mockRejectedValueOnce(new TypeError('connection lost')).mockResolvedValueOnce(draft)
  await open(); await w.get('.buy-button').trigger('click'); await flushPromises()
  await w.get('.checkout-panel > button').trigger('click'); await flushPromises()
  expect(w.text()).toContain('原请求'); await w.get('.checkout-panel > button').trigger('click'); await flushPromises()
  const calls = vi.mocked(shopApi.draft).mock.calls
  expect(calls[0]).toEqual(calls[1]); expect(calls[0][1]).toEqual({ sku_id: 'black', quantity: 2, expected_sku_version: 1 })
  expect(w.text()).toContain('待付款'); expect(w.text()).not.toContain('模拟付款完成于')
})
it('does not submit a stale quote after a price conflict', async () => {
  vi.mocked(shopApi.draft).mockRejectedValue(new ApiError(409, 'PRICE_CHANGED', 'changed'))
  await open(); await w.get('.buy-button').trigger('click'); await flushPromises()
  await w.get('.checkout-panel > button').trigger('click'); await flushPromises()
  expect(w.text()).toContain('重新读取商品'); expect(w.find('.checkout-panel').exists()).toBe(false)
})
it('allows anonymous browsing but asks for login before quoting a purchase', async () => {
  w = mount(MarketplaceWorkspace, { props: { account: null } }); await flushPromises()
  await w.get('.buy-button').trigger('click'); expect(w.emitted('login')).toHaveLength(1)
  expect(shopApi.quote).not.toHaveBeenCalled()
})
it('shows expiry from the server without a payment or aftercare action', async () => {
  window.history.replaceState(null, '', '/#/shop/drafts/draft-1')
  vi.mocked(shopApi.purchase).mockResolvedValue({ ...purchase, status: 'EXPIRED' })
  await open(); expect(w.text()).toContain('已到期'); expect(w.text()).not.toContain('申请退款')
})
it('drops a late product response after navigation', async () => {
  let resolve!: (p: ShopProduct) => void
  vi.mocked(shopApi.product).mockReturnValue(new Promise(r => { resolve = r }))
  w = mount(MarketplaceWorkspace, { props: { account: buyer } })
  await w.get('.shop-nav a').trigger('click'); await flushPromises(); resolve(product); await flushPromises()
  expect(w.find('.shop-product-detail').exists()).toBe(false); expect(w.find('.shop-grid').exists()).toBe(true)
})

it('shows the selected SKU image and price in the actual product detail', async () => {
  await open()
  expect(w.get('.detail-image img').attributes('src')).toContain('headphones-black.webp')
  await w.findAll('fieldset button')[1].trigger('click')
  expect(w.get('.detail-image img').attributes('src')).toContain('headphones-silver.webp')
  expect(w.get('.detail-price').text()).toContain('349.00')
})

it('opens the product store from its labelled storefront link without quoting a purchase', async () => {
  window.history.replaceState(null, '', '/#/shop')
  w = mount(MarketplaceWorkspace, { props: { account: null } }); await flushPromises()
  await w.get('a[aria-label="进入松间数码店铺"]').trigger('click'); await flushPromises()
  expect(shopApi.store).toHaveBeenCalledWith('M-1001')
  expect(shopApi.products).toHaveBeenLastCalledWith({ store_id: 'M-1001' })
  expect(w.get('.shop-store-banner').text()).toContain('松间数码')
  expect(shopApi.quote).not.toHaveBeenCalled()
})

it('preserves query and category when entering a store and returning to all stores', async () => {
  window.history.replaceState(null, '', '/#/shop/search?query=耳机&category=electronics')
  await open()
  await w.get('select[aria-label="选择店铺"]').setValue('M-1001'); await flushPromises()
  expect(shopApi.products).toHaveBeenLastCalledWith({ store_id: 'M-1001', query: '耳机', category: 'electronics' })
  await w.get('select[aria-label="选择店铺"]').setValue(''); await flushPromises()
  expect(shopApi.products).toHaveBeenLastCalledWith({ query: '耳机', category: 'electronics' })
  expect(w.get<HTMLInputElement>('input[aria-label="搜索商品"]').element.value).toBe('耳机')
})

it('keeps buyer logout available in the account menu', async () => {
  await open()
  await w.get('.shop-account button').trigger('click')
  expect(w.emitted('logout')).toHaveLength(1)
})

it('requires login when an anonymous visitor opens a private buyer route', async () => {
  window.history.replaceState(null, '', '/#/shop')
  w = mount(MarketplaceWorkspace, { props: { account: null } }); await flushPromises()
  await w.get('a[href="#/shop/orders"]').trigger('click'); await flushPromises()
  expect(w.emitted('login')).toHaveLength(1)
  expect(shopApi.purchase).not.toHaveBeenCalled()
  expect(shopApi.quote).not.toHaveBeenCalled()
})
