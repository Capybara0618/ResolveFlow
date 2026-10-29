import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { enrollmentApi } from '../src/enrollment-client'
import { presentationApi } from '../src/presentation-client'
import { ApiError } from '../src/client'
import EnrollmentForm from '../src/ui/EnrollmentForm.vue'
import PresentationEditor from '../src/ui/PresentationEditor.vue'
import ProductGallery from '../src/ui/ProductGallery.vue'
const account = { access_token: 'merchant', role: 'MERCHANT_ADMIN' as const, merchant_id: 'M-1001', expires_in: 3600 }
let w: VueWrapper
beforeEach(() => { vi.spyOn(presentationApi, 'product').mockResolvedValue({ product_id: 'p', version: 4, images: ['image-one', 'image-two'], specifications: [{ name: '材质', value: '棉' }], shipping_note: '配送说明', aftercare_note: '售后说明' }) })
afterEach(() => { w?.unmount(); vi.restoreAllMocks() })
it('requires matching passwords before registration and explicit recovery-key acknowledgement afterward', async () => {
  vi.spyOn(enrollmentApi, 'register').mockResolvedValue({ username: 'newbuyer', recovery_key: 'a'.repeat(64) })
  w = mount(EnrollmentForm, { props: { mode: 'register' } })
  await w.get('input[autocomplete="username"]').setValue('newbuyer'); await w.get('input[autocomplete="nickname"]').setValue('测试买家')
  const passwords = w.findAll('input[type="password"]'); await passwords[0].setValue('password-test'); await passwords[1].setValue('different')
  await w.get('form').trigger('submit'); expect(enrollmentApi.register).not.toHaveBeenCalled()
  await passwords[1].setValue('password-test'); await w.get('form').trigger('submit'); await flushPromises()
  expect(enrollmentApi.register).toHaveBeenCalledWith('newbuyer', '测试买家', 'password-test')
  expect(w.get('.recovery-key').text()).toBe('a'.repeat(64)); expect(w.get('button').attributes('disabled')).toBeDefined()
  await w.get('input[type="checkbox"]').setValue(true); await w.get('button').trigger('click'); expect(w.emitted('close')?.[0]).toEqual(['newbuyer'])
})
it('uses the supplied recovery key for the recovery endpoint', async () => {
  vi.spyOn(enrollmentApi, 'recover').mockResolvedValue({ username: 'newbuyer', recovery_key: 'b'.repeat(64) })
  w = mount(EnrollmentForm, { props: { mode: 'recover' } })
  await w.get('input[autocomplete="username"]').setValue('newbuyer'); await w.get('input[autocomplete="off"]').setValue('a'.repeat(64))
  for (const input of w.findAll('input[autocomplete="new-password"]')) await input.setValue('new-password')
  await w.get('form').trigger('submit'); await flushPromises()
  expect(enrollmentApi.recover).toHaveBeenCalledWith('newbuyer', 'a'.repeat(64), 'new-password')
})
it('persists image ordering with the loaded version and preserves edits on a conflict', async () => {
  vi.spyOn(presentationApi, 'saveProduct').mockRejectedValue(new ApiError(409, 'VERSION_CONFLICT', '资料已更新，请刷新'))
  w = mount(PresentationEditor, { props: { account, product: 'p' } }); await flushPromises()
  await w.findAll('.presentation-actions button').find(b => b.text() === '后移')!.trigger('click')
  await w.get('form').trigger('submit'); await flushPromises()
  expect(presentationApi.saveProduct).toHaveBeenCalledWith('merchant', 'p', expect.objectContaining({ expected_version: 4, images: ['image-two', 'image-one'] }))
  expect(w.get('[role="alert"]').text()).toContain('请刷新'); expect(w.get('.presentation-save').attributes('disabled')).toBeDefined()
  expect(w.findAll('.presentation-images article')).toHaveLength(2)
})
it('renders ordered gallery thumbnails and the supplied facts without inventing missing notes', async () => {
  w = mount(ProductGallery, { props: { product: 'p', asset: 'headphones', name: '测试商品' } }); await flushPromises()
  expect(w.text()).toContain('材质'); expect(w.text()).toContain('配送说明')
  await w.get('[aria-label="查看第2张商品图片"]').trigger('click'); expect(w.get('[aria-label="查看第2张商品图片"]').attributes('aria-pressed')).toBe('true')
  expect(w.get('.gallery-main img').attributes('src')).toContain('image-two')
})
