import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AdminPeople from '../src/ui/AdminPeople.vue'
import { ApiError, coreApi, type AdminAccount, type AdminAccountPage, type AccountAuditPage, type AccountMutation, type LoginResponse } from '../src/client'

const account: LoginResponse = { access_token: 't', role: 'MERCHANT_ADMIN', merchant_id: 'M-1', expires_in: 3600 }
const worker: AdminAccount = { username: 'worker', display_name: '售后专员甲', role: 'REVIEWER', enabled: true, version: 3, created_at: '2026-10-02T05:00:00Z', updated_at: '2026-10-02T05:00:00Z' }
const admin: AdminAccount = { ...worker, username: 'admin', display_name: '商家管理员', role: 'MERCHANT_ADMIN' }
const page: AdminAccountPage = { items: [worker, admin], page: { limit: 20, next_cursor: 'continue' }, total: 45, enabled_admins: 1, current_username: 'admin' }
const emptyHistory: AccountAuditPage = { items: [], page: { limit: 10 }, total: 0 }
let wrapper: VueWrapper | undefined
const click = async (text: string) => { await wrapper!.findAll('button').find(b => b.text() === text)!.trigger('click'); await flushPromises() }
const open = async (username = 'worker') => { await wrapper!.get(`[aria-label="维护 ${username}"]`).trigger('click'); await flushPromises() }
beforeEach(() => {
  vi.spyOn(coreApi, 'adminAccounts').mockResolvedValue(page)
  vi.spyOn(coreApi, 'accountHistory').mockResolvedValue(emptyHistory)
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks() })
const start = async () => { wrapper = mount(AdminPeople, { props: { account } }); await flushPromises() }

describe('merchant account administration', () => {
  it('shows server totals, applies independent filters and keeps cursor requests on the applied search', async () => {
    await start()
    expect(wrapper!.text()).toContain('账号列表 （45）')
    expect(wrapper!.text()).toContain('已显示 2 / 45')
    await wrapper!.get('.people-search input').setValue('first')
    await wrapper!.get('.people-filters select').setValue('REVIEWER')
    await wrapper!.get('.people-filters').trigger('submit'); await flushPromises()
    expect(coreApi.adminAccounts).toHaveBeenLastCalledWith('t', { query: 'first', role: 'REVIEWER', status: 'ALL' }, undefined)
    await wrapper!.get('.people-search input').setValue('unapplied')
    await click('加载更多')
    expect(coreApi.adminAccounts).toHaveBeenLastCalledWith('t', { query: 'first', role: 'REVIEWER', status: 'ALL' }, 'continue')
  })

  it('retains the opened account version and draft after conflict; reopening is required before another write', async () => {
    const update = vi.spyOn(coreApi, 'updateAccount').mockRejectedValue(new ApiError(409, 'STATE_CONFLICT', 'stale'))
    await start(); await open()
    await wrapper!.get('.people-maintenance input').setValue('我的草稿')
    await wrapper!.get('.people-maintenance textarea').setValue('维护理由')
    vi.mocked(coreApi.adminAccounts).mockResolvedValue({ ...page, items: [{ ...worker, version: 4, display_name: '别人的修改' }, admin] })
    await wrapper!.get('.people-maintenance').trigger('submit'); await flushPromises()
    expect(update).toHaveBeenCalledExactlyOnceWith('t', worker, { display_name: '我的草稿', role: 'REVIEWER', enabled: true, reason: '维护理由' })
    expect((wrapper!.get('.people-maintenance input').element as HTMLInputElement).value).toBe('我的草稿')
    expect(wrapper!.text()).toContain('请从列表重新打开')
    expect(wrapper!.get('.people-maintenance button[type="submit"]').attributes('disabled')).toBeDefined()
    await open()
    expect((wrapper!.get('.people-maintenance input').element as HTMLInputElement).value).toBe('别人的修改')
    expect(wrapper!.text()).toContain('版本 4')
    expect(update).toHaveBeenCalledTimes(1)
  })

  it('clears initial passwords immediately on submit and creates only staff accounts for the current merchant', async () => {
    let resolve!: (result: AccountMutation) => void
    const create = vi.spyOn(coreApi, 'createStaff').mockImplementation(() => new Promise(done => { resolve = done }))
    await start(); await click('新增工作人员')
    const dialog = wrapper!.get('[role="dialog"]')
    const inputs = dialog.findAll('input')
    await inputs[0].setValue('new-worker'); await inputs[1].setValue('新专员'); await inputs[2].setValue('initial-pass')
    await dialog.get('textarea').setValue('新增岗位')
    await dialog.get('form').trigger('submit')
    expect((inputs[2].element as HTMLInputElement).value).toBe('')
    expect(create).toHaveBeenCalledWith('t', { username: 'new-worker', display_name: '新专员', role: 'REVIEWER', password: 'initial-pass', reason: '新增岗位' })
    expect(dialog.get('[aria-label="关闭弹窗"]').attributes('disabled')).toBeDefined()
    resolve({ account: { ...worker, username: 'new-worker', display_name: '新专员', version: 1 }, session_invalidated: false }); await flushPromises()
    expect(wrapper!.find('[role="dialog"]').exists()).toBe(false)
    expect(wrapper!.text()).toContain('工作人员已创建')
  })

  it('protects the last administrator in the UI while still allowing name maintenance and password reset', async () => {
    await start(); await open('admin')
    expect(wrapper!.get('.people-maintenance select').attributes('disabled')).toBeDefined()
    expect(wrapper!.get('.people-maintenance input[type="checkbox"]').attributes('disabled')).toBeDefined()
    expect(wrapper!.text()).toContain('最后一个启用管理员')
    expect(wrapper!.get('.people-maintenance input:not([type="checkbox"])').attributes('disabled')).toBeUndefined()
    await click('重置密码')
    expect(wrapper!.get('[role="dialog"]').text()).toContain('成功后该账号的旧会话立即失效')
    await click('取消')
    await click('重置密码')
    expect((wrapper!.get('input[type="password"]').element as HTMLInputElement).value).toBe('')
  })

  it('exits immediately when a self password reset invalidates the signed session, without another old-token request', async () => {
    const reset = vi.spyOn(coreApi, 'resetAccountPassword').mockResolvedValue({ account: { ...admin, version: 4 }, session_invalidated: true })
    await start(); await open('admin'); await click('重置密码')
    await wrapper!.get('input[type="password"]').setValue('new-admin-pass')
    await wrapper!.get('[role="dialog"] textarea').setValue('本人重置')
    await wrapper!.get('[role="dialog"] form').trigger('submit'); await flushPromises()
    expect(reset).toHaveBeenCalledExactlyOnceWith('t', admin, 'new-admin-pass', '本人重置')
    expect(wrapper!.emitted('expired')).toHaveLength(1)
    expect(coreApi.adminAccounts).toHaveBeenCalledTimes(1)
    expect(coreApi.accountHistory).toHaveBeenCalledTimes(1)
  })

  it('ignores late audit results for a previously selected account', async () => {
    let resolve!: (page: AccountAuditPage) => void
    vi.mocked(coreApi.accountHistory).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    await start(); await open(); await open('admin')
    resolve({ items: [{ id: '1', action: 'CREATED', actor_username: 'other', account_version: 1, reason: '旧账号记录', occurred_at: worker.created_at, before: null, after: { display_name: '旧姓名', role: 'REVIEWER', enabled: true } }], page: { limit: 10 }, total: 1 }); await flushPromises()
    expect(wrapper!.text()).not.toContain('旧账号记录')
    expect(wrapper!.get('[aria-label="维护账号"]').text()).toContain('商家管理员')
  })

  it('does not retry an unknown password result and clears the secret on a network failure', async () => {
    const reset = vi.spyOn(coreApi, 'resetAccountPassword').mockRejectedValue(new Error('connection lost'))
    await start(); await open(); await click('重置密码')
    await wrapper!.get('input[type="password"]').setValue('new-worker-pass')
    await wrapper!.get('[role="dialog"] textarea').setValue('维护密码')
    await wrapper!.get('[role="dialog"] form').trigger('submit'); await flushPromises()
    expect(reset).toHaveBeenCalledTimes(1)
    expect(wrapper!.text()).toContain('不要直接重复提交')
    expect((wrapper!.get('input[type="password"]').element as HTMLInputElement).value).toBe('')
    expect(wrapper!.get('[role="dialog"] button[type="submit"]').attributes('disabled')).toBeDefined()
  })

  it('exits for an expired list request, and ignores errors arriving after the page was left', async () => {
    vi.mocked(coreApi.adminAccounts).mockRejectedValueOnce(new ApiError(401, 'UNAUTHENTICATED', 'expired'))
    await start(); expect(wrapper!.emitted('expired')).toHaveLength(1)
    wrapper!.unmount(); wrapper = undefined
    let reject!: (cause: unknown) => void
    vi.mocked(coreApi.adminAccounts).mockImplementationOnce(() => new Promise((_, fail) => { reject = fail }))
    wrapper = mount(AdminPeople, { props: { account } })
    const old = wrapper; wrapper.unmount(); wrapper = undefined
    reject(new ApiError(401, 'UNAUTHENTICATED', 'late')); await flushPromises()
    expect(old.emitted('expired')).toBeUndefined()
  })
})
