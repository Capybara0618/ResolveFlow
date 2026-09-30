import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App.vue'
import { watchCaseEvents } from '../src/events'

vi.mock('../src/events', () => ({ watchCaseEvents: vi.fn().mockResolvedValue(undefined) }))

afterEach(() => vi.unstubAllGlobals())

describe('core workbench', () => {
  it('refreshes reviewer permissions and execution details when SSE advances the case', async () => {
    let version = 1
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      let body: unknown
      if (url.endsWith('/auth/login')) body = { access_token: 't', role: 'REVIEWER', merchant_id: 'M-1' }
      else if (url.startsWith('/api/v1/review/cases')) body = { items: [{ case_id: 'case-sse', line_id: 'l' }], page: {} }
      else if (url === '/api/v1/cases/case-sse') body = {
        case: { case_id: 'case-sse', line_id: 'l', input_revision: 1, version,
          status: version === 1 ? 'PENDING_REVIEW' : 'CLOSED_SUCCESS' }, evidence: [], timeline: [],
      }
      else if (url.endsWith('/review-context')) body = {
        case_version: version, input_revision: 1, allowed_actions: version === 1 ? ['MANUAL_PROPOSAL'] : [],
        blocked_reason: version === 1 ? '' : '工单已结束，仅可查看记录', policy_rules: [], policy_status: 'PINNED',
        execution: { case_status: version === 1 ? 'PENDING_REVIEW' : 'CLOSED_SUCCESS', operation_id: 'op',
          outcome: version === 1 ? null : 'SUCCEEDED', amount_minor: 32900, reason_code: null },
      }
      else if (url.endsWith('/investigation')) body = { case_id: 'case-sse', input_revision: 1, availability: 'NOT_SCHEDULED' }
      else throw new Error(`Unexpected URL ${url}`)
      return Promise.resolve(new Response(JSON.stringify(body)))
    }))
    const wrapper = mount(App)
    await wrapper.get('[name="username"]').setValue('reviewer')
    await wrapper.get('[name="password"]').setValue('password')
    await wrapper.get('.login-panel').trigger('submit')
    await flushPromises()
    expect(wrapper.find('[data-test="manual-proposal"]').exists()).toBe(true)
    version = 2
    vi.mocked(watchCaseEvents).mock.calls.at(-1)![2]({ id: 'event-final', event: 'case.updated', data: '{}' })
    await flushPromises()
    expect(wrapper.find('[data-test="manual-proposal"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('工单已结束，仅可查看记录')
    expect(wrapper.find('[aria-label="退款执行结果"]').text()).toContain('模拟退款成功')
    wrapper.unmount()
  })

  it('separates a reviewer queue, case detail, and server-backed context without inventing customer data', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/auth/login')) return Promise.resolve(new Response(JSON.stringify({
        access_token: 'reviewer-token', role: 'REVIEWER', merchant_id: 'M-1', expires_in: 3600,
      })))
      if (url.startsWith('/api/v1/review/cases')) return Promise.resolve(new Response(JSON.stringify({
        items: [{ case_id: 'case-2', status: 'PENDING_REVIEW', version: 7, line_id: 'line-9',
          description: '耳机充电后仍无法开机，申请退款', updated_at: '2026-09-28T02:00:00Z' }], page: { limit: 20 },
      })))
      if (url === '/api/v1/cases/case-2') return Promise.resolve(new Response(JSON.stringify({
        case: { case_id: 'case-2', status: 'PENDING_REVIEW', input_revision: 2, version: 7, line_id: 'line-9',
          order_id: 'order-4', description: '耳机充电后仍无法开机，申请退款' },
        authorization: { authorization_id: 'auth-2', authorization_version: 3, status: 'PENDING_REVIEW', input_revision: 2 },
        evidence: [
          { observation_id: 'ev-1', evidence_kind: 'CUSTOMER_STATEMENT', content: '充电两小时仍不开机',
            source_ref: 'customer:C-9', observed_at: '2026-09-28T01:50:00Z' },
          { observation_id: 'ev-2', evidence_kind: 'REVIEWER_VERIFICATION', content: '已检查充电记录',
            source_ref: 'reviewer:R-1', reviewed_evidence_id: 'ev-1', verification_result: 'CONFIRMED' },
        ],
        proposal: { origin: 'HUMAN', recommended_action: 'REFUND', summary: '建议退款',
          status: 'VALIDATED', recomputed_amount_minor: 32900,
          evidence_refs: [{ observation_id: 'ev-1', source_ref: 'customer:C-9', source_version: '1' }],
          policy_refs: [{ bundle_id: 'refund-v2', version: '2', rule_id: 'QUALITY_7D', chunk_id: 'c-1' }] },
        timeline: [],
      })))
      if (url === '/api/v1/orders/order-4') return Promise.resolve(new Response(JSON.stringify({
        items: [{ order_id: 'order-4', line_id: 'line-9', sku: 'HEADPHONE-PRO', category: 'electronics',
          quantity: 1, line_paid_amount: 32900, currency: 'CNY', status: 'PAID' }], page: { limit: 20 },
      })))
      throw new Error(`Unexpected URL ${url}`)
    }))
    const wrapper = mount(App)
    await wrapper.get('[name="username"]').setValue('reviewer')
    await wrapper.get('[name="password"]').setValue('password')
    await wrapper.get('.login-panel').trigger('submit')
    await flushPromises()
    expect(wrapper.find('nav[aria-label="工作台导航"]').exists()).toBe(true)
    expect(wrapper.get('.queue-row').text()).toContain('耳机充电后仍无法开机')
    expect(wrapper.get('.queue-row').text()).not.toContain('case-2')
    expect(wrapper.find('section[aria-label="审核队列"]').text()).not.toContain('2026-09-28T02:00:00Z')
    expect(wrapper.get('.queue-row').classes()).toContain('selected')
    expect(wrapper.get('.case-title h3').text()).toContain('耳机充电后仍无法开机')
    expect(wrapper.find('section[aria-label="工单内容"]').text()).toContain('待人工审核')
    expect(wrapper.find('aside[aria-label="工单上下文"]').text()).toContain('case-2')
    expect(wrapper.get('.case-order').text()).toContain('电子产品')
    expect(wrapper.get('.case-order').text()).toContain('329.00 CNY')
    expect(wrapper.get('.case-order').text()).toContain('HEADPHONE-PRO')
    expect(wrapper.get('.case-order').text()).toContain('订单已付金额')
    expect(wrapper.get('.evidence').text()).toContain('客户陈述')
    expect(wrapper.get('.evidence').text()).toContain('customer:C-9')
    expect(wrapper.findAll('.evidence')[0].text()).toContain('已核验：确认')
    expect(wrapper.findAll('.evidence')[0].findAll('button')).toHaveLength(0)
    expect(wrapper.findAll('.evidence')[1].text()).toContain('确认')
    expect(wrapper.findAll('.evidence')[1].findAll('button')).toHaveLength(0)
    expect(wrapper.get('.proposal').text()).toContain('customer:C-9')
    expect(wrapper.get('.proposal').text()).toContain('QUALITY_7D')
    expect(wrapper.get('.proposal h3').text()).toContain('人工方案')
    expect(wrapper.findAll('.context-panel')[1].text()).toContain('待审退款额')
    expect(wrapper.find('.analysis-grid').exists()).toBe(true)
    expect(wrapper.find('aside[aria-label="工单上下文"]').text()).toContain('auth-2')
    expect(wrapper.text()).not.toContain('会员等级')
    await wrapper.get('[data-test="approve"]').trigger('click')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    await wrapper.get('[role="dialog"]').trigger('keydown', { key: 'Escape' })
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/reviews'))).toBe(false)
    wrapper.unmount()
  })

  it('starts with login and renders only scoped API order lines', async () => {
    const fetcher = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/auth/login')) return Promise.resolve(new Response(JSON.stringify({
        access_token: 'token', role: 'CUSTOMER', merchant_id: 'M-1001', customer_id: 'C-2002', expires_in: 3600,
      })))
      if (url.startsWith('/api/v1/orders')) return Promise.resolve(new Response(JSON.stringify({
        items: [
          { order_id: 'order-1', line_id: 'line-7', sku: 'demo', product_name: '演示商品 · 保温杯',
            variant_text: '雾蓝 · 500ml', category: 'other', quantity: 1, line_paid_amount: 2599,
            currency: 'CNY', paid_at: '2026-09-20T02:30:00Z', status: 'PAID' },
          // A line that predates the display columns: absent members, not empty ones.
          { order_id: 'order-1', line_id: 'line-8', sku: 'SKU-ONLY-8', category: 'other', quantity: 1,
            line_paid_amount: 1299, currency: 'CNY', status: 'PAID' },
        ], page: { limit: 20 },
      })))
      throw new Error(`Unexpected URL ${url}`)
    })
    vi.stubGlobal('fetch', fetcher)
    const wrapper = mount(App)
    expect(wrapper.text()).toContain('登录')
    expect(wrapper.text()).not.toContain('c-9001')
    await wrapper.get('[name="username"]').setValue('customer')
    await wrapper.get('[name="password"]').setValue('password')
    await wrapper.get('.login-panel').trigger('submit')
    await flushPromises()
    // The product name is the heading, the variant is the second line, and the SKU stays visible
    // as the merchant's own identifier.
    const rows = wrapper.findAll('.order-row')
    expect(rows[0].get('[data-test="order-product"]').text()).toBe('演示商品 · 保温杯')
    expect(rows[0].get('[data-test="order-variant"]').text()).toBe('雾蓝 · 500ml')
    expect(rows[0].text()).toContain('demo')
    expect(rows[0].text()).toContain('25.99 CNY')
    expect(rows[0].get('[data-test="order-paid-at"]').text()).toContain('支付于')
    // A line with no product name says so and still shows its SKU; it never invents a name.
    expect(rows[1].get('[data-test="order-product"]').text()).toBe('SKU-ONLY-8')
    expect(rows[1].get('[data-test="order-product"]').classes()).toContain('name-missing')
    expect(rows[1].find('[data-test="order-variant"]').exists()).toBe(false)
    expect(rows[1].find('[data-test="order-paid-at"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('RESHIP')
    wrapper.unmount()
  })

  it('keeps the case usable while optional order context is slow', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/auth/login')) return Promise.resolve(new Response(JSON.stringify({
        access_token: 'reviewer-token', role: 'REVIEWER', merchant_id: 'M-1', expires_in: 3600,
      })))
      if (url.startsWith('/api/v1/review/cases')) return Promise.resolve(new Response(JSON.stringify({
        items: [{ case_id: 'case-slow', status: 'PENDING_REVIEW', version: 2, line_id: 'line-9',
          description: '包裹未收到', updated_at: '2026-09-28T02:00:00Z' }], page: { limit: 20 },
      })))
      if (url === '/api/v1/cases/case-slow') return Promise.resolve(new Response(JSON.stringify({
        case: { case_id: 'case-slow', status: 'PENDING_REVIEW', input_revision: 1, version: 2,
          line_id: 'line-9', order_id: 'order-slow', description: '包裹未收到' }, timeline: [],
      })))
      if (url === '/api/v1/orders/order-slow') return new Promise<Response>(() => {})
      throw new Error(`Unexpected URL ${url}`)
    }))
    const wrapper = mount(App)
    await wrapper.get('[name="username"]').setValue('reviewer')
    await wrapper.get('[name="password"]').setValue('password')
    await wrapper.get('.login-panel').trigger('submit')
    await flushPromises()
    expect(wrapper.get('.case-title h3').text()).toBe('包裹未收到')
    expect(wrapper.get('.case-order').text()).toContain('正在读取订单信息')
    expect(wrapper.get('.review-unavailable').text()).toContain('暂无可审核授权')
    expect(wrapper.get('.list-actions button').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('explains that a consumed authorization cannot be approved again after a failed execution', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/auth/login')) return Promise.resolve(new Response(JSON.stringify({
        access_token: 'reviewer-token', role: 'REVIEWER', merchant_id: 'M-1', expires_in: 3600,
      })))
      if (url.startsWith('/api/v1/review/cases')) return Promise.resolve(new Response(JSON.stringify({
        items: [{ case_id: 'case-failed', status: 'PENDING_REVIEW', line_id: 'line-9' }], page: { limit: 20 },
      })))
      if (url === '/api/v1/cases/case-failed') return Promise.resolve(new Response(JSON.stringify({
        case: { case_id: 'case-failed', status: 'PENDING_REVIEW', input_revision: 1, version: 9, line_id: 'line-9' },
        authorization: { authorization_id: 'auth-old', authorization_version: 4, status: 'CONSUMED', input_revision: 1 },
        timeline: [{ event_id: 'event-1', type: 'EXECUTION_UPDATED', occurred_at: '2026-09-28T02:00:00Z', summary: '退款执行失败' }],
      })))
      throw new Error(`Unexpected URL ${url}`)
    }))
    const wrapper = mount(App)
    await wrapper.get('[name="username"]').setValue('reviewer')
    await wrapper.get('[name="password"]').setValue('password')
    await wrapper.get('.login-panel').trigger('submit')
    await flushPromises()
    expect(wrapper.get('.review-unavailable').text()).toContain('已消费')
    expect(wrapper.find('[data-test="approve"]').exists()).toBe(false)
    expect(wrapper.find('aside[aria-label="工单上下文"]').text()).toContain('已消费')
    wrapper.unmount()
  })

  it('shows a server refusal instead of silently presenting a successful login', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      code: 'INVALID_CREDENTIALS', message: 'wrong password',
    }), { status: 401 })))
    const wrapper = mount(App)
    await wrapper.get('[name="username"]').setValue('customer')
    await wrapper.get('[name="password"]').setValue('bad')
    await wrapper.get('.login-panel').trigger('submit')
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
    await wrapper.get('.login-panel').trigger('submit')
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

  it.each([
    ['批准授权', 'APPROVE'], ['请求补证', 'REQUEST_INFO'], ['拒绝', 'REJECT'],
  ])('confirms %s using the versions reviewed before a live update', async (label, decision) => {
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
    await wrapper.get('.login-panel').trigger('submit')
    await flushPromises()
    await wrapper.findAll('.review-section button').find(button => button.text().includes(label))!.trigger('click')
    expect(fetcher.mock.calls.some(([url]) => url.endsWith('/reviews'))).toBe(false)
    expect(wrapper.get('[data-test="confirm-review"]').attributes('disabled')).toBeDefined()
    snapshot.case.version = 8
    snapshot.authorization.authorization_version = 4
    vi.mocked(watchCaseEvents).mock.calls.at(-1)![2]({ id: 'event-2', event: 'case.updated', data: '{}' })
    await flushPromises()
    await wrapper.get('[role="dialog"] textarea').setValue('材料和金额已核实')
    await wrapper.get('[data-test="confirm-review"]').trigger('click')
    await flushPromises()
    const review = fetcher.mock.calls.find(([url]) => url === '/api/v1/cases/case-2/reviews')!
    expect(new Headers(review[1].headers).get('If-Match')).toBe('"7"')
    expect(JSON.parse(review[1].body)).toEqual({
      authorization_id: 'auth-2', authorization_version: 3, decision, reason: '材料和金额已核实',
    })
    wrapper.unmount()
  })

  it('reloads a changed case after a stale review decision instead of reusing old versions', async () => {
    let reads = 0
    const fetcher = vi.fn().mockImplementation((url: string, options: RequestInit) => {
      if (url.endsWith('/auth/login')) return Promise.resolve(new Response(JSON.stringify({
        access_token: 'reviewer-token', role: 'REVIEWER', merchant_id: 'M-1', expires_in: 3600,
      })))
      if (url.startsWith('/api/v1/review/cases')) return Promise.resolve(new Response(JSON.stringify({
        items: [{ case_id: 'case-3', status: 'PENDING_REVIEW', version: 7, line_id: 'line-9' }],
        page: { limit: 20 },
      })))
      if (url === '/api/v1/cases/case-3') {
        reads++
        return Promise.resolve(new Response(JSON.stringify({
          case: { case_id: 'case-3', status: 'PENDING_REVIEW', input_revision: 2, version: reads === 1 ? 7 : 8,
            line_id: 'line-9' },
          authorization: { authorization_id: 'auth-3', authorization_version: reads === 1 ? 3 : 4,
            status: 'PENDING_REVIEW', input_revision: 2 },
          timeline: [],
        })))
      }
      if (url === '/api/v1/cases/case-3/reviews' && options.method === 'POST') {
        return Promise.resolve(new Response(JSON.stringify({ code: 'STALE_VERSION', message: 'conflict' }), { status: 409 }))
      }
      throw new Error(`Unexpected URL ${url}`)
    })
    vi.stubGlobal('fetch', fetcher)
    const wrapper = mount(App)
    await wrapper.get('[name="username"]').setValue('reviewer')
    await wrapper.get('[name="password"]').setValue('password')
    await wrapper.get('.login-panel').trigger('submit')
    await flushPromises()
    await wrapper.get('[data-test="approve"]').trigger('click')
    await wrapper.get('[role="dialog"] textarea').setValue('原审核理由')
    await wrapper.get('[data-test="confirm-review"]').trigger('click')
    await flushPromises()
    expect(reads).toBe(2)
    expect(wrapper.get('[role="alert"]').text()).toContain('重新加载')
    expect(wrapper.find('aside[aria-label="工单上下文"]').text()).toContain('4')
    wrapper.unmount()
  })
})
