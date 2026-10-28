import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import SupportOperations from '../src/ui/SupportOperations.vue'
import { operationsApi, type OperationsDetail } from '../src/support-operations'
import fixture from '../../contracts/core/fixtures/support-operations.json'
import { ApiError } from '../src/client'
let wrapper: VueWrapper | undefined
afterEach(() => { wrapper?.unmount(); vi.restoreAllMocks() })
it('shows persisted process events and counts, including honest missing metrics and mock mode', async () => {
  vi.spyOn(operationsApi, 'list').mockResolvedValue(fixture.SupportOperationsPage)
  vi.spyOn(operationsApi, 'read').mockResolvedValue({ ...fixture.SupportOperationsDetail, run: { ...fixture.SupportOperationsDetail.run, model_requests: null } } as OperationsDetail)
  wrapper = mount(SupportOperations, { props: { token: 'platform' } }); await flushPromises()
  await wrapper.get('[data-run]').trigger('click'); await flushPromises()
  expect(wrapper.text()).toContain('查询物流')
  expect(wrapper.text()).toContain('未记录')
  expect(wrapper.text()).toContain('脚本模型')
  expect(wrapper.text()).not.toContain('请求正文')
})
it('discards a late detail after another run is selected', async () => {
  const run = fixture.SupportOperationsPage.items[0]!
  vi.spyOn(operationsApi, 'list').mockResolvedValue({ items: [run, { ...run, run_id: 'another' }], limit: 50 })
  let release!: (detail: OperationsDetail) => void
  vi.spyOn(operationsApi, 'read').mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
    .mockResolvedValueOnce({ ...fixture.SupportOperationsDetail, run: { ...run, run_id: 'another', merchant_id: 'SECOND' } } as OperationsDetail)
  wrapper = mount(SupportOperations, { props: { token: 'platform' } }); await flushPromises()
  await wrapper.findAll('[data-run]')[0]!.trigger('click')
  await wrapper.findAll('[data-run]')[1]!.trigger('click'); await flushPromises()
  release(fixture.SupportOperationsDetail as OperationsDetail); await flushPromises()
  expect(wrapper.get('[data-run-detail]').text()).toContain('SECOND')
  expect(wrapper.get('[data-run-detail]').text()).not.toContain('M-1001')
})
it('expires the session on a rejected administrator identity', async () => {
  vi.spyOn(operationsApi, 'list').mockRejectedValue(new ApiError(401, 'UNAUTHENTICATED', '登录已失效'))
  wrapper = mount(SupportOperations, { props: { token: 'expired' } }); await flushPromises()
  expect(wrapper.emitted('expired')).toHaveLength(1)
})
