const locks = new WeakMap<Document, { count: number; overflow: string }>()

/** Multiple dialogs share one background lock, including owner-first unmounts. */
export function lockDialogScroll(doc: Document = document): () => void {
  let state = locks.get(doc)
  if (!state) { state = { count: 0, overflow: doc.body.style.overflow }; locks.set(doc, state) }
  state.count++; doc.body.style.overflow = 'hidden'
  let released = false
  return () => {
    if (released) return
    released = true
    if (--state.count === 0) { doc.body.style.overflow = state.overflow; locks.delete(doc) }
  }
}
