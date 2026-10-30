type Marker = { owner: string; depth: number }
const key = 'resolveflow_buyer_navigation'
function marker(owner: string): Marker | null {
  const value = window.history.state?.[key]
  return value?.owner === owner && Number.isSafeInteger(value.depth) && value.depth >= 0 ? value : null
}
/** Mark only navigation made inside this buyer session; direct links never leave the app on Back. */
export function beginBuyerNavigation(owner: string): void {
  if (!marker(owner)) window.history.replaceState({ ...window.history.state, [key]: { owner, depth: 0 } }, '')
}
export function hasBuyerPrevious(owner: string): boolean { return (marker(owner)?.depth ?? 0) > 0 }
export function pushBuyerNavigation(hash: string, owner: string): void {
  beginBuyerNavigation(owner)
  if (hash === window.location.hash) return
  window.history.pushState({ [key]: { owner, depth: marker(owner)!.depth + 1 } }, '', hash)
}
