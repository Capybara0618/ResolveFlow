<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import { avatarBlob } from '../account-client'
const props = defineProps<{ id: string; name: string; token?: string }>()
const url = ref(''), failed = ref(false)
let generation = 0
function clear() { if (url.value.startsWith('blob:')) URL.revokeObjectURL(url.value); url.value = '' }
watch(() => [props.id, props.token], async () => { const g = ++generation; clear(); failed.value = false
  if (!props.token) { url.value = `/api/v1/shop/media/${encodeURIComponent(props.id)}`; return }
  try { const blob = await avatarBlob(props.token, `/api/v1/merchant/media/${encodeURIComponent(props.id)}`); if (g === generation) url.value = URL.createObjectURL(blob) } catch { if (g === generation) failed.value = true }
}, { immediate: true })
onBeforeUnmount(() => { generation++; clear() })
</script>
<template><img v-if="url && !failed" :src="url" :alt="name" @error="failed = true" /><span v-else class="catalog-image-fallback" role="img" :aria-label="`${name}图片暂不可用`">{{ failed ? '图片暂不可用' : '正在读取图片…' }}</span></template>
<style scoped>img{display:block;width:100%;height:100%;object-fit:contain}.catalog-image-fallback{display:flex;align-items:center;justify-content:center;width:100%;min-height:80px;height:100%;font-size:13px;color:#7a8075;background:#f2f2eb}</style>
