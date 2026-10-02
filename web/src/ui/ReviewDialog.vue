<script setup lang="ts">
import { nextTick, onMounted, onBeforeUnmount, ref } from 'vue'
import Icon from './ReviewIcon.vue'
withDefaults(defineProps<{ title: string; busy?: boolean; workspace?: string }>(), { workspace: '审核工作台' })
const emit = defineEmits<{ close: [] }>()
const panel = ref<HTMLElement | null>(null)
const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
const previousOverflow = document.body.style.overflow
onMounted(async () => {
  document.body.style.overflow = 'hidden'
  await nextTick()
  panel.value?.focus()
})
onBeforeUnmount(() => {
  document.body.style.overflow = previousOverflow
  if (opener?.isConnected) opener.focus()
})
function trap(event: KeyboardEvent) {
  if (event.key !== 'Tab') return
  const items = Array.from(panel.value?.querySelectorAll<HTMLElement>('button:not(:disabled), input, textarea, a[href], summary') ?? [])
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
  <div class="rf-dialog-backdrop" @click.self="!busy && emit('close')" @keydown.esc.prevent="!busy && emit('close')">
    <section ref="panel" class="rf-dialog" role="dialog" aria-modal="true" :aria-label="title" tabindex="-1" @keydown="trap">
      <header><div><small>ResolveFlow · {{ workspace }}</small><h2>{{ title }}</h2></div>
        <button class="rf-dialog-close" type="button" aria-label="关闭弹窗" :disabled="busy" @click="emit('close')"><Icon name="close" :size="20" /></button>
      </header>
      <div class="rf-dialog-content"><slot /></div>
    </section>
  </div>
</template>

<style scoped>
.rf-dialog-backdrop { position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; padding: 20px; background: #12233e55; backdrop-filter: blur(4px); }
.rf-dialog { width: min(560px, 100%); max-height: calc(100dvh - 40px); overflow: auto; border: 1px solid #e5ebf4; border-radius: 16px; background: white; color: #14233e; box-shadow: 0 24px 100px #12233e30; }
header { display: flex; justify-content: space-between; align-items: center; padding: 24px; border-bottom: 1px solid #edf1f7; }
header small { color: #7b89a2; font-size: 12px; }
header h2 { margin: 8px 0 0; font-size: 21px; }
.rf-dialog-close { display: grid; place-items: center; width: 34px; height: 34px; border: 0; border-radius: 8px; background: #f1f5fb; color: #64748b; }
.rf-dialog-content { padding: 24px; }
</style>
