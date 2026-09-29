/**
 * How an order line is presented, and what is shown when a member is absent.
 *
 * `product_name` and `variant_text` are optional members on the core `OrderLineSummary`
 * (tasks/dsh-reviewer/05-fields-visual.md section 2). A line that predates them answers null, and
 * a merchant that recorded nothing answers null too — the page must not fill either in. So the
 * rule this module keeps is the one the contract states: **absent means the reader falls back, not
 * the page invents**. The fallback is the SKU, which is real data, and when there is no product
 * name at all the page says so in words rather than showing a plausible-looking placeholder as if
 * it were the product.
 *
 * Nothing here reads the network, and nothing here decides anything about money: the amounts the
 * page shows come from the server's own fields.
 */

import type { OrderLine } from '../client'

function present(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value.trim() : null
}

/** The merchant's own product name, or null when the line carries none. */
export function productNameOf(line: Pick<OrderLine, 'product_name'>): string | null {
  return present(line.product_name)
}

/** The variant the customer chose, or null. Whitespace is absence, not an empty variant. */
export function variantOf(line: Pick<OrderLine, 'variant_text'>): string | null {
  return present(line.variant_text)
}

/**
 * The heading for one line: the product name when there is one, otherwise the SKU.
 *
 * A reviewer still needs to recognise the line, and the SKU is the identifier the merchant's own
 * records use. When neither exists the page says "商品名称未提供" instead of rendering an empty
 * heading that looks like a rendering bug.
 */
export function productTitle(line: Pick<OrderLine, 'product_name' | 'sku'>): string {
  return productNameOf(line) ?? present(line.sku) ?? '商品名称未提供'
}

/** True when the heading is the explicit "not provided" text rather than a product name. */
export function productNameMissing(line: Pick<OrderLine, 'product_name'>): boolean {
  return productNameOf(line) === null
}

/** The payment time the wire already carries, or null when the line has none. */
export function paidAtOf(line: Pick<OrderLine, 'paid_at'>): string | null {
  return present(line.paid_at)
}
