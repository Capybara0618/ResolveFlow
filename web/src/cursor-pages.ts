import { ref } from 'vue'

export interface CursorPageMemory<C> { index: number; cursors: Array<C | undefined> }

/** Keep opaque server cursors for visited pages; commit only after a successful read. */
export function useCursorPages<C>(memory?: CursorPageMemory<C>) {
  const pageIndex = ref(memory?.index ?? 0)
  let cursors: Array<C | undefined> = memory ? [...memory.cursors] : [undefined]
  function pageCursor(index: number): C | undefined {
    if (!Number.isInteger(index) || index < 0 || index >= cursors.length) throw new Error('无效页码')
    return cursors[index]
  }
  function acceptPage(index: number, next: C | null | undefined) {
    pageIndex.value = index
    cursors = cursors.slice(0, index + 1)
    if (next !== null && next !== undefined) cursors.push(next)
    if (memory) { memory.index = index; memory.cursors = [...cursors] }
  }
  function resetPages() { pageIndex.value = 0; cursors = [undefined]; if (memory) { memory.index = 0; memory.cursors = [undefined] } }
  return { pageIndex, pageCursor, acceptPage, resetPages }
}
