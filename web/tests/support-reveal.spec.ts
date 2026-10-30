import { effectScope, ref } from 'vue'
import { afterEach, expect, it, vi } from 'vitest'
import { useSupportReveal } from '../src/support-reveal'
import type { SupportConversation } from '../src/support-client'
import fixture from '../../contracts/core/fixtures/support.json'

const scopes: ReturnType<typeof effectScope>[] = []
afterEach(() => { scopes.splice(0).forEach(s => s.stop()); vi.useRealTimers(); vi.unstubAllGlobals() })
function setup() {
  vi.useFakeTimers()
  const conversation = ref<SupportConversation | null>({ ...structuredClone(fixture.Conversation), ticket: null, assistant_turn: { run_id: 'r', status: 'RUNNING', reason: null } } as SupportConversation)
  const scope = effectScope(); scopes.push(scope)
  return { conversation, view: scope.run(() => useSupportReveal(conversation))! }
}
function delta(c: ReturnType<typeof setup>['conversation'], text: string, attempt = 'a') {
  c.value = { ...c.value!, generation: { run_id: 'r', input_version: c.value!.version, attempt_id: attempt, parts: { 'part-0': text } } }
}
function commit(c: ReturnType<typeof setup>['conversation'], text: string) {
  c.value = { ...c.value!, version: c.value!.version + 1, generation: undefined, assistant_turn: { run_id: 'r', status: 'SUCCEEDED', reason: null }, messages: [...c.value!.messages, { message_id: 'final', sequence: c.value!.version + 1, author: 'ASSISTANT', recipient: 'CUSTOMER', ticket_id: null, text, created_at: '', assistant: { run_id: 'r', mode: 'live', citations: [], handoff_summary: null } }] }
}
it('reveals a burst over frames and drains the committed suffix without jumping to the full reply', async () => {
  const { conversation: c, view } = setup(); const text = '已经核实物流情况。'.repeat(8)
  delta(c, text); expect(view.text.value.length).toBeGreaterThan(0); expect(view.text.value.length).toBeLessThan(text.length)
  await vi.advanceTimersByTimeAsync(160); const prefix = view.text.value
  expect(text.startsWith(prefix)).toBe(true); expect(prefix.length).toBeGreaterThan(1)
  commit(c, text + '可以继续申请。')
  expect(view.active.value).toBe(true); expect(view.text.value).toBe(prefix)
  await vi.advanceTimersByTimeAsync(1300)
  expect(view.active.value).toBe(false)
})
it('drops a rejected attempt and failed text immediately instead of animating stale words', () => {
  const { conversation: c, view } = setup(); delta(c, '旧答复'); delta(c, '', 'b')
  expect(view.text.value).toBe('')
  delta(c, '新答复', 'b'); c.value = { ...c.value!, generation: undefined, assistant_turn: { run_id: 'r', status: 'FAILED', reason: 'INVALID_DECISION' } }
  expect(view.active.value).toBe(false); expect(view.text.value).toBe('')
})
it('never animates history and stops work when switching conversations or unmounting', async () => {
  const { conversation: c, view } = setup(); delta(c, '正在显示的长答复'.repeat(10))
  c.value = { ...c.value!, conversation_id: 'other', generation: undefined, assistant_turn: { run_id: 'old', status: 'SUCCEEDED', reason: null } }
  expect(view.active.value).toBe(false); expect(view.text.value).toBe('')
  scopes.at(-1)!.stop(); await vi.advanceTimersByTimeAsync(2000); expect(view.text.value).toBe('')
})
it('does not split emoji sequences and respects reduced motion', async () => {
  const { conversation: c, view } = setup(); delta(c, '👩‍💻你好'); expect(view.text.value).toBe('👩‍💻')
  vi.stubGlobal('matchMedia', () => ({ matches: true }))
  delta(c, '无需等待的完整正文'); expect(view.text.value).toBe('无需等待的完整正文')
  commit(c, '无需等待的完整正文'); expect(view.active.value).toBe(false)
})
it('replaces corrected final content immediately before revealing its own text', () => {
  const { conversation: c, view } = setup(); delta(c, '旧的错误结论'.repeat(10)); commit(c, '商家还需要核实。')
  expect(view.text.value).not.toContain('旧'); expect('商家还需要核实。'.startsWith(view.text.value)).toBe(true)
})
