import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiRequest, ApiError, coreApi, type AdminAccount, type CustomerCaseDetail } from '../src/client'

afterEach(() => vi.unstubAllGlobals())

describe('authenticated API client', () => {
  it('uses original account versions for maintenance and reset, with credentials only in the POST body', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{}'))
    vi.stubGlobal('fetch', fetcher)
    const original = { username: 'worker/a', version: 7 } as AdminAccount
    await coreApi.updateAccount('private-token', original, { display_name: '专员', role: 'REVIEWER', enabled: true, reason: '维护' })
    await coreApi.resetAccountPassword('private-token', original, 'new-test-pass', '重置')
    for (const [url, init] of fetcher.mock.calls) {
      expect(url).toContain('/api/v1/admin/accounts/worker%2Fa')
      expect(url).not.toContain('private-token'); expect(url).not.toContain('new-test-pass')
      expect(init.headers.get('Authorization')).toBe('Bearer private-token')
      expect(init.headers.get('If-Match')).toBe('"7"')
      expect(init.method).toBe('POST')
      expect(JSON.parse(init.body)).not.toHaveProperty('merchant_id')
      expect(JSON.parse(init.body)).not.toHaveProperty('customer_id')
    }
  })
  it('uses the private customer projection and versions a question answer', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{}'))
    vi.stubGlobal('fetch', fetcher)
    await coreApi.customerCases('private-token', 'WAITING', 'a+b/c')
    await coreApi.customerCase('private-token', 'case/a')
    await coreApi.answerQuestion('private-token', { case: { case_id: 'case/a', version: 7 } } as CustomerCaseDetail, 'q-1', '承运商回复')
    expect(fetcher.mock.calls[0][0]).toBe('/api/v1/customer/cases?view=WAITING&limit=20&cursor=a%2Bb%2Fc')
    expect(fetcher.mock.calls[1][0]).toBe('/api/v1/customer/cases/case%2Fa')
    const [url, options] = fetcher.mock.calls[2]
    expect(url).toBe('/api/v1/customer/cases/case%2Fa/answers')
    expect(new Headers(options.headers).get('If-Match')).toBe('"7"')
    expect(JSON.parse(options.body)).toEqual({ question_id: 'q-1', text: '承运商回复' })
    expect(fetcher.mock.calls.every(([path]) => !path.includes('private-token'))).toBe(true)
  })
  it('sends the token in a header and never in the URL', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200 }))
    vi.stubGlobal('fetch', fetcher)
    const value = await apiRequest<{ items: unknown[] }>('/api/v1/orders?limit=20', 'test-token')
    expect(value.items).toEqual([])
    const [url, options] = fetcher.mock.calls[0]
    expect(url).toBe('/api/v1/orders?limit=20')
    expect(new Headers(options.headers).get('Authorization')).toBe('Bearer test-token')
  })

  it('preserves the server refusal instead of treating it as an empty result', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: 'CASE_NOT_FOUND' }), {
      status: 404,
    })))
    await expect(apiRequest('/api/v1/cases/hidden', 'test-token')).rejects.toMatchObject({
      status: 404,
      code: 'CASE_NOT_FOUND',
    } satisfies Partial<ApiError>)
  })
})
