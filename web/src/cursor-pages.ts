import { ref } from 'vue'

/** Keep opaque server cursors for visited pages; commit only after a successful read. */
export function useCursorPages<C>() {
  const pageIndex = ref(0)
  let cursors: Array<C | undefined> = [undefined]
  function pageCursor(index: number): C | undefined {
    if (!Number.isInteger(index) || index < 0 || index >= cursors.length) throw new Error('无效页码')
    return cursors[index]
  }
  function acceptPage(index: number, next: C | null | undefined) {
    pageIndex.value = index
    cursors = cursors.slice(0, index + 1)
    if (next !== null && next !== undefined) cursors.push(next)
  }
  function resetPages() { pageIndex.value = 0; cursors = [undefined] }
  return { pageIndex, pageCursor, acceptPage, resetPages }
}
