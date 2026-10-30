<script setup lang="ts">
import { nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import Icon from './ReviewIcon.vue'
const props = withDefaults(defineProps<{ title: string; busy?: boolean; workspace?: string; merchant?: boolean; open?: boolean }>(), { workspace: '审核工作台', open: true })
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
    <section ref="panel" class="rf-dialog" :class="{ 'merchant-dialog': merchant }" role="dialog" aria-modal="true" :aria-label="title" tabindex="-1" @keydown="trap">
      <header><div><small v-if="!merchant">ResolveFlow · {{ workspace }}</small><h2>{{ title }}</h2></div>
        <button class="rf-dialog-close" type="button" aria-label="关闭弹窗" :disabled="busy" @click="close"><Icon name="close" :size="20" /></button>
      </header>
      <div class="rf-dialog-content"><slot /></div>
    </section>
  </div>
  </Transition>
</template>

<style scoped>
.rf-dialog-backdrop { position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; padding: 20px; background: #12233e55; backdrop-filter: blur(4px); }
.rf-dialog { width: min(560px, 100%); max-height: calc(100dvh - 40px); overflow: auto; border: 1px solid #e5ebf4; border-radius: 16px; background: white; color: #14233e; box-shadow: 0 24px 100px #12233e30; }
header { display: flex; justify-content: space-between; align-items: center; padding: 24px; border-bottom: 1px solid #edf1f7; }
header small { color: #7b89a2; font-size: 12px; }
header h2 { margin: 8px 0 0; font-size: 21px; }
.rf-dialog-close { display: grid; place-items: center; width: 34px; height: 34px; border: 0; border-radius: 8px; background: #f1f5fb; color: #64748b; }
.rf-dialog-content { padding: 24px; }
.merchant-dialog { width: min(660px, 100%); font-size: 18px; }
.merchant-dialog header h2 { font-size: 26px; margin: 0; }
.merchant-dialog :deep(.dialog-actions) { gap: 14px; margin-top: 24px; }
.merchant-dialog :deep(.dialog-actions button) { font-size: 18px; padding: 12px 22px; }
.merchant-dialog :deep(.message) { font-size: 18px; }
.merchant-dialog :deep(.dialog-refund-amount) { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 18px; background: #f0f7ff; border-radius: 12px; }
.merchant-dialog :deep(.dialog-refund-amount strong) { font-size: 28px; }
</style>

<style scoped>
.rf-dialog-presence-enter-active { transition: opacity 180ms ease; }
.rf-dialog-presence-leave-active { transition: opacity 140ms ease; }
.rf-dialog-presence-enter-active .rf-dialog,.rf-dialog-presence-leave-active .rf-dialog { transition: transform 180ms cubic-bezier(.2,.7,.2,1); }
.rf-dialog-presence-enter-from,.rf-dialog-presence-leave-to { opacity: 0; }
.rf-dialog-presence-enter-from .rf-dialog,.rf-dialog-presence-leave-to .rf-dialog { transform: translateY(6px); }
@media(prefers-reduced-motion:reduce) { .rf-dialog-presence-enter-active,.rf-dialog-presence-leave-active,.rf-dialog-presence-enter-active .rf-dialog,.rf-dialog-presence-leave-active .rf-dialog { transition: none; } }
</style>
