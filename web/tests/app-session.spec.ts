import { defineComponent, onMounted } from 'vue'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import App from '../src/App.vue'
import MarketplaceWorkspace from '../src/ui/MarketplaceWorkspace.vue'
import { readTabSession, saveTabSession } from '../src/tab-session'

let wrapper: VueWrapper | undefined
afterEach(() => { wrapper?.unmount(); sessionStorage.clear(); vi.unstubAllGlobals(); window.history.replaceState(null, '', '/') })
const stub = { props: ['account'], template: '<p data-session-buyer>{{ account?.buyer_id }}</p>' }

it('refresh restores the same buyer and private route without submitting login or business commands again', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    access_token: 'buyer-token', role: 'CUSTOMER', buyer_id: 'B-1', expires_in: 3600,
  })))
  vi.stubGlobal('fetch', fetcher)
  wrapper = mount(App, { global: { stubs: { MarketplaceWorkspace: stub } } })
  await wrapper.get('.login-panel').trigger('submit'); await flushPromises()
  window.history.replaceState(null, '', '#/shop/support')
  wrapper.unmount(); fetcher.mockClear()
  wrapper = mount(App, { global: { stubs: { MarketplaceWorkspace: stub } } }); await flushPromises()
  expect(wrapper.get('[data-session-buyer]').text()).toBe('B-1')
  expect(window.location.hash).toBe('#/shop/support')
  expect(fetcher).not.toHaveBeenCalled()
  wrapper.findComponent(MarketplaceWorkspace).vm.$emit('logout'); await flushPromises()
  expect(readTabSession()).toBeNull()
  expect(window.location.hash).toBe('')
})

it('a restored token rejected by the backend returns to login and clears the stored session', async () => {
  saveTabSession({ access_token: 'revoked-token', role: 'REVIEWER', merchant_id: 'M-1', expires_in: 3600 })
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => new Response(JSON.stringify({ code: 'UNAUTHENTICATED' }), { status: 401 })))
  wrapper = mount(App); await flushPromises()
  expect(wrapper.find('.login-panel').exists()).toBe(true)
  expect(readTabSession()).toBeNull()
})

it('returns a renamed buyer to login with a success notice and no retained password', async () => {
  saveTabSession({ access_token: 'buyer-token', role: 'CUSTOMER', buyer_id: 'B-1', expires_in: 3600 })
  wrapper = mount(App, { global: { stubs: { MarketplaceWorkspace: stub } } }); await flushPromises()
  wrapper.findComponent(MarketplaceWorkspace).vm.$emit('reauthenticate', 'renamed-buyer'); await flushPromises()
  expect(readTabSession()).toBeNull()
  expect(wrapper.get<HTMLInputElement>('input[name="username"]').element.value).toBe('renamed-buyer')
  expect(wrapper.get<HTMLInputElement>('input[name="password"]').element.value).toBe('')
  expect(wrapper.get('[role="status"]').text()).toBe('账号已修改，请使用新账号登录。')
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: 'UNAUTHENTICATED', message: '账号或密码不正确' }), { status: 401 })))
  await wrapper.get('.login-panel').trigger('submit'); await flushPromises()
  expect(wrapper.find('[role="status"]').exists()).toBe(false)
  expect(wrapper.get('[role="alert"]').text()).toContain('账号或密码不正确')
})

it('restores buyer identity before a private page can request visitor login and replace its history', async () => {
  saveTabSession({ access_token: 'buyer-token', role: 'CUSTOMER', buyer_id: 'B-1', expires_in: 3600 })
  window.history.replaceState({ resolveflow_buyer_navigation: { owner: 'B-1', depth: 2 } }, '', '#/shop/cart')
  const pages = defineComponent({ props: { account: Object }, emits: ['login'], setup(props, { emit }) {
    onMounted(() => { if (!props.account) emit('login') })
    return {}
  }, template: '<p>购物车</p>' })
  wrapper = mount(App, { global: { stubs: { MarketplaceWorkspace: pages } } }); await flushPromises()
  expect(window.location.hash).toBe('#/shop/cart')
  expect(window.history.state.resolveflow_buyer_navigation).toEqual({ owner: 'B-1', depth: 2 })
})
