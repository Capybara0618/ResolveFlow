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
