import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type LoginResponse } from '../src/client'
import { managementApi, type ManagedProduct } from '../src/management-client'
import PlatformWorkspace from '../src/ui/PlatformWorkspace.vue'
import AdminProducts from '../src/ui/AdminProducts.vue'
import App from '../src/App.vue'

const platform: LoginResponse = { access_token: 't', role: 'PLATFORM_ADMIN', expires_in: 3600 }
const merchant: LoginResponse = { access_token: 't', role: 'MERCHANT_ADMIN', merchant_id: 'M-1001', expires_in: 3600 }

it('allows platform navigation during a read and ignores failure from the departed page', async () => {
  let reject!: (reason:unknown)=>void
  vi.spyOn(managementApi,'merchants').mockImplementationOnce(()=>new Promise((_resolve,fail)=>{reject=fail}))
  vi.spyOn(managementApi,'buyers').mockResolvedValue({items:[{username:'current',display_name:'当前买家',enabled:true,version:1}]})
  const w=mount(PlatformWorkspace,{props:{account:platform}})
  try {
    await flushPromises()
    const buyers=w.findAll('.nav-link').find(b=>b.text()==='买家账号')!
    expect(buyers.attributes('disabled')).toBeUndefined()
    await buyers.trigger('click'); await flushPromises()
    reject(new Error('旧页面读取失败')); await flushPromises()
    expect(w.text()).toContain('当前买家')
    expect(w.text()).not.toContain('旧页面读取失败')
    expect(w.get('main').attributes('data-page-loading')).toBe('false')
  } finally { w.unmount() }
})

it('does not mark a merchant product read as a blocking business write', async () => {
  let resolve!: (value:{items:ManagedProduct[];next_after:null})=>void
  vi.spyOn(managementApi,'products').mockImplementationOnce(()=>new Promise(done=>{resolve=done}))
  const w=mount(AdminProducts,{props:{account:merchant}})
  try {
    await flushPromises()
    expect(w.emitted('working')).toBeUndefined()
    resolve({items:[],next_after:null}); await flushPromises()
    expect(w.emitted('working')).toBeUndefined()
  } finally { w.unmount() }
})

it('discards a departed listing error when navigating to run records without another listing read', async () => {
  let reject!: (reason:unknown)=>void
  vi.spyOn(managementApi,'merchants').mockImplementationOnce(()=>new Promise((_resolve,fail)=>{reject=fail}))
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({items:[],next_before:null}))))
  const w=mount(PlatformWorkspace,{props:{account:platform}})
  try {
    await flushPromises()
    await w.findAll('.nav-link').find(b=>b.text()==='客服运行记录')!.trigger('click'); await flushPromises()
    reject(new ApiError(401,'UNAUTHENTICATED','已经离开的商家列表错误')); await flushPromises()
    expect(w.emitted('expired')).toBeUndefined()
    await w.findAll('.nav-link').find(b=>b.text()==='买家账号')!.trigger('click'); await flushPromises()
    expect(w.text()).not.toContain('已经离开的商家列表错误')
  } finally { w.unmount() }
})

it('keeps navigation blocked while a platform write is being confirmed', async () => {
  const row={merchant_id:'M-pending',name:'待同步店铺',description:'介绍',enabled:false,desired_enabled:true,version:1,sync_state:'PENDING' as const,policy_ready:false}
  vi.spyOn(managementApi,'merchants').mockResolvedValue({items:[row]})
  let release!: (value:typeof row)=>void
  vi.spyOn(managementApi,'syncMerchant').mockImplementationOnce(()=>new Promise(resolve=>{release=resolve}))
  const w=mount(PlatformWorkspace,{props:{account:platform}})
  try {
    await flushPromises()
    await w.findAll('button').find(b=>b.text()==='重试同步')!.trigger('click'); await flushPromises()
    expect(w.findAll('.nav-link').every(b=>b.attributes('disabled')!==undefined)).toBe(true)
    release(row); await flushPromises()
    expect(w.findAll('.nav-link').every(b=>b.attributes('disabled')===undefined)).toBe(true)
  } finally { w.unmount() }
})
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
      expect(wrapper.findAll('.nav-link').map(link => link.text())).toEqual(['商家概览', '交易订单', '商品管理', '商品评价', '售后工单', '咨询核查', '退款规则'])
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


it('pages buyers on the server and keeps the current page when refreshing or a read fails', async () => {
  vi.spyOn(managementApi,'merchants').mockResolvedValue({items:[],next_after:null})
  const buyer={username:'first',display_name:'第一页',enabled:true,version:1}
  const list=vi.spyOn(managementApi,'buyers').mockResolvedValueOnce({items:[buyer],next_after:'after-first'})
    .mockResolvedValueOnce({items:[{...buyer,username:'second',display_name:'第二页'}],next_after:null}).mockRejectedValueOnce(new Error('lost'))
  const w=mount(PlatformWorkspace,{props:{account:platform}});await flushPromises()
  try {
    await w.findAll('button').find(b=>b.text()==='买家账号')!.trigger('click');await flushPromises()
    await w.findAll('button').find(b=>b.text()==='下一页')!.trigger('click');await flushPromises()
    expect(list).toHaveBeenLastCalledWith('t',{after:'after-first',query:''})
    expect(w.findAll('tbody tr')).toHaveLength(1);expect(w.text()).toContain('第 2 页')
    await w.findAll('button').find(b=>b.text()==='刷新')!.trigger('click');await flushPromises()
    expect(list).toHaveBeenLastCalledWith('t',{after:'after-first',query:''})
    expect(w.text()).toContain('第二页');expect(w.text()).toContain('第 2 页');expect(w.find('[role="alert"]').exists()).toBe(true)
  } finally {w.unmount()}
})
