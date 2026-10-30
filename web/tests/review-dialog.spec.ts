import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ReviewDialog from '../src/ui/ReviewDialog.vue'

describe('review dialog keyboard access', () => {
  it('includes selects in keyboard containment and excludes disabled fields', async () => {
    const wrapper = mount(ReviewDialog, { attachTo: document.body, props: { title: '新增工作人员' },
      slots: { default: '<input disabled><textarea disabled></textarea><select id="last-select"><option>售后专员</option></select>' } })
    await flushPromises()
    const dialog = wrapper.get('[role="dialog"]')
    await dialog.trigger('keydown', { key: 'Tab', shiftKey: true })
    expect(document.activeElement?.id).toBe('last-select')
    await dialog.trigger('keydown', { key: 'Tab' })
    expect(document.activeElement?.getAttribute('aria-label')).toBe('关闭弹窗')
    wrapper.unmount()
  })
  it('contains keyboard focus and restores focus and scrolling on close', async () => {
    const opener = document.createElement('button')
    document.body.append(opener)
    opener.focus()
    const before = document.body.style.overflow
    const wrapper = mount(ReviewDialog, {
      attachTo: document.body,
      props: { title: '批准退款授权' },
      slots: { default: '<textarea aria-label="审核理由"></textarea><button id="last-action">提交</button>' },
    })
    await flushPromises()
    const dialog = wrapper.get('[role="dialog"]')
    expect(document.activeElement).toBe(dialog.element)
    expect(document.body.style.overflow).toBe('hidden')
    await dialog.trigger('keydown', { key: 'Tab', shiftKey: true })
    expect(document.activeElement?.id).toBe('last-action')
    await dialog.trigger('keydown', { key: 'Tab' })
    expect(document.activeElement?.getAttribute('aria-label')).toBe('关闭弹窗')
    await dialog.trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('close')).toHaveLength(1)
    wrapper.unmount()
    expect(document.activeElement).toBe(opener)
    expect(document.body.style.overflow).toBe(before)
    opener.remove()
  })

  it('keeps an in-flight decision open until its request finishes', async () => {
    const wrapper = mount(ReviewDialog, { props: { title: '批准退款授权', busy: true } })
    await wrapper.get('[role="dialog"]').trigger('keydown', { key: 'Escape' })
    await wrapper.get('.rf-dialog-backdrop').trigger('click')
    expect(wrapper.emitted('close')).toBeUndefined()
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
})

it('keeps a closed reusable dialog out of the focus order and locks the page only when opened', async () => {
  const opener = document.createElement('button'); document.body.append(opener); opener.focus()
  const previous = document.body.style.overflow
  const w = mount(ReviewDialog, { attachTo: document.body, props: { title: '确认操作', open: false } })
  await flushPromises(); expect(w.find('[role="dialog"]').exists()).toBe(false)
  expect(document.body.style.overflow).toBe(previous)
  await w.setProps({ open: true }); await flushPromises()
  expect(w.find('[role="dialog"]').exists()).toBe(true); expect(document.body.style.overflow).toBe('hidden')
  await w.setProps({ open: false }); await flushPromises()
  w.unmount(); expect(document.body.style.overflow).toBe(previous); expect(document.activeElement).toBe(opener)
  opener.remove()
})


it('contains keyboard focus through the separate action footer', async () => {
  const w = mount(ReviewDialog, { attachTo: document.body, props: { title: '取消这笔订单？', compact: true }, slots: { default: '<p>订单尚未付款</p>', footer: '<button>暂不取消</button><button id="footer-confirm">取消订单</button>' } })
  await flushPromises()
  await w.get('[role="dialog"]').trigger('keydown', { key: 'Tab', shiftKey: true })
  expect(document.activeElement?.id).toBe('footer-confirm')
  await w.get('[role="dialog"]').trigger('keydown', { key: 'Tab' })
  expect(document.activeElement?.getAttribute('aria-label')).toBe('关闭弹窗')
  w.unmount()
})
