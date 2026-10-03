import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { coreApi, type OrderLine } from '../src/client'
import { useAftercareProducts } from '../src/ui/aftercare-products'

const line = (id: string): OrderLine => ({ line_id: id, order_id: 'order', sku: 'sku', product_name: '商品',
  category: 'electronics', quantity: 1, line_paid_amount: 32900, currency: 'CNY', status: 'PAID', asset_key: 'headphones' })
beforeEach(() => vi.spyOn(coreApi, 'orderLine').mockImplementation(async (_, id) => line(id)))
afterEach(() => vi.restoreAllMocks())

describe('independent scoped aftercare product reads', () => {
  it('keeps at most four reads active and reuses accurate line data on polling', async () => {
    let active = 0, peak = 0
    vi.mocked(coreApi.orderLine).mockImplementation(async (_, id) => {
      peak = Math.max(peak, ++active); await Promise.resolve(); --active; return line(id)
    })
    const cache = useAftercareProducts(() => 'buyer')
    await cache.readMany(['1', '2', '3', '4', '5', '6', '1'])
    expect(peak).toBe(4); expect(coreApi.orderLine).toHaveBeenCalledTimes(6)
    await cache.readMany(['1', '2']); expect(coreApi.orderLine).toHaveBeenCalledTimes(6)
    expect(cache.lines.value['1'].asset_key).toBe('headphones')
  })
  it('discards a late former session response without disturbing a new session read', async () => {
    let identity = 'buyer-a', complete!: (value: OrderLine) => void
    vi.mocked(coreApi.orderLine).mockImplementationOnce(() => new Promise(resolve => { complete = resolve }))
    const cache = useAftercareProducts(() => identity), stale = cache.read('1')
    identity = 'buyer-b'; cache.reset(); await cache.read('1')
    complete({ ...line('1'), product_name: '旧会话商品' }); await stale
    expect(cache.lines.value['1'].product_name).toBe('商品'); expect(cache.states.value['1']).toBe('ready')
  })
  it('does not invent a product on failure or wrong-line response and supports explicit retry', async () => {
    vi.mocked(coreApi.orderLine).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(line('foreign'))
    const cache = useAftercareProducts(() => 'buyer')
    await cache.read('1'); expect(cache.states.value['1']).toBe('unavailable'); expect(cache.lines.value['1']).toBeUndefined()
    await cache.read('1'); expect(coreApi.orderLine).toHaveBeenCalledTimes(1)
    await cache.read('1', true); expect(cache.lines.value['1']).toBeUndefined()
    await cache.read('1', true); expect(cache.lines.value['1']).toEqual(line('1'))
  })
})
