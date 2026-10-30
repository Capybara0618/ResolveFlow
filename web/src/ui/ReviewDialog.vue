<script setup lang="ts">
import { nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import Icon from './ReviewIcon.vue'
const props = withDefaults(defineProps<{ title: string; busy?: boolean; workspace?: string; merchant?: boolean; open?: boolean; compact?: boolean }>(), { workspace: '审核工作台', open: true })
const emit = defineEmits<{ close: [] }>()
const panel = ref<HTMLElement | null>(null)
let opener: HTMLElement | null = null, previousOverflow = '', locked = false, mounted = false
async function engage() {
  if (!locked) {
    opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    previousOverflow = document.body.style.overflow; locked = true
    document.body.style.overflow = 'hidden'
  }
  await nextTick()
  if (props.open) panel.value?.focus({ preventScroll: true })
}
function release(force = false) {
  if (!locked || props.open && !force) return
  document.body.style.overflow = previousOverflow; locked = false
  if (opener?.isConnected) opener.focus({ preventScroll: true })
}
function close() { if (!props.busy) emit('close') }
watch(() => props.open, open => { if (mounted && open) void engage() })
onMounted(() => { mounted = true; if (props.open) void engage() })
onBeforeUnmount(() => release(true))
function trap(event: KeyboardEvent) {
  if (event.key !== 'Tab') return
  const items = Array.from(panel.value?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], summary') ?? [])
  const first = items[0], last = items.at(-1)
  if (!first) { event.preventDefault(); return }
  if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.value)) {
    event.preventDefault(); last?.focus()
  } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === panel.value)) {
    event.preventDefault(); first.focus()
  }
}
</script>

<template>
  <Transition name="rf-dialog-presence" appear @after-leave="release()">
  <div v-if="open" class="rf-dialog-backdrop" @click.self="close" @keydown.esc.prevent="close">
    <section ref="panel" class="rf-dialog" :class="{ 'merchant-dialog': merchant, 'compact-dialog': compact }" role="dialog" aria-modal="true" :aria-label="title" tabindex="-1" @keydown="trap">
      <header class="rf-dialog-header"><h2>{{ title }}</h2>
        <button class="rf-dialog-close" type="button" aria-label="关闭弹窗" :disabled="busy" @click="close"><Icon name="close" :size="20" /></button>
      </header>
      <div class="rf-dialog-content"><slot /></div>
      <footer v-if="$slots.footer" class="rf-dialog-footer"><slot name="footer" /></footer>
    </section>
  </div>
  </Transition>
</template>

<style scoped>
.rf-dialog-backdrop { position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; padding: 24px; background: #1f29283d; backdrop-filter: blur(2px); }
.rf-dialog { width: min(540px, 100%); max-height: calc(100dvh - 48px); overflow: auto; border: 1px solid #e5e7e0; border-radius: var(--rf-radius-dialog); background: var(--rf-surface); color: var(--rf-ink); box-shadow: 0 20px 70px #172b2424, 0 2px 8px #172b2408; }
.rf-dialog:focus { outline: none; }
.rf-dialog .rf-dialog-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 26px 28px 0; border: 0; }
.rf-dialog .rf-dialog-header h2 { margin: 0; color: inherit; font-size: 20px; font-weight: 500; line-height: 1.5; letter-spacing: -.3px; }
.rf-dialog .rf-dialog-close { display: grid; place-items: center; flex-shrink: 0; width: 30px; min-height: 30px; height: 30px; padding: 0; margin: 0 -5px 0 0; border: 0; border-radius: 7px; background: transparent; color: #7a857d; }
.rf-dialog .rf-dialog-close:hover:not(:disabled) { background: #f2f4ef; color: #25372e; }
.rf-dialog .rf-dialog-content { padding: 14px 28px 28px; font-size: 15px; line-height: 1.7; }
.rf-dialog .rf-dialog-content :deep(p) { font-size: 15px; line-height: 1.7; }
.rf-dialog .rf-dialog-content :deep(> p:first-child) { margin: 0; color: #69756d; }
.rf-dialog:has(.rf-dialog-footer) .rf-dialog-content { padding-bottom: 0; }
.rf-dialog .rf-dialog-footer { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 10px; padding: 26px 28px 26px; }
.rf-dialog .rf-dialog-footer :deep(button) { min-width: 100px; min-height: var(--rf-control-height); margin: 0; padding: 9px 18px; border-radius: var(--rf-radius); font-size: 14px; line-height: 20px; }
.rf-dialog .rf-dialog-footer :deep(.dialog-danger) { background: #a34e42; color: #fff; border: 1px solid #a34e42; }
.rf-dialog .rf-dialog-footer :deep(.dialog-danger:hover:not(:disabled)) { background: #8c4036; border-color: #8c4036; }
.compact-dialog { width: min(440px, 100%); }
.merchant-dialog { width: min(660px, 100%); }
.merchant-dialog :deep(.dialog-actions) { gap: 10px; margin-top: 24px; }
.merchant-dialog :deep(.dialog-actions button) { font-size: 15px; padding: 10px 18px; }
.merchant-dialog :deep(.dialog-refund-amount) { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 18px; background: #f0f4ed; border-radius: 10px; }
.merchant-dialog :deep(.dialog-refund-amount strong) { font-size: 26px; }
@media(max-width:480px) {
  .rf-dialog-backdrop { padding: 20px; }
  .rf-dialog .rf-dialog-header { padding: 22px 22px 0; }
  .rf-dialog .rf-dialog-content { padding: 12px 22px 22px; }
  .rf-dialog .rf-dialog-footer { padding: 24px 22px 22px; }
  .rf-dialog .rf-dialog-footer :deep(button) { flex: 1; min-width: 0; }
}
.rf-dialog-presence-enter-active { transition: opacity 180ms ease; }
.rf-dialog-presence-leave-active { transition: opacity 140ms ease; }
.rf-dialog-presence-enter-active .rf-dialog,.rf-dialog-presence-leave-active .rf-dialog { transition: transform 180ms cubic-bezier(.2,.7,.2,1); }
.rf-dialog-presence-enter-from,.rf-dialog-presence-leave-to { opacity: 0; }
.rf-dialog-presence-enter-from .rf-dialog,.rf-dialog-presence-leave-to .rf-dialog { transform: translateY(6px); }
@media(prefers-reduced-motion:reduce) { .rf-dialog-presence-enter-active,.rf-dialog-presence-leave-active,.rf-dialog-presence-enter-active .rf-dialog,.rf-dialog-presence-leave-active .rf-dialog { transition: none; } }
</style>
