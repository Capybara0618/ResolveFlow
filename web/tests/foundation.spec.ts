import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type LoginResponse } from '../src/client'
import { managementApi, type ManagedProduct } from '../src/management-client'
import PlatformWorkspace from '../src/ui/PlatformWorkspace.vue'
import AdminProducts from '../src/ui/AdminProducts.vue'
import App from '../src/App.vue'

const platform: LoginResponse = { access_token: 't', role: 'PLATFORM_ADMIN', expires_in: 3600 }
const merchant: LoginResponse = { access_token: 't', role: 'MERCHANT_ADMIN', merchant_id: 'M-1001', expires_in: 3600 }
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); sessionStorage.clear(); window.history.replaceState(null, '', '/') })

describe('foundation management', () => {
  it('opens one merchant workspace and enters aftercare without personnel or claiming', async () => {
    const fetcher = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/auth/login')) return Promise.resolve(new Response(JSON.stringify({ ...merchant, single_operator: true })))
      if (url.endsWith('/admin/overview')) return Promise.resolve(new Response(JSON.stringify({ mine: 0, attention: 0, items: [] })))
      if (url.includes('/merchant/reviews')) return Promise.resolve(new Response(JSON.stringify({ items: [], summary: null, next_before: null })))
      return Promise.resolve(new Response(JSON.stringify({ items: [], page: { limit: 20 }, counts: { total: 0, public: 0, mine: 0, unclaimed: 0, stages: {} } })))
    })
    vi.stubGlobal('fetch', fetcher)
    const wrapper = mount(App)
    try {
      await wrapper.get('.login-panel').trigger('submit'); await flushPromises()
      expect(wrapper.find('[aria-label="商家工作台"]').exists()).toBe(true)
      expect(wrapper.findAll('.nav-link').map(link => link.text())).toEqual(['商家概览', '交易订单', '商品管理', '商品评价', '售后工单', '咨询核查', '售后政策'])
      await wrapper.findAll('.nav-link').find(link => link.text() === '商品评价')!.trigger('click'); await flushPromises()
      expect(wrapper.text()).toContain('本店暂无商品评价')
      expect(fetcher.mock.calls.some(([url]) => url.includes('/merchant/reviews'))).toBe(true)
      await wrapper.findAll('.nav-link').find(link => link.text() === '售后工单')!.trigger('click'); await flushPromises()
      expect(wrapper.find('#queue-panel').exists()).toBe(true)
      expect(wrapper.find('[aria-label="工单归属范围"]').exists()).toBe(false)
      expect((wrapper.get('.queue-filters select').element as HTMLSelectElement).value).toBe('ALL')
      expect(wrapper.text()).not.toContain('领取')
      expect(fetcher.mock.calls.some(([url]) => url.includes('/admin/accounts'))).toBe(false)
    } finally { wrapper.unmount() }
  })
  it('shows pending merchant sync and retries the original identity', async () => {
    vi.spyOn(managementApi, 'merchants').mockResolvedValue({ items: [{ merchant_id: 'M-4', name: '新商家', description: '介绍', enabled: false, desired_enabled: true, version: 1, sync_state: 'PENDING', policy_ready: false }] })
    vi.spyOn(managementApi, 'buyers').mockResolvedValue({ items: [] })
    const sync = vi.spyOn(managementApi, 'syncMerchant').mockResolvedValue({ merchant_id: 'M-4', name: '新商家', description: '介绍', enabled: true, desired_enabled: true, version: 1, sync_state: 'READY', policy_ready: false })
    const wrapper = mount(PlatformWorkspace, { props: { account: platform } }); await flushPromises()
    expect(wrapper.text()).toContain('售后政策待准备')
    await wrapper.findAll('button').find(b => b.text() === '重试同步')!.trigger('click'); await flushPromises()
    expect(sync).toHaveBeenCalledExactlyOnceWith('t', 'M-4')
    expect(wrapper.find('[aria-label="审核队列"]').exists()).toBe(false)
    wrapper.unmount()
  })
  it('edits a reactive product with its original version, converts yuan exactly and keeps draft on conflict', async () => {
    const product: ManagedProduct = { product_id: 'P-1', store_id: 'M-1001', name: '背包', description: '商品介绍', category: 'outdoor', asset_key: 'backpack', listed: true, version: 4, skus: [{ sku_id: 'S-1', variant: '蓝色', unit_amount: 12900, max_quantity: 10, listed: true, version: 2 }] }
    vi.spyOn(managementApi, 'products').mockResolvedValue({ items: [product], next_after: null })
    const save = vi.spyOn(managementApi, 'saveProduct').mockRejectedValue(new ApiError(409, 'VERSION_CONFLICT', '商品已更新'))
    const wrapper = mount(AdminProducts, { props: { account: merchant } }); await flushPromises()
    await wrapper.findAll('button').find(b => b.text() === '编辑')!.trigger('click')
    await wrapper.get('.foundation-sku-row input[inputmode="decimal"]').setValue('129.09')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(save).toHaveBeenCalledWith('t', 'P-1', expect.objectContaining({ expected_version: 4, skus: [expect.objectContaining({ sku_id: 'S-1', unit_amount: 12909 })] }))
    expect(wrapper.find('form').exists()).toBe(true)
    expect(wrapper.text()).toContain('商品已更新')
    wrapper.unmount()
  })
})
