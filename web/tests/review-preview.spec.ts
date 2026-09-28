import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ReviewPreview from '../src/preview/ReviewPreview.vue'

afterEach(() => vi.unstubAllGlobals())

describe('review design preview', () => {
  it('switches the entire case context and keeps demo data separate from API requests', async () => {
    const fetcher = vi.fn()
    vi.stubGlobal('fetch', fetcher)
    const wrapper = mount(ReviewPreview)
    expect(wrapper.text()).toContain('设计预览 · 合成数据')
    expect(wrapper.get('[data-test="order-product"]').text()).toContain('无线降噪耳机')
    await wrapper.get('[data-test="case-0011"]').trigger('click')
    expect(wrapper.get('[data-test="case-number"]').text()).toContain('0011')
    expect(wrapper.get('[data-test="order-product"]').text()).toContain('便携蓝牙音箱')
    expect(wrapper.get('[data-test="customer-name"]').text()).toBe('李**')
    expect(wrapper.get('[data-test="recommendation"]').text()).toContain('补充物流凭证')
    expect(fetcher).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('requires a reason, previews a decision locally, and leaves the other cases unchanged', async () => {
    const fetcher = vi.fn()
    vi.stubGlobal('fetch', fetcher)
    const wrapper = mount(ReviewPreview)
    await wrapper.get('[data-test="approve"]').trigger('click')
    expect(wrapper.get('[role="dialog"]').text()).toContain('批准退款授权')
    expect(wrapper.get('[data-test="confirm-decision"]').attributes('disabled')).toBeDefined()
    await wrapper.get('textarea').setValue('已核对订单、材料及退款政策')
    await wrapper.get('[data-test="confirm-decision"]').trigger('click')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(wrapper.get('[role="status"]').text()).toContain('未提交真实工单')
    expect(wrapper.get('[data-test="case-status"]').text()).toBe('已批准')
    expect(wrapper.get('[data-test="approve"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-test="case-0011"]').trigger('click')
    expect(wrapper.get('[data-test="case-status"]').text()).toBe('待补充')
    expect(fetcher).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('opens evidence details and can close them without changing the case', async () => {
    const wrapper = mount(ReviewPreview, { attachTo: document.body })
    await wrapper.get('[data-test="evidence-photo"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="dialog"]').text()).toContain('IMG_3281.jpg')
    expect(wrapper.get('[role="dialog"] img').attributes('alt')).toContain('合成')
    await wrapper.get('[role="dialog"]').trigger('keydown', { key: 'Escape' })
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="case-status"]').text()).toBe('待审核')
    wrapper.unmount()
  })
})
