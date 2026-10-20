<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import Icon from './ReviewIcon.vue'
defineProps<{ title: string; subtitle?: string }>()
const emit = defineEmits<{ close: [] }>()
const panel = ref<HTMLElement>()
const previous = document.activeElement as HTMLElement | null
function keys(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); emit('close') }
  if (event.key !== 'Tab') return
  const controls = [...(panel.value?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex="0"]') ?? [])]
  const first = controls[0], last = controls[controls.length - 1]
  if (!first) { event.preventDefault(); return }
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}
onMounted(async () => { await nextTick(); (panel.value?.querySelector<HTMLElement>('[data-autofocus]') || panel.value)?.focus() })
onBeforeUnmount(() => previous?.isConnected && previous.focus())
</script>

<template>
  <div class="support-dialog-backdrop" @click.self="emit('close')">
    <section ref="panel" class="support-dialog" role="dialog" aria-modal="true" :aria-label="title" tabindex="-1" @keydown="keys">
      <header><div><h2>{{ title }}</h2><p v-if="subtitle">{{ subtitle }}</p></div><button class="icon-action" aria-label="关闭弹层" @click="emit('close')"><Icon name="close" /></button></header>
      <div class="support-dialog-body"><slot /></div>
      <footer v-if="$slots.footer"><slot name="footer" /></footer>
    </section>
  </div>
</template>
