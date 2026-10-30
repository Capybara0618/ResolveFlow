import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { it, expect, vi, beforeEach, afterEach } from 'vitest'
import { notificationApi, type Notification } from '../src/notification-client'
import NotificationCenter from '../src/ui/NotificationCenter.vue'
import { accountApi } from '../src/account-client'
import { shopApi } from '../src/shop-client'
import PersonalCenter from '../src/ui/PersonalCenter.vue'
const item: Notification = { notification_id: 'message:a', title: '商家回复了你的咨询', target: 'SUPPORT', target_id: 'conversation-a', conversation_id: 'conversation-a', created_at: '2026-10-29T08:00:00Z', read: false }
let w: VueWrapper
beforeEach(() => { vi.spyOn(shopApi, 'purchases').mockResolvedValue({ items: [], next_cursor: null }); vi.spyOn(accountApi, 'addresses').mockResolvedValue({ items: [] }); vi.spyOn(notificationApi, 'list').mockResolvedValue({ items: [structuredClone(item)], unread_count: 1, next_cursor: null }); vi.spyOn(notificationApi, 'read').mockResolvedValue(undefined) })
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
  await w.findAll('.personal-orders button').at(-1)!.trigger('click')
  expect(w.emitted('navigate')?.at(-1)).toEqual(['#/customer/applications'])
})

it('identifies the store in a buyer notification and uses its avatar component', async () => {
  vi.mocked(notificationApi.list).mockResolvedValue({ items: [{ ...item, store_id: 'M-1001', sender_name: '松间数码', sender_kind: 'MERCHANT' }], unread_count: 1, next_cursor: null })
  w = mount(NotificationCenter, { props: { token: 'buyer', expanded: true } }); await flushPromises()
  expect(w.get('.notification-copy strong').text()).toBe('松间数码'); expect(w.findComponent({ name: 'StoreMark' }).props('id')).toBe('M-1001')
})
it('shows real recent orders even if address lookup fails', async () => {
  vi.mocked(shopApi.purchases).mockResolvedValue({ items: [{ purchase_id: 'order:recent', store_id: 'M-1001', store_name: '松间数码', status: 'PAID', shopping_stage: 'AWAITING_SHIPMENT', total_amount: 32900, lines: [{ product_name: '无线耳机', asset_key: 'headphones', variant: '黑色' }] } as Awaited<ReturnType<typeof shopApi.purchases>>['items'][number]], next_cursor: null })
  vi.mocked(accountApi.addresses).mockRejectedValue(new Error('lost'))
  w = mount(PersonalCenter, { props: { account: { access_token: 'owner', role: 'CUSTOMER', buyer_id: 'b', expires_in: 3600 } } }); await flushPromises()
  expect(w.get('.personal-order').text()).toContain('无线耳机'); expect(w.get('.personal-order').text()).toContain('待发货'); expect(w.text()).toContain('地址暂时无法读取')
  await w.get('.personal-order').trigger('click'); expect(w.emitted('navigate')?.[0]).toEqual(['#/shop/orders/order%3Arecent'])
})

it('pages message records without marking them read or accumulating prior records', async () => {
  vi.mocked(notificationApi.list).mockResolvedValueOnce({ items: [structuredClone(item)], unread_count: 20, next_cursor: 'next-messages' })
    .mockResolvedValueOnce({ items: [{ ...item, notification_id: 'message:b', title: '第二页消息' }], unread_count: 20, next_cursor: null })
  w = mount(NotificationCenter, { props: { token: 'owner', expanded: true } }); await flushPromises()
  await w.findAll('button').find(b => b.text() === '下一页')!.trigger('click'); await flushPromises()
  expect(notificationApi.list).toHaveBeenLastCalledWith('owner', 'next-messages')
  expect(w.findAll('.notification-item')).toHaveLength(1); expect(w.text()).toContain('第二页消息')
  expect(w.text()).not.toContain('商家回复了你的咨询'); expect(notificationApi.read).not.toHaveBeenCalled()
})


it('restores the visited message page on return and refreshes that page', async () => {
  const memory={index:0,cursors:[undefined] as Array<string|undefined>}
  vi.mocked(notificationApi.list).mockResolvedValueOnce({items:[structuredClone(item)],unread_count:2,next_cursor:'messages:2'})
    .mockResolvedValue({items:[{...item,title:'保留第二页'}],unread_count:2,next_cursor:null})
  w=mount(NotificationCenter,{props:{token:'owner',expanded:true,memory}});await flushPromises()
  await w.findAll('button').find(b=>b.text()==='下一页')!.trigger('click');await flushPromises();w.unmount()
  w=mount(NotificationCenter,{props:{token:'owner',expanded:true,memory}});await flushPromises()
  expect(notificationApi.list).toHaveBeenLastCalledWith('owner','messages:2')
  await w.findAll('button').find(b=>b.text()==='刷新')!.trigger('click');await flushPromises()
  expect(notificationApi.list).toHaveBeenLastCalledWith('owner','messages:2')
  expect(w.text()).toContain('第 2 页');expect(w.text()).toContain('保留第二页')
})
