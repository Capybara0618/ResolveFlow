import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AdminProducts from '../src/ui/AdminProducts.vue'
import { managementApi, type ManagedProduct } from '../src/management-client'
const account = { access_token: 'merchant-token', role: 'MERCHANT_ADMIN' as const, merchant_id: 'M-1001', expires_in: 3600 }
afterEach(() => vi.restoreAllMocks())
it('keeps one page of products and refreshes the current opaque cursor', async () => {
  const row: ManagedProduct = { product_id: 'P1', store_id: 'M-1001', name: '第一页商品', description: '', category: 'home', asset_key: 'lamp', listed: true, version: 1, skus: [{ sku_id: 's1', variant: '白色', unit_amount: 1000, max_quantity: 10, listed: true, version: 1 }] }
  const read = vi.spyOn(managementApi, 'products').mockResolvedValueOnce({ items: [row], next_after: 'opaque' })
    .mockResolvedValueOnce({ items: [{ ...row, product_id: 'P2', name: '第二页商品' }], next_after: null })
    .mockResolvedValue({ items: [row], next_after: 'opaque' })
  const w = mount(AdminProducts, { props: { account } }); await flushPromises()
  await w.findAll('button').find(b => b.text() === '下一页')!.trigger('click'); await flushPromises()
  expect(read).toHaveBeenLastCalledWith('merchant-token', 'opaque')
  expect(w.findAll('tbody tr')).toHaveLength(1); expect(w.text()).not.toContain('第一页商品')
  await w.findAll('button').find(b => b.text() === '刷新')!.trigger('click'); await flushPromises()
  expect(read).toHaveBeenLastCalledWith('merchant-token', 'opaque'); expect(w.text()).toContain('第 2 页')
  w.unmount()
})
