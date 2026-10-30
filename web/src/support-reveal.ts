import { computed, onScopeDispose, ref, watch, type Ref } from 'vue'
import type { SupportConversation } from './support-client'

/** Presentation only: authoritative messages and input versions never wait for animation. */
export function useSupportReveal(conversation: Readonly<Ref<SupportConversation | null>>) {
  const text = ref(''), active = ref(false), run = ref('')
  let identity = '', observedRun = '', attempt = '', target = '', frame: number | undefined
  let shown = 0, last = 0, credit = 0, deadline = 0, committed = false
  const segmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' })
  let characters: string[] = []
  const instant = () => document.hidden || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  function cancel() { if (frame !== undefined) cancelAnimationFrame(frame); frame = undefined }
  function clear() { cancel(); text.value = ''; active.value = false; run.value = ''; target = ''; characters = []; shown = 0; attempt = ''; committed = false; deadline = 0; credit = 0 }
  function tick(now: number) {
    frame = undefined
    const remaining = characters.length - shown
    if (remaining <= 0) { if (committed) active.value = false; return }
    if (instant() || deadline && now >= deadline) shown = characters.length
    else {
      const elapsed = Math.min(64, Math.max(0, now - last)) / 1000
      const rate = Math.max(55, remaining / (deadline ? Math.max(.016, (deadline - now) / 1000) : .55))
      credit += elapsed * rate
      const count = Math.floor(credit); credit -= count; shown = Math.min(characters.length, shown + count)
    }
    text.value = characters.slice(0, shown).join(''); last = now
    if (shown < characters.length) frame = requestAnimationFrame(tick)
    else if (committed) active.value = false
  }
  function update(next: string, final: boolean) {
    if (!next.startsWith(text.value)) { shown = 0; text.value = ''; credit = 0 }
    target = next; characters = [...segmenter.segment(target)].map(s => s.segment)
    if (instant()) { shown = characters.length; text.value = target }
    else if (!shown && characters.length) { shown = 1; text.value = characters[0] }
    active.value = !final || shown < characters.length
    if (final && !committed) deadline = performance.now() + Math.min(1200, Math.max(180, (characters.length - shown) * 14))
    committed = final
    if (active.value && frame === undefined) { last = performance.now(); frame = requestAnimationFrame(tick) }
  }
  watch(conversation, c => {
    if (!c) { clear(); identity = ''; observedRun = ''; return }
    if (identity !== c.conversation_id) { clear(); identity = c.conversation_id; observedRun = '' }
    const turn = c.assistant_turn
    if (!turn || ['FAILED', 'STALE'].includes(turn.status)) { clear(); observedRun = ''; return }
    if (['PENDING', 'RUNNING'].includes(turn.status)) {
      if (observedRun !== turn.run_id) { clear(); observedRun = turn.run_id }
      run.value = turn.run_id
      const generation = c.generation
      if (generation?.attempt_id && generation.attempt_id !== attempt) { clear(); run.value = turn.run_id; attempt = generation.attempt_id }
      const next = Object.entries(generation?.parts ?? {}).sort(([a], [b]) => a.localeCompare(b)).map(([, value]) => value).join('\n\n')
      if (generation?.attempt_id) update(next, false)
      return
    }
    const message = c.messages.find(m => m.author === 'ASSISTANT' && m.assistant?.run_id === turn.run_id)
    if (turn.status === 'SUCCEEDED' && observedRun === turn.run_id && message) {
      // A poll/snapshot after completion must not replay an already presented answer.
      if (committed && !active.value) return
      run.value = turn.run_id; update(message.text, true)
    } else clear()
  }, { immediate: true, flush: 'sync' })
  onScopeDispose(cancel)
  return { text, active, run, messages: computed(() => conversation.value?.messages.filter(m => !active.value || m.assistant?.run_id !== run.value) ?? []) }
}
