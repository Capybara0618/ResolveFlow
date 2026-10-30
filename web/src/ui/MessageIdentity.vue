<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import { apiRequest } from '../client'
import UserAvatar from './UserAvatar.vue'
const props = defineProps<{ token: string; conversation: string; message: string; author: string }>()
const display = ref(''), avatar = ref<string | null>(null)
let generation = 0
const path = () => `/api/v1/support/conversations/${encodeURIComponent(props.conversation)}/messages/${encodeURIComponent(props.message)}/identity`
watch(() => [props.token, props.conversation, props.message], async () => {
  const g = ++generation; avatar.value = null; display.value = props.author === 'ASSISTANT' ? '售后助手' : props.author === 'MERCHANT' ? '商家' : '买家'
  if (props.author === 'ASSISTANT') return
  try { const result = await apiRequest<{ display_name: string; avatar_id: string | null }>(path(), props.token); if (g === generation) { display.value = result.display_name; avatar.value = result.avatar_id } } catch { /* Optional profile data may be unavailable. */ }
}, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>
<template><span class="message-identity" :title="display"><UserAvatar :token="token" :source="avatar ? `${path()}/avatar` : undefined" :name="display" :kind="author" :size="32" /></span></template>
<style scoped>.message-identity{display:inline-flex;align-items:flex-start;justify-content:center;flex:0 0 36px;width:36px}</style>
