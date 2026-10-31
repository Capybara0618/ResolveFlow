import { nextTick } from 'vue'

type Transition = { ready: Promise<void>; finished: Promise<void>; skipTransition(): void }
type MotionDocument = Document & { startViewTransition?: (update: () => Promise<void>) => Transition }
type Options = { direction?: 'forward' | 'back'; product?: string; initial?: boolean; native?: boolean }

// A transition follows navigation, never polling, text streaming or form edits.
// The old screenshot may wait briefly for data, but never for an unbounded request.
export function createPageMotion(surface: () => HTMLElement | null) {
  let generation = 0, disposed = false
  let transition: Transition | undefined
  let releaseNames = () => {}
  let stopWaiting = () => {}
  const animations = new Set<Animation>()
  const reduced = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
  const busy = () => !!surface()?.querySelector('[data-page-loading="true"], [aria-busy="true"]:not(.support-messages)')

  function cancel() {
    transition?.skipTransition(); transition = undefined
    releaseNames(); releaseNames = () => {}
    delete document.documentElement.dataset.rfNavigation
    stopWaiting(); stopWaiting = () => {}
    animations.forEach(animation => animation.cancel()); animations.clear()
  }
  function reveal(id: number, direction: Options['direction'], seen: WeakSet<HTMLElement>, regionsOnly = false) {
    const root = surface()
    if (!root || disposed || id !== generation || reduced() || typeof root.animate !== 'function') return
    // Animate a few visible regions, not every row in a long list or the chat composer.
    const visible = [...root.querySelectorAll<HTMLElement>('[data-page-reveal]')]
      .filter(element => { const box = element.getBoundingClientRect(); return box.height > 0 && box.bottom > 0 && box.top < window.innerHeight })
    const regions = visible.filter(element => !seen.has(element))
      .slice(0, 6)
    if (!regions.length && (regionsOnly || visible.length || seen.has(root))) return
    for (const [index, element] of (regions.length ? regions : [root]).entries()) {
      seen.add(element)
      const animation = element.animate([
        { opacity: .15, transform: regions.length ? `translate(${direction === 'back' ? -8 : 8}px, 6px)` : 'none' },
        { opacity: 1, transform: 'none' },
      ], { duration: 240, delay: Math.min(index * 35, 140), easing: 'cubic-bezier(.22,1,.36,1)', fill: 'backwards' })
      animations.add(animation)
      void animation.finished.catch(() => {}).finally(() => animations.delete(animation))
    }
  }
  function ready(id: number): Promise<boolean> {
    if (id !== generation || disposed) return Promise.resolve(false)
    if (!busy()) return Promise.resolve(true)
    return new Promise(resolve => {
      const observer = new MutationObserver(() => { if (!busy()) finish(true) })
      const timer = setTimeout(() => finish(false), 10000)
      function finish(value: boolean) { clearTimeout(timer); observer.disconnect(); if (stopWaiting === stop) stopWaiting = () => {}; resolve(value && id === generation && !disposed) }
      const stop = () => finish(false)
      stopWaiting = stop
      const root = surface()
      if (root) observer.observe(root, { subtree: true, childList: true, attributes: true, attributeFilter: ['aria-busy', 'data-page-loading'] })
      else finish(false)
    })
  }
  function productElement(product?: string) {
    if (!product) return undefined
    return [...surface()?.querySelectorAll<HTMLElement>('[data-motion-product]') ?? []].find(element => {
      const box = element.getBoundingClientRect()
      return element.dataset.motionProduct === product && box.bottom > 0 && box.top < window.innerHeight
    })
  }
  async function navigate(update: () => Promise<void> | void, options: Options = {}) {
    const id = ++generation
    cancel()
    const revealed = new WeakSet<HTMLElement>()
    let job: Promise<void> | undefined
    // Snapshot setup may fall back; the application update must still run once.
    const commit = () => job ??= Promise.resolve().then(() => { if (!disposed && id === generation) return update() }).then(() => nextTick())
    const doc = document as MotionDocument
    if (options.native === false || options.initial || reduced() || !doc.startViewTransition || !surface()) {
      const work = commit()
      await Promise.resolve(); await nextTick()
      reveal(id, options.direction, revealed, true)
      await work
      if (await ready(id)) reveal(id, options.direction, revealed)
      return
    }
    const names: Array<[HTMLElement, string]> = []
    const name = (element: HTMLElement | undefined | null, value: string) => {
      if (element && !names.some(([target]) => target === element)) { names.push([element, element.style.viewTransitionName]); element.style.viewTransitionName = value }
    }
    let cleaned = false
    const clean = () => { if (cleaned) return; cleaned = true; names.forEach(([element, previous]) => { element.style.viewTransitionName = previous }); if (id === generation) delete document.documentElement.dataset.rfNavigation }
    releaseNames = clean
    name(surface(), 'rf-page')
    const sharedProduct = productElement(options.product)
    name(sharedProduct, 'rf-product')
    document.documentElement.dataset.rfNavigation = options.direction ?? 'forward'
    let capturedReady = false
    let content: Promise<boolean> | undefined
    let snapshotTimer: ReturnType<typeof setTimeout> | undefined
    let completed!: () => void
    const committed = new Promise<void>(resolve => { completed = resolve })
    const render = async () => {
      // Commit begins inside the browser callback so the old screenshot is genuine.
      const work = commit()
      void work.finally(completed).catch(() => {})
      content = work.then(() => ready(id))
      // Ordinary navigation never pauses rendering for a network request. Only a
      // visible shared product may wait up to 64ms for its matching image.
      try { capturedReady = await Promise.race([content, new Promise<false>(resolve => { snapshotTimer = setTimeout(() => resolve(false), sharedProduct ? 64 : 0) })]) }
      finally { clearTimeout(snapshotTimer) }
      if (id !== generation || disposed) return
      await nextTick()
      if (capturedReady) name(productElement(options.product), 'rf-product')
    }
    let current: Transition
    try {
      current = doc.startViewTransition(render)
      transition = current
    } catch {
      clean(); releaseNames = () => {}
      await commit()
      if (await ready(id)) reveal(id, options.direction, revealed)
      return
    }
    // A rejected ready promise means snapshots could not be captured; navigation still works.
    let snapshots = true
    void current.ready.catch(() => { snapshots = false })
    void current.finished.catch(() => {}).finally(() => {
      clean()
      if (id === generation) { transition = undefined; releaseNames = () => {} }
    })
    await committed
    await job
    await current.ready.catch(() => {})
    if (!capturedReady || !snapshots) {
      if (await content) {
        if (id !== generation || disposed) return
        // Once real content is ready, release a loading-state snapshot immediately.
        // Its entrance should not wait for a picture of an empty skeleton to finish.
        current.skipTransition()
        await current.finished.catch(() => {})
        reveal(id, options.direction, revealed)
      }
    }
  }
  function dispose() { disposed = true; ++generation; cancel() }
  return { navigate, dispose }
}
