import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { beforeEach, afterEach, it, expect, vi } from 'vitest'
import { accountApi } from '../src/account-client'
import { ApiError } from '../src/client'
import AccountWorkspace from '../src/ui/AccountWorkspace.vue'
import AddressPicker from '../src/ui/AddressPicker.vue'

const account = { access_token: 'owner', role: 'CUSTOMER' as const, buyer_id: 'buyer', expires_in: 3600 }
const profile = { username: 'buyer', display_name: '原昵称', avatar_id: null, version: 3 }
const address = { address_id: 'a1', recipient: '测试收货人', phone: '13000000000', province: '测试省', city: '测试市', district: '测试区', detail: '测试路1号', is_default: true, version: 4 }
let w: VueWrapper
beforeEach(() => {
  vi.spyOn(accountApi, 'profile').mockResolvedValue(profile)
  vi.spyOn(accountApi, 'addresses').mockResolvedValue({ items: [address] })
})
afterEach(() => { w?.unmount(); vi.restoreAllMocks() })
it('saves a nickname with its loaded version and updates the account display', async () => {
  vi.spyOn(accountApi, 'save').mockResolvedValue({ ...profile, display_name: '新昵称', version: 4 })
  w = mount(AccountWorkspace, { props: { account } }); await flushPromises()
  await w.get('input[autocomplete="nickname"]').setValue('新昵称')
  await w.get('form').trigger('submit'); await flushPromises()
  expect(accountApi.save).toHaveBeenCalledWith('owner', '新昵称', 3)
  expect(w.emitted('saved')?.[0][0]).toMatchObject({ display_name: '新昵称', version: 4 })
})
it('keeps the editor visible after an address version conflict', async () => {
  vi.spyOn(accountApi, 'saveAddress').mockRejectedValue(new ApiError(409, 'VERSION_CONFLICT', '地址已更新，请刷新'))
  w = mount(AccountWorkspace, { props: { account, mode: 'addresses' } }); await flushPromises()
  await w.get('.address-row .account-actions button').trigger('click')
  await w.get('.address-form').trigger('submit'); await flushPromises()
  expect(w.get('[role="alert"]').text()).toContain('请刷新')
  expect(w.find('.address-form').exists()).toBe(true)
  expect(w.emitted('changed')).toBeUndefined()
})
it('selects the default address and refreshes its version after management', async () => {
  w = mount(AddressPicker, { props: { account, modelValue: null } }); await flushPromises()
  expect(w.emitted('update:modelValue')?.[0]).toEqual([{ address_id: 'a1', expected_version: 4 }])
  vi.mocked(accountApi.addresses).mockResolvedValue({ items: [{ ...address, version: 5 }] })
  await w.get('.shipping-picker-head button').trigger('click'); await flushPromises()
  w.findComponent(AccountWorkspace).vm.$emit('changed'); await flushPromises()
  expect(w.emitted('update:modelValue')?.at(-1)).toEqual([{ address_id: 'a1', expected_version: 5 }])
})
it('locks address selection and closing the editor during a save', async () => {
  w = mount(AddressPicker, { props: { account, modelValue: null } }); await flushPromises()
  await w.get('.shipping-picker-head button').trigger('click'); await flushPromises()
  w.findComponent(AccountWorkspace).vm.$emit('working', true); await flushPromises()
  expect(w.get('.shipping-picker-head button').attributes('disabled')).toBeDefined()
  expect(w.get('input[type="radio"]').attributes('disabled')).toBeDefined()
})
