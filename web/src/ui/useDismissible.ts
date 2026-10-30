import { onMounted, onBeforeUnmount, type Ref } from 'vue'

/** Only transient menus use this hook; inline records and edit forms stay open. */
export function useDismissible(root: Ref<HTMLElement | undefined>, isOpen: () => boolean, close: () => void) {
  function outside(event: PointerEvent) {
    if (isOpen() && root.value && event.target instanceof Node && !root.value.contains(event.target)) close()
  }
  function escape(event: KeyboardEvent) {
    if (event.key === 'Escape' && isOpen()) {
      close()
      root.value?.querySelector<HTMLElement>('summary, button')?.focus()
    }
  }
  onMounted(() => { document.addEventListener('pointerdown', outside); document.addEventListener('keydown', escape) })
  onBeforeUnmount(() => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape) })
}
