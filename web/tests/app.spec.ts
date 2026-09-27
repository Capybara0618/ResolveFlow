import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App.vue'

vi.mock('../src/events', () => ({ watchCaseEvents: vi.fn().mockResolvedValue(undefined) }))

afterEach(() => vi.unstubAllGlobals())

describe('core workbench', () => {
  it('starts with login and renders only scoped API order lines', async () => {
    const fetcher = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/auth/login')) return Promise.resolve(new Response(JSON.stringify({
        access_token: 'token', role: 'CUSTOMER', merchant_id: 'M-1001', customer_id: 'C-2002', expires_in: 3600,
      })))
      if (url.startsWith('/api/v1/orders')) return Promise.resolve(new Response(JSON.stringify({
        items: [{ order_id: 'order-1', line_id: 'line-7', sku: 'demo', category: 'other', quantity: 1,
          line_paid_amount: 2599, currency: 'CNY', status: 'PAID' }], page: { limit: 20 },
      })))
      throw new Error(`Unexpected URL ${url}`)
    })
    vi.stubGlobal('fetch', fetcher)
    const wrapper = mount(App)
    expect(wrapper.text()).toContain('登录')
    expect(wrapper.text()).not.toContain('c-9001')
    await wrapper.get('[name="username"]').setValue('customer')
    await wrapper.get('[name="password"]').setValue('password')
    await wrapper.get('[data-test="login"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('line-7')
    expect(wrapper.text()).toContain('25.99 CNY')
    expect(wrapper.text()).not.toContain('RESHIP')
    wrapper.unmount()
  })

  it('shows a server refusal instead of silently presenting a successful login', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      code: 'INVALID_CREDENTIALS', message: 'wrong password',
    }), { status: 401 })))
    const wrapper = mount(App)
    await wrapper.get('[name="username"]').setValue('customer')
    await wrapper.get('[name="password"]').setValue('bad')
    await wrapper.get('[data-test="login"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('wrong password')
    expect(wrapper.text()).not.toContain('订单行')
    wrapper.unmount()
  })

  it('creates only a full-line REFUND case with an idempotency key', async () => {
    vi.stubGlobal('crypto', { randomUUID: () => 'key-1' })
    const fetcher = vi.fn().mockImplementation((url: string, options: RequestInit) => {
      if (url.endsWith('/auth/login')) return Promise.resolve(new Response(JSON.stringify({
        access_token: 'token', role: 'CUSTOMER', merchant_id: 'M-1', expires_in: 3600,
      })))
      if (url.startsWith('/api/v1/orders')) return Promise.resolve(new Response(JSON.stringify({
        items: [{ order_id: 'o-1', line_id: 'line-7', sku: 'demo', line_paid_amount: 2599, currency: 'CNY',
          status: 'PAID' }], page: { limit: 20 },
      })))
      if (url === '/api/v1/cases' && options.method === 'POST') return Promise.resolve(new Response(JSON.stringify({
        case_id: 'case-1',
      }), { status: 201 }))
      if (url === '/api/v1/cases/case-1') return Promise.resolve(new Response(JSON.stringify({
        case: { case_id: 'case-1', status: 'CLOSED_REJECTED', input_revision: 1, version: 2, line_id: 'line-7' },
        evidence: [], timeline: [],
      })))
      throw new Error(`Unexpected URL ${url}`)
    })
    vi.stubGlobal('fetch', fetcher)
    const wrapper = mount(App)
    await wrapper.get('[name="username"]').setValue('customer')
    await wrapper.get('[name="password"]').setValue('password')
    await wrapper.get('[data-test="login"]').trigger('click')
    await flushPromises()
    await wrapper.get('[name="line"]').setValue('line-7')
    await wrapper.get('textarea').setValue('包裹未到')
    await wrapper.get('[data-test="create-case"]').trigger('click')
    await flushPromises()
    const create = fetcher.mock.calls.find(([url, options]) => url === '/api/v1/cases' && options.method === 'POST')!
    expect(JSON.parse(create[1].body)).toEqual({
      line_id: 'line-7', description: '包裹未到', requested_actions: ['REFUND'],
    })
    expect(new Headers(create[1].headers).get('Idempotency-Key')).toBe('key-1')
    expect(wrapper.text()).toContain('case-1')
    wrapper.unmount()
  })

  it('submits reviewer decision with both case and authorization versions', async () => {
    const snapshot = {
      case: { case_id: 'case-2', status: 'PENDING_REVIEW', input_revision: 2, version: 7, line_id: 'line-9' },
      authorization: { authorization_id: 'auth-2', authorization_version: 3, status: 'PENDING_REVIEW', input_revision: 2 },
      evidence: [], timeline: [],
    }
    const fetcher = vi.fn().mockImplementation((url: string, options: RequestInit) => {
      if (url.endsWith('/auth/login')) return Promise.resolve(new Response(JSON.stringify({
        access_token: 'reviewer-token', role: 'REVIEWER', merchant_id: 'M-1', expires_in: 3600,
      })))
      if (url.startsWith('/api/v1/review/cases')) return Promise.resolve(new Response(JSON.stringify({
        items: [{ case_id: 'case-2', status: 'PENDING_REVIEW', version: 7, line_id: 'line-9' }],
        page: { limit: 20 },
      })))
      if (url === '/api/v1/cases/case-2/reviews' && options.method === 'POST') return Promise.resolve(new Response('{}'))
      if (url === '/api/v1/cases/case-2') return Promise.resolve(new Response(JSON.stringify(snapshot)))
      throw new Error(`Unexpected URL ${url}`)
    })
    vi.stubGlobal('fetch', fetcher)
    const wrapper = mount(App)
    await wrapper.get('[name="username"]').setValue('reviewer')
    await wrapper.get('[name="password"]').setValue('password')
    await wrapper.get('[data-test="login"]').trigger('click')
    await flushPromises()
    await wrapper.get('.queue-row').trigger('click')
    await flushPromises()
    await wrapper.get('.case-panel textarea').setValue('材料和金额已核实')
    await wrapper.get('[data-test="approve"]').trigger('click')
    await flushPromises()
    const review = fetcher.mock.calls.find(([url]) => url === '/api/v1/cases/case-2/reviews')!
    expect(new Headers(review[1].headers).get('If-Match')).toBe('"7"')
    expect(JSON.parse(review[1].body)).toEqual({
      authorization_id: 'auth-2', authorization_version: 3, decision: 'APPROVE', reason: '材料和金额已核实',
    })
    wrapper.unmount()
  })
})
