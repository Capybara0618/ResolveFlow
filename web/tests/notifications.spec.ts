import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { it, expect, vi, beforeEach, afterEach } from 'vitest'
import { notificationApi, type Notification } from '../src/notification-client'
import NotificationCenter from '../src/ui/NotificationCenter.vue'
import PersonalCenter from '../src/ui/PersonalCenter.vue'
const item: Notification = { notification_id: 'message:a', title: '商家回复了你的咨询', target: 'SUPPORT', target_id: 'conversation-a', conversation_id: 'conversation-a', created_at: '2026-10-29T08:00:00Z', read: false }
let w: VueWrapper
beforeEach(() => { vi.spyOn(notificationApi, 'list').mockResolvedValue({ items: [structuredClone(item)], unread_count: 1, next_cursor: null }); vi.spyOn(notificationApi, 'read').mockResolvedValue(undefined) })
afterEach(() => { w?.unmount(); vi.restoreAllMocks() })
it('shows unread count and opens the exact destination after persisting read state', async () => {
  w = mount(NotificationCenter, { props: { token: 'owner' } }); await flushPromises()
  expect(w.get('.notification-count').text()).toBe('1')
  await w.get('.notification-toggle').trigger('click'); await flushPromises()
  await w.get('.notification-item').trigger('click'); await flushPromises()
  expect(notificationApi.read).toHaveBeenCalledWith('owner', 'message:a')
  expect(w.emitted('open')?.[0][0]).toMatchObject({ target_id: 'conversation-a', read: true })
  expect(w.find('.notification-count').exists()).toBe(false)
})
it('does not mark a failed read as success or lose the message', async () => {
  vi.mocked(notificationApi.read).mockRejectedValue(new TypeError('lost'))
  w = mount(NotificationCenter, { props: { token: 'owner', expanded: true } }); await flushPromises()
  await w.get('.notification-item').trigger('click'); await flushPromises()
  expect(w.emitted('open')).toBeUndefined(); expect(w.get('[role="alert"]').text()).toContain('请重试')
  expect(w.get('.notification-item').classes()).toContain('unread')
})
it('ignores an old account response after switching accounts', async () => {
  let resolve!: (value: { items: Notification[]; unread_count: number; next_cursor: null }) => void
  vi.mocked(notificationApi.list).mockReturnValueOnce(new Promise(r => { resolve = r })).mockResolvedValueOnce({ items: [], unread_count: 0, next_cursor: null })
  w = mount(NotificationCenter, { props: { token: 'old', expanded: true } })
  await w.setProps({ token: 'new' }); await flushPromises(); resolve({ items: [item], unread_count: 1, next_cursor: null }); await flushPromises()
  expect(w.text()).toContain('暂时没有消息'); expect(w.text()).not.toContain(item.title)
})
it('connects personal-center stages to server-side order filters', async () => {
  w = mount(PersonalCenter, { props: { account: { access_token: 'owner', role: 'CUSTOMER', buyer_id: 'b', expires_in: 3600 } } })
  await w.get('.personal-orders button:nth-child(2)').trigger('click')
  expect(w.emitted('navigate')?.[0]).toEqual(['#/shop/orders?status=AWAITING_SHIPMENT'])
})
