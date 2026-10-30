<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import { useDismissible } from './useDismissible'
import { ApiError } from '../client'
import { notificationApi, type Notification } from '../notification-client'
const props = defineProps<{ token: string; disabled?: boolean; expanded?: boolean }>()
const emit = defineEmits<{ expired: []; open: [item: Notification] }>()
const visible = ref(false), items = ref<Notification[]>([]), unread = ref<number | null>(null), next = ref<string | null>(null), loading = ref(false), error = ref('')
const root = ref<HTMLElement>()
useDismissible(root, () => visible.value && !props.expanded, () => { visible.value = false })
let generation = 0, timer: ReturnType<typeof setInterval> | undefined
async function load(more = false) {
  if (loading.value) return
  const g = generation; loading.value = true; error.value = ''
  try { const page = await notificationApi.list(props.token, more ? next.value ?? undefined : undefined); if (g !== generation) return
    items.value = more ? [...items.value, ...page.items.filter(i => !items.value.some(old => old.notification_id === i.notification_id))] : page.items
    unread.value = page.unread_count; next.value = page.next_cursor
  } catch (e) { if (g === generation) { if (e instanceof ApiError && e.status === 401) emit('expired'); error.value = '消息暂时无法读取，请重试' } }
  finally { if (g === generation) loading.value = false }
}
async function open(item: Notification) {
  if (props.disabled || loading.value) return
  const g = generation; loading.value = true; error.value = ''
  try { await notificationApi.read(props.token, item.notification_id); if (g !== generation) return
    if (!item.read && unread.value !== null) unread.value = Math.max(0, unread.value - 1)
    item.read = true; visible.value = false; emit('open', item)
  } catch (e) { if (g === generation) { if (e instanceof ApiError && e.status === 401) emit('expired'); error.value = '消息打开失败，请重试' } }
  finally { if (g === generation) loading.value = false }
}
watch(() => props.token, () => { generation++; items.value = []; unread.value = null; next.value = null; loading.value = false; visible.value = false; void load(); if (timer) clearInterval(timer); timer = setInterval(() => { if (!visible.value && !props.expanded && !document.hidden) void load() }, 30000) }, { immediate: true })
onBeforeUnmount(() => { generation++; if (timer) clearInterval(timer) })
</script>
<template>
  <section ref="root" class="notification-center" :class="{ expanded }" aria-label="站内消息">
    <button v-if="!expanded" type="button" class="notification-toggle" :disabled="disabled" :aria-expanded="visible" @click="visible = !visible; visible && load()">消息<span v-if="unread" class="notification-count">{{ unread > 99 ? '99+' : unread }}</span><span v-else-if="error" class="notification-unavailable" aria-label="消息读取失败">!</span></button>
    <div v-if="visible || expanded" class="notification-panel">
      <header><h2>消息</h2><button :disabled="loading" @click="load()">刷新</button><button v-if="!expanded" @click="visible = false">关闭</button></header>
      <p v-if="error" role="alert">{{ error }}</p><p v-else-if="loading && !items.length" role="status">正在读取消息…</p><p v-else-if="!items.length">暂时没有消息</p>
      <button v-for="item in items" :key="item.notification_id" class="notification-item" :class="{ unread: !item.read }" :disabled="disabled || loading" @click="open(item)"><strong>{{ item.title }}</strong><time>{{ new Date(item.created_at).toLocaleString('zh-CN', { hour12: false }) }}</time><span>{{ item.read ? '已读' : '未读' }}</span></button>
      <button v-if="next" :disabled="loading" @click="load(true)">加载更多消息</button>
    </div>
  </section>
</template>
<style scoped>
.notification-center{position:relative}.notification-center button{font:inherit;color:inherit;cursor:pointer}.notification-toggle{display:flex;white-space:nowrap;align-items:center;gap:7px;padding:8px 4px;background:none;border:0}.notification-count{font-size:11px;background:#205e50;color:#fff;border-radius:20px;padding:2px 6px}.notification-unavailable{color:#a34c38}.notification-panel{position:absolute;z-index:50;right:0;top:45px;width:min(380px,85vw);max-height:65vh;overflow:auto;border:1px solid #dfe3da;border-radius:12px;background:#fffdf8;padding:18px;box-shadow:0 12px 38px #283b341a;color:#293d34}.notification-panel header{display:flex;align-items:center;gap:12px;margin-bottom:12px}.notification-panel h2{font-size:18px;margin:0;flex:1}.notification-panel header button,.notification-panel>button:last-child{background:none;border:0;color:#205e50;font-size:14px}.notification-item{display:grid;width:100%;text-align:left;gap:7px;border:0;border-bottom:1px solid #e8e9e2;background:none;padding:16px 8px}.notification-item strong{font-size:15px;font-weight:500}.notification-item time,.notification-item span{font-size:12px;color:#758075}.notification-item.unread{background:#f0f5ed;border-radius:7px}.notification-item.unread strong{font-weight:600}.expanded .notification-panel{position:static;width:auto;max-height:none;box-shadow:none}.expanded{max-width:800px;margin:32px auto;padding:0 24px}
</style>
