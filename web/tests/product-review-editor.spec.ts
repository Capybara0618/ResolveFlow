import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import ProductReviewEditor from '../src/ui/ProductReviewEditor.vue'
import { reviewApi, type ProductReview } from '../src/review-client'
import { ApiError } from '../src/client'

const review: ProductReview = { review_id: 1, product_id: 'P-1001', product_name: '耳机', variant: '黑色', rating: 5, body: '我的评价', reply: null, version: 1, created_at: '2026-10-22T04:00:00Z', updated_at: '2026-10-22T04:00:00Z' }
let w: VueWrapper
beforeEach(() => { vi.spyOn(reviewApi, 'own').mockResolvedValue({ can_review: true, blocked_reason: null, review: null }); vi.spyOn(reviewApi, 'save').mockResolvedValue(review) })
afterEach(() => { w?.unmount(); vi.restoreAllMocks() })
async function open() { w = mount(ProductReviewEditor, { props: { token: 'buyer-token', line: 'line-one', name: '耳机' } }); await flushPromises() }
it('uses server delivery eligibility before offering an editor', async () => {
  vi.mocked(reviewApi.own).mockResolvedValue({ can_review: false, blocked_reason: '签收后可评价', review: null })
  await open(); expect(w.text()).toContain('签收后可评价'); expect(w.find('textarea').exists()).toBe(false)
  expect(reviewApi.save).not.toHaveBeenCalled()
})
it('sends only rating, text and current version then shows the saved server result', async () => {
  await open(); await w.get('textarea').setValue('我的评价'); await w.get('form').trigger('submit'); await flushPromises()
  expect(reviewApi.save).toHaveBeenCalledWith('buyer-token', 'line-one', { rating: 5, body: '我的评价', expected_version: 0 })
  expect(w.text()).toContain('评价已保存'); expect(w.text()).toContain('我的评价')
})
it('preserves input on conflict and requires an explicit latest read before resubmitting', async () => {
  vi.mocked(reviewApi.save).mockRejectedValueOnce(new ApiError(409, 'REVIEW_CHANGED', '评价已更新'))
  await open(); await w.get('textarea').setValue('本地输入'); await w.get('form').trigger('submit'); await flushPromises()
  expect(w.get('textarea').element.value).toBe('本地输入'); expect(w.get('[data-test="review-save"]').attributes('disabled')).toBeDefined()
  vi.mocked(reviewApi.own).mockResolvedValue({ can_review: true, blocked_reason: null, review: { ...review, body: '其他页面内容', version: 4 } })
  await w.get('[data-test="review-refresh"]').trigger('click'); await flushPromises()
  expect(w.get('textarea').element.value).toBe('本地输入'); expect(w.text()).toContain('其他页面内容')
  await w.get('form').trigger('submit'); await flushPromises()
  expect(reviewApi.save).toHaveBeenLastCalledWith('buyer-token', 'line-one', { rating: 5, body: '本地输入', expected_version: 4 })
})
it('unknown save freezes and retries the original payload without claiming success', async () => {
  vi.mocked(reviewApi.save).mockRejectedValueOnce(new TypeError('lost response'))
  await open(); await w.get('textarea').setValue('我的评价'); await w.get('form').trigger('submit'); await flushPromises()
  expect(w.text()).not.toContain('评价已保存'); expect(w.get('textarea').attributes('disabled')).toBeDefined()
  await w.get('form').trigger('submit'); await flushPromises()
  expect(vi.mocked(reviewApi.save).mock.calls[0]).toEqual(vi.mocked(reviewApi.save).mock.calls[1])
  expect(w.text()).toContain('评价已保存')
})
