import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ProductReviews from '../src/ui/ProductReviews.vue'
import { reviewApi, type ReviewPage } from '../src/review-client'

const page: ReviewPage = { items: [{ review_id: 2, product_id: 'P-1001', product_name: '耳机', variant: '黑色', rating: 5, body: '<script>用户原文</script>', reply: '感谢反馈', version: 1, created_at: '2026-10-22T04:00:00Z', updated_at: '2026-10-22T04:00:00Z' }], summary: { count: 1, average: 5, stars: [1, 0, 0, 0, 0] }, next_before: null }
let wrapper: VueWrapper
beforeEach(() => { vi.spyOn(reviewApi, 'public').mockResolvedValue(page) })
afterEach(() => { wrapper?.unmount(); vi.restoreAllMocks() })
it('renders server scores, purchased review text and merchant reply without interpreting HTML', async () => {
  wrapper = mount(ProductReviews, { props: { product: 'P-1001' } }); await flushPromises()
  expect(wrapper.text()).toContain('5.0'); expect(wrapper.text()).toContain('已购用户')
  expect(wrapper.text()).toContain('<script>用户原文</script>'); expect(wrapper.find('script').exists()).toBe(false)
  expect(wrapper.text()).toContain('感谢反馈')
  expect(wrapper.emitted('summary')).toEqual([[page.summary]])
})
it('empty results never invent a zero-star score', async () => {
  vi.mocked(reviewApi.public).mockResolvedValue({ items: [], summary: { count: 0, average: null, stars: [0, 0, 0, 0, 0] }, next_before: null })
  wrapper = mount(ProductReviews, { props: { product: 'P-1001' } }); await flushPromises()
  expect(wrapper.text()).toContain('暂无评价'); expect(wrapper.text()).not.toContain('0.0')
})
it('failed reads remain errors until explicit retry succeeds', async () => {
  vi.mocked(reviewApi.public).mockRejectedValueOnce(new Error('offline'))
  wrapper = mount(ProductReviews, { props: { product: 'P-1001' } }); await flushPromises()
  expect(wrapper.find('[role="alert"]').exists()).toBe(true)
  await wrapper.get('button').trigger('click'); await flushPromises()
  expect(wrapper.text()).toContain('感谢反馈')
})
it('ignores a late response after the product changes', async () => {
  let finish!: (p: ReviewPage) => void
  vi.mocked(reviewApi.public).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  wrapper = mount(ProductReviews, { props: { product: 'old' } }); await flushPromises()
  vi.mocked(reviewApi.public).mockResolvedValue({ ...page, items: [{ ...page.items[0], body: '新商品评价' }] })
  await wrapper.setProps({ product: 'new' }); await flushPromises()
  finish(page); await flushPromises()
  expect(wrapper.text()).toContain('新商品评价'); expect(wrapper.text()).not.toContain('用户原文')
  expect(wrapper.emitted('summary')).toHaveLength(1)
})
