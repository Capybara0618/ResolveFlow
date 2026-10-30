import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import MerchantReviews from '../src/ui/MerchantReviews.vue'
import { reviewApi, type ProductReview } from '../src/review-client'
import { ApiError } from '../src/client'

const review: ProductReview = { review_id: 2, product_id: 'P1', product_name: '耳机', variant: '黑色', rating: 2, body: '买家原文', reply: null, version: 3, created_at: '2026-10-22T04:00:00Z', updated_at: '2026-10-22T04:00:00Z' }
const account = { access_token: 'merchant-token', role: 'MERCHANT_ADMIN' as const, merchant_id: 'M-1001', expires_in: 3600 }
let w: VueWrapper
beforeEach(() => { vi.spyOn(reviewApi, 'merchant').mockResolvedValue({ items: [review], summary: null, next_before: null }); vi.spyOn(reviewApi, 'reply').mockResolvedValue({ ...review, reply: '商家答复', version: 4 }) })
afterEach(() => { w?.unmount(); vi.restoreAllMocks() })
async function open() { w = mount(MerchantReviews, { props: { account } }); await flushPromises(); await w.get('[data-test="select-review"]').trigger('click') }
it('shows original buyer text and submits only a reply against the observed version', async () => {
  await open(); expect(w.text()).toContain('买家原文'); expect(w.text()).not.toContain('删除评价')
  await w.get('textarea').setValue('商家答复'); await w.get('form').trigger('submit'); await flushPromises()
  expect(reviewApi.reply).toHaveBeenCalledWith('merchant-token', 2, '商家答复', 3)
  expect(w.text()).toContain('回复已保存')
})
it('retains local reply on conflict and reads the exact original review before allowing another write', async () => {
  vi.mocked(reviewApi.reply).mockRejectedValueOnce(new ApiError(409, 'REVIEW_CHANGED', '评价已更新'))
  await open(); await w.get('textarea').setValue('本地答复'); await w.get('form').trigger('submit'); await flushPromises()
  expect(w.get('textarea').element.value).toBe('本地答复'); expect(w.get('[data-test="save-reply"]').attributes('disabled')).toBeDefined()
  vi.mocked(reviewApi.merchant).mockResolvedValue({ items: [{ ...review, body: '买家更新原文', version: 5 }], summary: null, next_before: null })
  await w.get('[data-test="refresh-review"]').trigger('click'); await flushPromises()
  expect(reviewApi.merchant).toHaveBeenLastCalledWith('merchant-token', 3, 1)
  expect(w.text()).toContain('买家更新原文'); expect(w.get('textarea').element.value).toBe('本地答复')
  await w.get('form').trigger('submit'); await flushPromises()
  expect(reviewApi.reply).toHaveBeenLastCalledWith('merchant-token', 2, '本地答复', 5)
})
it('unknown replies freeze their original target and content until confirmed', async () => {
  vi.mocked(reviewApi.reply).mockRejectedValueOnce(new TypeError('lost'))
  await open(); await w.get('textarea').setValue('商家答复'); await w.get('form').trigger('submit'); await flushPromises()
  expect(w.text()).not.toContain('回复已保存'); expect(w.get('textarea').attributes('disabled')).toBeDefined()
  await w.get('form').trigger('submit'); await flushPromises()
  expect(vi.mocked(reviewApi.reply).mock.calls[0]).toEqual(vi.mocked(reviewApi.reply).mock.calls[1])
})

it('replaces review pages and closes the editor instead of replying to an off-page selection', async () => {
  vi.mocked(reviewApi.merchant).mockResolvedValueOnce({ items: [review], summary: null, next_before: 2 })
  await open()
  vi.mocked(reviewApi.merchant).mockResolvedValueOnce({ items: [{ ...review, review_id: 1, body: '第二页评价' }], summary: null, next_before: null })
  await w.findAll('button').find(b => b.text() === '下一页')!.trigger('click'); await flushPromises()
  expect(reviewApi.merchant).toHaveBeenLastCalledWith('merchant-token', 2, 8)
  expect(w.findAll('[data-test="select-review"]')).toHaveLength(1)
  expect(w.text()).toContain('第二页评价'); expect(w.find('textarea').exists()).toBe(false)
  expect(w.text()).toContain('第 2 页')
})
