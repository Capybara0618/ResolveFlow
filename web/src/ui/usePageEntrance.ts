import { onBeforeUnmount, onMounted, watch } from 'vue'
import { createPageMotion } from './page-motion'

/** Observe explicit view identities, not polling, message text or input drafts. */
export function usePageEntrance(surface: () => HTMLElement | null | undefined, view: () => string | null) {
  const motion = createPageMotion(() => surface() ?? null)
  let observer: MutationObserver | undefined
  let previousRoot: HTMLElement | null | undefined, previousKey: string | null = null
  function enter() {
    const root = surface(), key = view()
    const identity = key === null ? null : `${key}:${root?.dataset.pageKey ?? ''}`
    if (previousRoot === root && previousKey === identity) return
    observer?.disconnect(); observer = undefined
    previousRoot = root; previousKey = identity
    if (!root || identity === null) { motion.reset(); return }
    // This hook runs after Vue patches the page, keeping business handlers synchronous.
    // A child page can signal internal navigation through data-page-key on its root.
    observer = new MutationObserver(enter)
    observer.observe(root, { attributes:true, attributeFilter:['data-page-key'] })
    void motion.navigate(() => {}, { native:false })
  }
  onMounted(enter)
  watch(() => [view(), surface()], enter, { flush:'post' })
  onBeforeUnmount(() => { observer?.disconnect(); motion.dispose() })
}
