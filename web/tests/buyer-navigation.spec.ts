import { afterEach, expect, it, vi } from 'vitest'
import { beginBuyerNavigation, pushBuyerNavigation, hasBuyerPrevious } from '../src/buyer-navigation'
afterEach(() => { vi.restoreAllMocks(); window.history.replaceState(null, '', '/') })
it('starts direct entries without a previous app page and preserves unrelated listing state', () => {
  window.history.replaceState({ resolveflow_listing: { index: 1 } }, '', '#/shop/cart')
  beginBuyerNavigation('buyer')
  expect(hasBuyerPrevious('buyer')).toBe(false)
  expect(window.history.state.resolveflow_listing).toEqual({ index: 1 })
})
it('tracks actual previous app pages across refresh and avoids duplicate history entries', () => {
  window.history.replaceState(null, '', '#/shop/search?query=耳机')
  beginBuyerNavigation('buyer'); pushBuyerNavigation('#/shop/products/P-1001', 'buyer'); pushBuyerNavigation('#/shop/cart', 'buyer')
  expect(hasBuyerPrevious('buyer')).toBe(true)
  const depth = window.history.state.resolveflow_buyer_navigation.depth
  beginBuyerNavigation('buyer'); expect(hasBuyerPrevious('buyer')).toBe(true)
  pushBuyerNavigation('#/shop/cart', 'buyer'); expect(window.history.state.resolveflow_buyer_navigation.depth).toBe(depth)
})
it('does not treat a previous account or an invalid marker as app navigation', () => {
  window.history.replaceState(null, '', '#/shop'); beginBuyerNavigation('one'); pushBuyerNavigation('#/shop/cart','one')
  expect(hasBuyerPrevious('two')).toBe(false); beginBuyerNavigation('two'); expect(hasBuyerPrevious('two')).toBe(false)
  window.history.replaceState({ resolveflow_buyer_navigation: { owner: 'two', depth: -1 } }, '', '#/shop/cart')
  expect(hasBuyerPrevious('two')).toBe(false)
})
