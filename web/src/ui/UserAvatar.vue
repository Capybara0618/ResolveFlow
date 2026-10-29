<script setup lang="ts">
import { ref, watch, onBeforeUnmount, onMounted } from 'vue'
import { avatarBlob } from '../account-client'
const props = withDefaults(defineProps<{ token?: string; source?: string; name?: string; kind?: string; size?: number }>(), { name: '用户', kind: 'CUSTOMER', size: 36 })
const url = ref(''), revision = ref(0)
const assistantFailed = ref(false)
const assistantImage = '/identity/v1/assistant.webp'
let generation = 0
function clear() { if (url.value) URL.revokeObjectURL(url.value); url.value = '' }
watch(() => [props.token, props.source, revision.value], async () => {
  const g = ++generation; clear()
  if (!props.token || !props.source) return
  try { const blob = await avatarBlob(props.token, props.source); if (g === generation) url.value = URL.createObjectURL(blob) } catch { /* default avatar remains visible */ }
}, { immediate: true })
const refresh = () => { revision.value++ }
onMounted(() => window.addEventListener('resolveflow-profile-updated', refresh))
onBeforeUnmount(() => { generation++; clear(); window.removeEventListener('resolveflow-profile-updated', refresh) })
</script>
<template>
  <span class="user-avatar" :style="{ width: `${size}px`, height: `${size}px` }" role="img" :aria-label="`${name}的头像`">
    <img v-if="url" :src="url" alt="" @error="clear" />
    <img v-else-if="kind === 'ASSISTANT' && !assistantFailed" :src="assistantImage" alt="" @error="assistantFailed = true" />
    <svg v-else-if="kind === 'ASSISTANT'" viewBox="0 0 48 48" aria-hidden="true"><rect x="8" y="8" width="13" height="13" rx="4" fill="#256358"/><rect x="25" y="8" width="13" height="13" rx="4" fill="#79a598"/><rect x="8" y="25" width="13" height="13" rx="4" fill="#79a598"/><rect x="25" y="25" width="13" height="13" rx="4" fill="#256358"/></svg>
    <svg v-else-if="kind === 'MERCHANT'" viewBox="0 0 48 48" aria-hidden="true"><path d="M12 22h24v17H12z" fill="#b8cfc3"/><path d="M10 21l4-11h20l4 11c0 5-7 5-7 0 0 5-7 5-7 0 0 5-7 5-7 0 0 5-7 5-7 0" fill="#397769"/><rect x="21" y="28" width="8" height="11" rx="1" fill="#f8faf5"/></svg>
    <svg v-else viewBox="0 0 48 48" aria-hidden="true"><circle cx="15" cy="14" r="5" fill="#a17f62"/><circle cx="33" cy="14" r="5" fill="#a17f62"/><rect x="9" y="12" width="31" height="29" rx="13" fill="#bc9b7d"/><ellipse cx="32" cy="30" rx="11" ry="9" fill="#d5b79a"/><circle cx="18" cy="24" r="1.7" fill="#3b352d"/><circle cx="32" cy="24" r="1.7" fill="#3b352d"/><path d="M30 31h4m-2 0v3" stroke="#66503c" stroke-width="1.6" stroke-linecap="round" fill="none"/></svg>
  </span>
</template>
<style scoped>
.user-avatar{display:inline-flex;flex-shrink:0;align-items:center;justify-content:center;overflow:hidden;border-radius:50%;background:#efece3;vertical-align:middle}.user-avatar img,.user-avatar svg{width:100%;height:100%;object-fit:cover}
</style>
