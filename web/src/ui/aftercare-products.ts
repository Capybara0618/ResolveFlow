import { ref } from 'vue'
import { coreApi, type OrderLine } from '../client'

/** Read display data independently; a failed product read never hides the application. */
export function useAftercareProducts(token: () => string | undefined) {
  const lines = ref<Record<string, OrderLine>>({})
  const states = ref<Record<string, 'loading' | 'ready' | 'unavailable'>>({})
  const pending = new Map<string, Promise<void>>()
  let generation = 0
  function reset() { ++generation; pending.clear(); lines.value = {}; states.value = {} }
  async function read(id: string, retry = false) {
    if (!id || !token()) return
    if (pending.has(id)) return pending.get(id)
    if (!retry && states.value[id]) return
    const identity = token()!, g = generation
    states.value[id] = 'loading'
    const task = (async () => {
      try {
        const line = await coreApi.orderLine(identity, id)
        if (g !== generation || identity !== token()) return
        if (line.line_id !== id) throw new Error('Product line mismatch')
        lines.value[id] = line; states.value[id] = 'ready'
      } catch {
        if (g === generation && identity === token()) states.value[id] = 'unavailable'
      } finally {
        if (g === generation && identity === token()) pending.delete(id)
      }
    })()
    pending.set(id, task)
    return task
  }
  async function readMany(ids: string[], retry = false) {
    const unique = [...new Set(ids)], g = generation, identity = token()
    for (let i = 0; i < unique.length && g === generation && identity === token(); i += 4)
      await Promise.all(unique.slice(i, i + 4).map(id => read(id, retry)))
  }
  return { lines, states, read, readMany, reset }
}
