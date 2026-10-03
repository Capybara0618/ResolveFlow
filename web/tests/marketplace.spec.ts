import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { beforeEach, afterEach, it, expect, vi } from 'vitest'
import MarketplaceWorkspace from '../src/ui/MarketplaceWorkspace.vue'
import { shopApi, type ShopProduct, type ShopDraft } from '../src/shop-client'
import { ApiError } from '../src/client'

const product: ShopProduct = { product_id: 'P-1001', store_id: 'M-1001', store_name: '松间数码', name: '无线降噪耳机', description: '日常聆听', category: 'electronics', asset_key: 'headphones', from_amount: 32900, currency: 'CNY', skus: [{ sku_id: 'black', variant: '黑色', unit_amount: 32900, max_quantity: 10, version: 1 }, { sku_id: 'silver', variant: '银色', unit_amount: 34900, max_quantity: 10, version: 2 }] }
const buyer = { access_token: 'buyer-token', role: 'CUSTOMER' as const, buyer_id: 'B-3001', expires_in: 3600 }
const draft: ShopDraft = { draft_id: 'draft-1', store_id: 'M-1001', store_name: '松间数码', product_id: 'P-1001', product_name: product.name, asset_key: 'headphones', sku_id: 'black', variant: '黑色', quantity: 2, unit_amount: 32900, total_amount: 65800, currency: 'CNY', status: 'WAITING_PAYMENT', created_at: '2026-10-03T04:00:00Z', expires_at: '2026-10-03T04:15:00Z' }
let w: VueWrapper
beforeEach(() => {
  window.history.replaceState(null, '', '/#/shop/products/P-1001')
  vi.spyOn(shopApi, 'product').mockResolvedValue(product)
  vi.spyOn(shopApi, 'products').mockResolvedValue({ items: [product], next_after: null })
  vi.spyOn(shopApi, 'stores').mockResolvedValue([{ store_id: 'M-1001', name: '松间数码', description: '日常数码' }])
  vi.spyOn(shopApi, 'quote').mockResolvedValue({ product, sku: product.skus[0], quantity: 2, total_amount: 65800, currency: 'CNY' })
  vi.spyOn(shopApi, 'draft').mockResolvedValue(draft)
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
  expect(w.text()).toContain('尚未付款'); expect(w.text()).not.toContain('支付成功')
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
  vi.spyOn(shopApi, 'readDraft').mockResolvedValue({ ...draft, status: 'EXPIRED' })
  await open(); expect(w.text()).toContain('已到期'); expect(w.text()).not.toContain('申请退款')
})
it('drops a late product response after navigation', async () => {
  let resolve!: (p: ShopProduct) => void
  vi.mocked(shopApi.product).mockReturnValue(new Promise(r => { resolve = r }))
  w = mount(MarketplaceWorkspace, { props: { account: buyer } })
  await w.get('.shop-nav a').trigger('click'); await flushPromises(); resolve(product); await flushPromises()
  expect(w.find('.shop-product-detail').exists()).toBe(false); expect(w.find('.shop-grid').exists()).toBe(true)
})
