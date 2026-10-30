import { reviewApi } from '../src/review-client'
import { accountApi } from '../src/account-client'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { beforeEach, afterEach, it, expect, vi } from 'vitest'
import MarketplaceWorkspace from '../src/ui/MarketplaceWorkspace.vue'
import { shopApi, type ShopProduct, type ShopDraft, type Purchase } from '../src/shop-client'
import { ApiError } from '../src/client'

const product: ShopProduct = { product_id: 'P-1001', store_id: 'M-1001', store_name: '松间数码', name: '无线降噪耳机', description: '日常聆听', category: 'electronics', asset_key: 'headphones', from_amount: 32900, currency: 'CNY', skus: [{ sku_id: 'black', variant: '黑色', unit_amount: 32900, max_quantity: 10, version: 1 }, { sku_id: 'silver', variant: '银色', unit_amount: 34900, max_quantity: 10, version: 2 }] }
const buyer = { access_token: 'buyer-token', role: 'CUSTOMER' as const, buyer_id: 'B-3001', expires_in: 3600 }
const draft: ShopDraft = { draft_id: 'draft-1', store_id: 'M-1001', store_name: '松间数码', product_id: 'P-1001', product_name: product.name, asset_key: 'headphones', sku_id: 'black', variant: '黑色', quantity: 2, unit_amount: 32900, total_amount: 65800, currency: 'CNY', status: 'WAITING_PAYMENT', created_at: '2026-10-03T04:00:00Z', expires_at: '2099-10-03T04:15:00Z' }
const purchase: Purchase = { purchase_id: 'draft:draft-1', draft_id: draft.draft_id, store_id: draft.store_id, store_name: draft.store_name, status: draft.status, total_amount: draft.total_amount, currency: 'CNY', created_at: draft.created_at, expires_at: draft.expires_at, paid_at: null, order_id: null, payment: null, lines: [{ line_id: null, sku: draft.sku_id, product_name: draft.product_name, variant: draft.variant, asset_key: draft.asset_key, quantity: draft.quantity, unit_amount: draft.unit_amount, line_amount: draft.total_amount }] }
Element.prototype.scrollIntoView = vi.fn()
let w: VueWrapper
beforeEach(() => {
  vi.spyOn(accountApi,'addresses').mockResolvedValue({items:[{address_id:'address-1',recipient:'测试收货人',phone:'13000000000',province:'测试省',city:'测试市',district:'测试区',detail:'测试路1号',is_default:true,version:1}]})
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
  await w.get('[aria-label="购买数量"]').setValue(3); expect(w.text()).not.toContain('已加入购物车')
})
it('retries unknown add with frozen request instead of reading and incrementing again', async () => {
  vi.spyOn(shopApi, 'cart').mockResolvedValue({ stores: [{ store_id: 'M-1001', store_name: '松间数码', revision: 0, currency: 'CNY', items: [] }] })
  vi.spyOn(shopApi, 'cartWrite').mockRejectedValueOnce(new TypeError('lost')).mockResolvedValueOnce({ store_id: 'M-1001', revision: 1 })
  await open(); await w.get('.cart-add').trigger('click'); await flushPromises()
  expect(w.get('.buy-button').attributes('disabled')).toBeDefined()
  expect(w.get('[aria-label="返回上一页"]').attributes('disabled')).toBeDefined()
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
  await w.get('.checkout-submit').trigger('click'); await flushPromises()
  expect(w.text()).toContain('原请求'); await w.get('.checkout-submit').trigger('click'); await flushPromises()
  const calls = vi.mocked(shopApi.draft).mock.calls
  expect(calls[0]).toEqual(calls[1]); expect(calls[0][1]).toEqual({ sku_id: 'black', quantity: 2, expected_sku_version: 1, shipping: {address_id:'address-1',expected_version:1} })
  expect(w.text()).toContain('待付款'); expect(w.text()).not.toContain('模拟付款完成于')
})
it('does not submit a stale quote after a price conflict', async () => {
  vi.mocked(shopApi.draft).mockRejectedValue(new ApiError(409, 'PRICE_CHANGED', 'changed'))
  await open(); await w.get('.buy-button').trigger('click'); await flushPromises()
  await w.get('.checkout-submit').trigger('click'); await flushPromises()
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
  expect(w.get('.gallery-main img').attributes('src')).toContain('headphones-black.webp')
  await w.findAll('fieldset button')[1].trigger('click')
  expect(w.get('.gallery-main img').attributes('src')).toContain('headphones-silver.webp')
  expect(w.get('.detail-price').text()).toContain('349.00')
})

it('exposes the current variant selection without issuing a purchase request', async () => {
  await open()
  expect(w.findAll('fieldset button').map(b => b.attributes('aria-pressed'))).toEqual(['true', 'false'])
  await w.findAll('fieldset button')[1].trigger('click')
  expect(w.findAll('fieldset button').map(b => b.attributes('aria-pressed'))).toEqual(['false', 'true'])
  expect(shopApi.quote).not.toHaveBeenCalled()
  expect(shopApi.draft).not.toHaveBeenCalled()
})

it('opens the product store from its labelled storefront link without quoting a purchase', async () => {
  window.history.replaceState(null, '', '/#/shop')
  w = mount(MarketplaceWorkspace, { props: { account: null } }); await flushPromises()
  await w.get('a[aria-label="进入松间数码店铺"]').trigger('click'); await flushPromises()
  expect(shopApi.store).toHaveBeenCalledWith('M-1001')
  expect(shopApi.products).toHaveBeenLastCalledWith({ store_id: 'M-1001' })
  expect(w.get('.store-profile').text()).toContain('松间数码')
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

it('requires an address before submitting a direct purchase',async()=>{vi.mocked(accountApi.addresses).mockResolvedValue({items:[]});await open();await w.get('.buy-button').trigger('click');await flushPromises();expect(w.get('.checkout-submit').attributes('disabled')).toBeDefined();await w.get('.checkout-submit').trigger('click');expect(shopApi.draft).not.toHaveBeenCalled()})

it('replaces rather than appends pages, keeps cursors for previous, and resets when filtering', async () => {
  window.history.replaceState(null, '', '/#/shop/search')
  vi.mocked(shopApi.products).mockResolvedValueOnce({ items: [product], next_after: 'cursor-1' }).mockResolvedValueOnce({ items: [{ ...product, product_id: 'page-two', name: '第二页商品' }], next_after: null }).mockResolvedValueOnce({ items: [product], next_after: 'cursor-1' }).mockResolvedValue({ items: [product], next_after: null })
  await open()
  expect(w.get('[aria-label="上一页"]').attributes('disabled')).toBeDefined()
  await w.get('[aria-label="下一页"]').trigger('click'); await flushPromises()
  expect(shopApi.products).toHaveBeenLastCalledWith({ after: 'cursor-1' })
  expect(w.findAll('.product-card')).toHaveLength(1); expect(w.text()).toContain('第二页商品'); expect(w.text()).toContain('第 2 页')
  expect(w.get('[aria-label="下一页"]').attributes('disabled')).toBeDefined()
  await w.get('[aria-label="上一页"]').trigger('click'); await flushPromises()
  expect(w.text()).toContain('第 1 页'); expect(shopApi.products).toHaveBeenLastCalledWith({})
  await w.get('.shop-categories button:nth-child(2)').trigger('click'); await flushPromises()
  expect(w.text()).toContain('第 1 页'); expect(shopApi.products).toHaveBeenLastCalledWith({ category: 'electronics' })
})

it('restores the catalogue cursor when returning from a product or refreshing', async () => {
  window.history.replaceState({ resolveflow_listing: { hash: '#/shop/search', index: 1, cursors: [undefined, 'page-2-cursor'] } }, '', '/#/shop/search')
  await open()
  expect(shopApi.products).toHaveBeenLastCalledWith({ after: 'page-2-cursor' })
  expect(w.text()).toContain('第 2 页')
})

it('falls back to the storefront from a direct entry and unwinds checkout to the product first', async () => {
  await open(); await w.get('.buy-button').trigger('click'); await flushPromises()
  expect(w.find('.checkout-panel').exists()).toBe(true)
  await w.get('[aria-label="返回上一页"]').trigger('click'); await flushPromises()
  expect(w.find('.shop-product-detail').exists()).toBe(true)
  await w.get('[aria-label="返回上一页"]').trigger('click'); await flushPromises()
  expect(window.location.hash).toBe('#/shop'); expect(w.get('[aria-label="返回上一页"]').attributes('disabled')).toBeDefined()
})

it('uses browser history for the preceding app page rather than pushing a fixed destination', async () => {
  const previous = vi.spyOn(window.history, 'back').mockImplementation(() => {})
  await open(); await w.get('a[href="#/shop/cart"]').trigger('click'); await flushPromises()
  await w.get('[aria-label="返回上一页"]').trigger('click'); expect(previous).toHaveBeenCalledOnce()
})

it('shows the server review summary beside the product and opens its review section without an extra request', async () => {
  const summary = { count: 3, average: 4.7, stars: [2, 1, 0, 0, 0] }
  const read = vi.spyOn(reviewApi, 'public').mockResolvedValue({ items: [], summary, next_before: null })
  await open()
  const entry = w.get('[aria-label="查看买家评价"]')
  expect(entry.text()).toContain('4.7')
  expect(entry.text()).toContain('3 条评价')
  await entry.trigger('click')
  expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' })
  expect(read).toHaveBeenCalledTimes(1)
  window.history.pushState({}, '', '/#/shop/products/P-2001')
  vi.mocked(shopApi.product).mockResolvedValue({ ...product, product_id: 'P-2001' })
  read.mockResolvedValue({ items: [], summary: { count: 0, average: null, stars: [0, 0, 0, 0, 0] }, next_before: null })
  window.dispatchEvent(new HashChangeEvent('hashchange')); await flushPromises()
  expect(w.find('[aria-label="查看买家评价"]').exists()).toBe(false)
  expect(w.text()).not.toContain('4.7 分')
})


it('returns to the same catalogue page and scroll without an empty refetch', async () => {
  vi.useFakeTimers()
  const scroll = vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
  vi.spyOn(window, 'scrollY', 'get').mockReturnValue(460)
  window.history.replaceState(null, '', '/#/shop/search?category=electronics')
  vi.mocked(shopApi.products).mockResolvedValueOnce({items:[product],next_after:'p2'}).mockResolvedValueOnce({items:[{...product,name:'第二页耳机'}],next_after:null})
  await open(); await w.get('[aria-label="下一页"]').trigger('click'); await flushPromises()
  await w.get('.product-image').trigger('click'); await flushPromises()
  window.history.back(); await vi.advanceTimersByTimeAsync(120); await flushPromises(); await vi.advanceTimersByTimeAsync(40)
  expect(w.text()).toContain('第 2 页'); expect(w.text()).toContain('第二页耳机')
  expect(shopApi.products).toHaveBeenCalledTimes(2)
  expect(scroll).toHaveBeenLastCalledWith({top:460,behavior:'auto'})
  vi.useRealTimers()
})

it('restores the chosen product variant and quantity after visiting the cart while re-reading its price', async () => {
  vi.useFakeTimers()
  vi.spyOn(shopApi,'cart').mockResolvedValue({stores:[]})
  await open(); await w.findAll('fieldset button')[1].trigger('click'); await w.get('[aria-label="购买数量"]').setValue(3)
  await w.get('a[href="#/shop/cart"]').trigger('click'); await flushPromises()
  window.history.back(); await vi.advanceTimersByTimeAsync(120); await flushPromises()
  expect(w.get<HTMLInputElement>('[aria-label="购买数量"]').element.value).toBe('3')
  expect(w.findAll('fieldset button')[1].attributes('aria-pressed')).toBe('true')
  expect(shopApi.product).toHaveBeenCalledTimes(2)
  expect(shopApi.quote).not.toHaveBeenCalled(); expect(shopApi.draft).not.toHaveBeenCalled()
  vi.useRealTimers()
})


it('keeps cart selections after opening a product and returning through history', async () => {
  vi.useFakeTimers()
  window.history.replaceState(null, '', '/#/shop/cart')
  vi.spyOn(shopApi,'cart').mockResolvedValue({stores:[{store_id:'M-1001',store_name:'松间数码',revision:1,currency:'CNY',items:product.skus.map(s=>({sku_id:s.sku_id,product_id:product.product_id,product_name:product.name,variant:s.variant,asset_key:product.asset_key,quantity:1,unit_amount:s.unit_amount,total_amount:s.unit_amount,max_quantity:10,sku_version:s.version,price_changed:false,availability:'AVAILABLE'}))}]})
  await open(); await w.findAll<HTMLInputElement>('.cart-row input[type=checkbox]')[1].setValue(false)
  await w.get('a[aria-label="查看无线降噪耳机"]').trigger('click'); await flushPromises()
  window.history.back(); await vi.advanceTimersByTimeAsync(120); await flushPromises()
  expect(w.findAll<HTMLInputElement>('.cart-row input[type=checkbox]').map(c=>c.element.checked)).toEqual([true,false])
  expect(shopApi.cart).toHaveBeenCalledTimes(2)
  vi.useRealTimers()
})

it('delays the initial catalogue skeleton and never flashes an empty search result', async () => {
  vi.useFakeTimers()
  window.history.replaceState(null, '', '/#/shop/search')
  let resolve!: (v:{items:ShopProduct[];next_after:null})=>void
  vi.mocked(shopApi.products).mockReturnValue(new Promise(r=>{resolve=r}))
  w = mount(MarketplaceWorkspace,{props:{account:buyer}}); await flushPromises()
  expect(w.find('.catalog-skeleton').exists()).toBe(false); expect(w.text()).not.toContain('没有找到商品')
  await vi.advanceTimersByTimeAsync(170)
  expect(w.find('.catalog-skeleton').exists()).toBe(true)
  resolve({items:[product],next_after:null}); await flushPromises()
  expect(w.find('.catalog-skeleton').exists()).toBe(false); expect(w.findAll('.product-card')).toHaveLength(1)
  vi.useRealTimers()
})


it('re-reads a catalogue snapshot after its five minute lifetime', async () => {
  vi.useFakeTimers()
  window.history.replaceState(null, '', '/#/shop/search')
  await open(); await w.get('.product-image').trigger('click'); await flushPromises()
  await vi.advanceTimersByTimeAsync(300001)
  window.history.back(); await vi.advanceTimersByTimeAsync(120); await flushPromises()
  expect(shopApi.products).toHaveBeenCalledTimes(2)
  vi.useRealTimers()
})

it('does not turn a failed catalogue read into a cached empty result', async () => {
  vi.useFakeTimers()
  window.history.replaceState(null, '', '/#/shop/search?query=耳机')
  vi.mocked(shopApi.products).mockRejectedValueOnce(new ApiError(503,'UNAVAILABLE','商品暂时无法读取'))
  await open(); expect(w.text()).toContain('商品暂时无法读取')
  await w.get('.shop-brand').trigger('click'); await flushPromises()
  window.history.back(); await vi.advanceTimersByTimeAsync(120); await flushPromises()
  expect(shopApi.products).toHaveBeenCalledTimes(3)
  expect(w.findAll('.product-card')).toHaveLength(1)
  vi.useRealTimers()
})


it('keeps the product quantity controls within the server SKU limit', async () => {
  await open()
  expect(w.get('[aria-label="减少购买数量"]').attributes('disabled')).toBeDefined()
  await w.get('[aria-label="购买数量"]').setValue(10)
  expect(w.get('[aria-label="增加购买数量"]').attributes('disabled')).toBeDefined()
  await w.get('[aria-label="减少购买数量"]').trigger('click')
  expect(w.get<HTMLInputElement>('[aria-label="购买数量"]').element.value).toBe('9')
  expect(shopApi.quote).not.toHaveBeenCalled()
})
