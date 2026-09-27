import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiRequest, ApiError } from '../src/client'

afterEach(() => vi.unstubAllGlobals())

describe('authenticated API client', () => {
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
