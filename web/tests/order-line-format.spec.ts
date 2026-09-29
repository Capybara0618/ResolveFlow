import { describe, expect, it } from 'vitest'
import { paidAtOf, productNameMissing, productTitle, variantOf } from '../src/ui/order-line-format'

describe('order line presentation', () => {
  it('uses the merchant’s own product name when there is one', () => {
    expect(productTitle({ product_name: '演示商品 · 降噪耳机', sku: 'SKU-RED-M' })).toBe('演示商品 · 降噪耳机')
    expect(productNameMissing({ product_name: '演示商品 · 降噪耳机' })).toBe(false)
  })

  it('falls back to the SKU rather than inventing a product', () => {
    expect(productTitle({ product_name: null, sku: 'SKU-RED-M' })).toBe('SKU-RED-M')
    expect(productTitle({ sku: 'SKU-RED-M' })).toBe('SKU-RED-M')
    expect(productNameMissing({ product_name: null })).toBe(true)
  })

  it('states missing rather than rendering an empty heading', () => {
    expect(productTitle({ product_name: '   ', sku: '' })).toBe('商品名称未提供')
    expect(productNameMissing({ product_name: '' })).toBe(true)
  })

  it('treats a blank variant as absent, not as an empty variant', () => {
    expect(variantOf({ variant_text: '深空灰' })).toBe('深空灰')
    expect(variantOf({ variant_text: '   ' })).toBeNull()
    expect(variantOf({})).toBeNull()
  })

  it('shows a payment time only when the wire carries one', () => {
    expect(paidAtOf({ paid_at: '2026-09-10T08:15:00Z' })).toBe('2026-09-10T08:15:00Z')
    expect(paidAtOf({})).toBeNull()
    expect(paidAtOf({ paid_at: '' })).toBeNull()
  })
})
