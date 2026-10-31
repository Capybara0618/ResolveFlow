import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createPageMotion } from '../src/ui/page-motion'

let root: HTMLElement
let motion: ReturnType<typeof createPageMotion>
beforeEach(() => {
  vi.useFakeTimers()
  root = document.createElement('div'); document.body.append(root)
  motion = createPageMotion(() => root)
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false })))
})
afterEach(() => { motion.dispose(); root.remove(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); delete (document as any).startViewTransition })

function native() {
  const callbacks: Array<() => Promise<void>> = []
  const transitions: Array<{ ready: Promise<void>; finished: Promise<void>; skipTransition: ReturnType<typeof vi.fn>; capture: () => Promise<void>; finish: () => void }> = []
  ;(document as any).startViewTransition = vi.fn((update: () => Promise<void>) => {
    callbacks.push(update)
    let ready!: () => void, finish!: () => void
    const transition = { ready: new Promise<void>(resolve => { ready = resolve }), finished: new Promise<void>(resolve => { finish = resolve }), skipTransition: vi.fn(), capture: async () => { await update(); ready() }, finish: () => finish() }
    transitions.push(transition)
    return transition
  })
  return { callbacks, transitions }
}

it('takes the old snapshot before committing and restores existing inline styles', async () => {
  const { transitions } = native()
  root.style.viewTransitionName = 'previous'
  root.textContent = '旧页面'
  const update = vi.fn(() => { root.textContent = '新页面' })
  const navigation = motion.navigate(update, { direction: 'back' })
  expect(root.textContent).toBe('旧页面'); expect(update).not.toHaveBeenCalled()
  expect(document.documentElement.dataset.rfNavigation).toBe('back')
  await transitions[0].capture(); await navigation
  expect(update).toHaveBeenCalledTimes(1); expect(root.textContent).toBe('新页面')
  transitions[0].finish(); await Promise.resolve(); await Promise.resolve()
  expect(root.style.viewTransitionName).toBe('previous')
})

it('releases the screenshot after 64ms while a slow request continues', async () => {
  const { transitions } = native()
  const image = document.createElement('div'); image.dataset.motionProduct = 'P-1'; root.append(image)
  vi.spyOn(image, 'getBoundingClientRect').mockReturnValue({ top: 10, bottom: 200 } as DOMRect)
  let finishRead!: () => void
  const navigation = motion.navigate(async () => {
    root.innerHTML = '<main aria-busy="true">正在读取</main>'
    await new Promise<void>(resolve => { finishRead = resolve })
    root.innerHTML = '<main aria-busy="false">商品内容</main>'
  }, { product:'P-1' })
  const capture = transitions[0].capture()
  await vi.advanceTimersByTimeAsync(64); await capture
  expect(root.textContent).toBe('正在读取')
  transitions[0].finish(); finishRead(); await navigation
  expect(root.textContent).toBe('商品内容')
})

it('waits for a child workspace to finish its first read without watching stream text', async () => {
  const { transitions } = native()
  const navigation = motion.navigate(() => { root.innerHTML = '<main data-page-loading="true"></main><div class="support-messages" aria-busy="true"></div>' })
  const capture = transitions[0].capture(); await Promise.resolve(); await Promise.resolve()
  root.querySelector('main')!.setAttribute('data-page-loading', 'false')
  await capture; await navigation
  transitions[0].finish()
})

it('drops a queued obsolete navigation and does not let its cleanup erase the current names', async () => {
  const { transitions } = native()
  const oldUpdate = vi.fn()
  const first = motion.navigate(oldUpdate)
  const second = motion.navigate(() => { root.textContent = '最终页面' })
  expect(transitions[0].skipTransition).toHaveBeenCalledTimes(1)
  await transitions[0].capture(); transitions[0].finish(); await first
  expect(oldUpdate).not.toHaveBeenCalled()
  expect(root.style.viewTransitionName).toBe('rf-page')
  await transitions[1].capture(); transitions[1].finish(); await second
  expect(root.textContent).toBe('最终页面')
})

it('honors reduced motion and does not invoke either animation API', async () => {
  native()
  vi.mocked(window.matchMedia).mockReturnValue({ matches: true } as MediaQueryList)
  const animate = vi.fn(); root.animate = animate
  await motion.navigate(() => { root.textContent = '内容' })
  expect((document as any).startViewTransition).not.toHaveBeenCalled()
  expect(animate).not.toHaveBeenCalled()
  expect(root.textContent).toBe('内容')
})

it('falls back when capture is unavailable and commits a write callback only once', async () => {
  ;(document as any).startViewTransition = vi.fn(() => { throw new Error('capture unavailable') })
  const update = vi.fn(() => { root.textContent = '内容' })
  await motion.navigate(update)
  expect(update).toHaveBeenCalledTimes(1)
  expect(root.style.viewTransitionName).toBe('')
})

it('cancels a pending readiness observer on disposal', async () => {
  const pending = motion.navigate(() => { root.innerHTML = '<main aria-busy="true"></main>' })
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
  motion.dispose(); await pending
  expect(vi.getTimerCount()).toBe(0)
})

it('clears native state when a subsequent navigation uses reduced motion', async () => {
  const { transitions } = native()
  const first = motion.navigate(() => {})
  vi.mocked(window.matchMedia).mockReturnValue({ matches: true } as MediaQueryList)
  await motion.navigate(() => { root.textContent = '减少动态效果' })
  expect(document.documentElement.dataset.rfNavigation).toBeUndefined()
  expect(root.style.viewTransitionName).toBe('')
  await transitions[0].capture(); transitions[0].finish(); await first
  expect(root.textContent).toBe('减少动态效果')
})

it('matches only the selected product image across the captured pages', async () => {
  const { transitions } = native()
  const product = () => { const e = document.createElement('div'); e.dataset.motionProduct = 'P-1'; vi.spyOn(e,'getBoundingClientRect').mockReturnValue({top:100,bottom:300} as DOMRect); return e }
  const previous = product(); root.append(previous)
  let next!: HTMLElement
  const navigation = motion.navigate(() => { next = product(); root.replaceChildren(next) }, { product:'P-1' })
  expect(previous.style.viewTransitionName).toBe('rf-product')
  await transitions[0].capture(); await navigation
  expect(next.style.viewTransitionName).toBe('rf-product')
  transitions[0].finish(); await Promise.resolve(); await Promise.resolve()
  expect(previous.style.viewTransitionName).toBe(''); expect(next.style.viewTransitionName).toBe('')
})

it('uses live DOM navigation without taking a screenshot and reveals only after data is ready', async () => {
  native()
  const animate = vi.fn(() => ({ finished:Promise.resolve(), cancel:vi.fn() }) as unknown as Animation)
  root.animate = animate
  const navigation = motion.navigate(() => { root.innerHTML = '<main aria-busy="true">加载中</main>' }, { native:false })
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
  expect((document as any).startViewTransition).not.toHaveBeenCalled()
  expect(animate).not.toHaveBeenCalled()
  root.querySelector('main')!.setAttribute('aria-busy','false')
  await navigation
  expect(animate).toHaveBeenCalledTimes(1)
})

it('does not replay an already visible heading when delayed content arrives', async () => {
  const animation = () => ({ finished:Promise.resolve(), cancel:vi.fn() }) as unknown as Animation
  root.animate = vi.fn(animation)
  const title = document.createElement('header'); title.dataset.pageReveal = ''
  const content = document.createElement('section'); content.dataset.pageReveal = ''
  vi.spyOn(title,'getBoundingClientRect').mockReturnValue({ top:10, bottom:40, height:30 } as DOMRect)
  vi.spyOn(content,'getBoundingClientRect').mockReturnValue({ top:50, bottom:200, height:150 } as DOMRect)
  title.animate = vi.fn(animation); content.animate = vi.fn(animation)
  let release!: () => void
  const navigation = motion.navigate(async () => { root.replaceChildren(title); await new Promise<void>(resolve => { release=resolve }); root.append(content) }, { native:false })
  await vi.advanceTimersByTimeAsync(0)
  expect(title.animate).toHaveBeenCalledTimes(1)
  release(); await navigation
  expect(title.animate).toHaveBeenCalledTimes(1)
  expect(content.animate).toHaveBeenCalledTimes(1)
})
