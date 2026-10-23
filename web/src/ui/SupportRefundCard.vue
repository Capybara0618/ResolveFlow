<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ApiError } from '../client'
import type { SupportConversation } from '../support-client'
import { refundApi, refundStatus, clearRefundRequest, readRefundRequest, saveRefundRequest, type RefundRequest, type RefundView } from '../support-refund'
import { formatMinorUnits } from '../money'
import ProductArt from './ProductArt.vue'

const props = defineProps<{ token: string; owner: string; conversation: SupportConversation }>()
const emit = defineEmits<{ expired: [] }>()
const id = props.conversation.conversation_id
const value = ref<RefundView>({ draft: null, application: null })
const pending = ref(readRefundRequest(props.owner, id)), busy = ref(false), reading = ref(false), loaded = ref(false)
const error = ref(''), expanded = ref(false), editing = ref(false), reason = ref('')
const dismissed = ref(false), now = ref(Date.now())
let alive = true, timer: ReturnType<typeof setInterval> | undefined, readSequence = 0
let offeredMessage = ''
const offer = computed(() => [...props.conversation.messages].reverse().find(m => m.author === 'ASSISTANT' && m.sequence === props.conversation.version && m.assistant?.refund_summary?.trim()))
const d = computed(() => value.value.draft)
const application = computed(() => value.value.application)
const blockingApplication = computed(() => application.value && !['CLOSED_REJECTED', 'CANCELLED'].includes(application.value.case.status))
const showDraft = computed(() => !dismissed.value && !blockingApplication.value && (expanded.value || ['DRAFT', 'EXPIRED', 'STALE'].includes(d.value?.status ?? '')))
const outdated = computed(() => !!d.value && (d.value.status !== 'DRAFT' || d.value.expected_version !== props.conversation.version || now.value >= Date.parse(d.value.expires_at)))
function fail(cause: unknown) {
  if (cause instanceof ApiError && cause.status === 401) emit('expired')
  error.value = cause instanceof ApiError ? cause.message : '连接中断，暂时无法确认结果。'
}
function accept(view: RefundView) {
  value.value = view
  if (!editing.value) reason.value = view.draft?.reason ?? reason.value
}
async function read() {
  if (reading.value || busy.value) return
  reading.value = true
  const seq = ++readSequence
  try {
    const view = await refundApi.read(props.token, id)
    if (alive && seq === readSequence) { accept(view); loaded.value = true }
  } catch (cause) { if (alive && seq === readSequence) fail(cause) }
  finally { if (alive) reading.value = false }
}
function start() {
  if (pending.value || busy.value) return
  expanded.value = true; editing.value = true; dismissed.value = false; error.value = ''
  reason.value = d.value?.reason || [...props.conversation.messages].reverse().find(m => m.author === 'CUSTOMER' && m.recipient === 'ASSISTANT')?.text || ''
}
async function retry() {
  const p = pending.value
  if (!p || busy.value) return
  busy.value = true; error.value = ''; ++readSequence
  try {
    const view = await refundApi.mutate(props.token, p)
    clearRefundRequest(props.owner, id)
    if (!alive) return
    pending.value = null; editing.value = false; expanded.value = false; accept(view); loaded.value = true
  } catch (cause) {
    if (!alive) return
    fail(cause)
    if (cause instanceof ApiError && cause.status < 500 && cause.status !== 401) {
      clearRefundRequest(props.owner, id); pending.value = null
    }
  } finally { if (alive) busy.value = false }
}
async function send(kind: RefundRequest['kind']) {
  if (pending.value || busy.value) return
  const p: RefundRequest = { conversation: id, ...(kind === 'prepare' ? {} : { draft: d.value!.draft_id }), kind, key: crypto.randomUUID(), body: kind === 'prepare' ? { expected_version: props.conversation.version, reason: reason.value.trim() } : kind === 'edit' ? { revision: d.value!.revision, reason: reason.value.trim() } : kind === 'confirm' ? { revision: d.value!.revision, expected_version: d.value!.expected_version } : { revision: d.value!.revision } }
  try { saveRefundRequest(props.owner, p) } catch { error.value = '浏览器无法保存请求，请稍后重试。'; return }
  pending.value = p; await retry()
}
function save() { return send(!d.value || outdated.value ? 'prepare' : 'edit') }
watch(() => props.conversation.version, () => { void read() })
watch(() => [loaded.value, offer.value?.message_id], () => {
  const message = offer.value
  if (!loaded.value || !message || offeredMessage === message.message_id || d.value || blockingApplication.value || busy.value || pending.value) return
  offeredMessage = message.message_id
  reason.value = message.assistant!.refund_summary!
  // Only a finalized message can prepare a Java-checked draft; Case creation still needs the confirm button.
  void send('prepare')
}, { immediate: true })
onMounted(() => {
  void read()
  timer = setInterval(() => { now.value = Date.now(); if (application.value && !['CLOSED_SUCCESS', 'CLOSED_REJECTED', 'CANCELLED'].includes(application.value.case.status)) void read() }, 5000)
})
onBeforeUnmount(() => { alive = false; ++readSequence; if (timer) clearInterval(timer) })
</script>

<template>
  <section class="chat-refund" aria-label="退款申请">
    <p v-if="error" role="alert" class="refund-error">{{ error }} <button :disabled="busy || reading" @click="read">重新读取</button></p>
    <div v-if="pending" class="refund-pending" role="status">{{ busy ? '正在保存，请稍候…' : '提交结果尚未确认，请使用原请求确认结果。' }}<button v-if="!busy" data-refund="retry" @click="retry">确认原请求结果</button></div>
    <article v-if="application" class="refund-progress">
      <header><strong>{{ refundStatus(application.case.status) }}</strong><small>模拟退款</small></header>
      <p>{{ application.result.message }}</p>
      <small>申请编号 {{ application.case.case_id }}</small>
      <ol v-if="application.timeline.length"><li v-for="(event, index) in application.timeline.slice(-3)" :key="index">{{ event.summary }}</li></ol>
      <footer><a :href="`#/customer/applications/${encodeURIComponent(application.case.case_id)}`">查看申请详情{{ application.case.status === 'WAITING_CUSTOMER' ? '并补充材料' : '' }} →</a><button :disabled="busy || reading" @click="read">刷新进度</button></footer>
    </article>
    <article v-if="showDraft" class="refund-summary">
      <header><strong>退款申请</strong><small>{{ outdated ? '请重新核对' : '待你确认' }}</small></header>
      <div class="refund-product"><ProductArt :asset="conversation.product.asset_key || ''" :name="conversation.product.name" /><div><strong>{{ conversation.product.name }}</strong><p>{{ conversation.product.variant || '默认规格' }} · {{ d?.quantity ?? conversation.product.quantity }}件 · {{ conversation.store_name }}</p></div></div>
      <p class="refund-amount"><span>整行申请金额</span><strong>{{ d ? `¥${formatMinorUnits(d.amount_minor).replace(' CNY', '')}` : '核对后显示' }} <small v-if="d">{{ d.currency }}</small></strong></p>
      <div class="refund-reason"><div><span>申请原因</span><button v-if="!editing" data-refund="edit" :disabled="busy || !!pending" @click="editing = true">{{ outdated ? '重新核对' : '编辑' }}</button></div>
        <label v-if="editing">确认要提交给商家的原因<textarea v-model="reason" aria-label="退款申请原因" maxlength="4000" rows="3" :disabled="busy || !!pending" /></label><p v-else>{{ d?.reason }}</p>
      </div>
      <p class="refund-note">仅提交你确认的申请原因，私有聊天不会自动共享。提交后进入核查流程。</p>
      <p v-if="outdated" class="refund-note">摘要或咨询已更新，请重新核对金额和原因后再确认。</p>
      <footer><button :disabled="busy || !!pending" @click="d?.status === 'DRAFT' && !outdated ? send('cancel') : (expanded = false, editing = false, dismissed = true)">暂不申请</button>
        <button v-if="editing" data-refund="save" class="primary" :disabled="!reason.trim() || busy || !!pending" @click="save">{{ d && !outdated ? '保存原因' : '核对申请摘要' }}</button>
        <button v-else-if="!outdated" data-refund="confirm" class="primary" :disabled="busy || !!pending" @click="send('confirm')">确认提交申请</button>
      </footer>
    </article>
    <div v-if="!showDraft && !blockingApplication && !pending" class="refund-entry"><span>{{ loaded ? '需要正式退款？核对原因后再提交。' : '正在读取退款信息…' }}</span><button data-refund="start" :disabled="busy || !loaded" @click="start">申请退款</button></div>
  </section>
</template>

<style scoped>
.chat-refund { margin: 18px 0 4px 46px; max-width: 620px; color: #243957; font-size: 14px; }
.refund-summary,.refund-progress { border: 1px solid #d9e3fa; border-radius: 12px; overflow: hidden; background: white; margin-bottom: 12px; }
header,footer { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:16px 20px; }
header { background:#f6f9ff; } header small { color:#8d671f; background:#fff4dc; padding:4px 8px; border-radius:5px; }
footer { border-top:1px solid #e7edf6; } button { padding:7px 10px; border-radius:7px; border:1px solid #dce5f5; background:white; color:#31517c; cursor:pointer; }
button.primary { background:#2563eb; color:white; border-color:#2563eb; padding:10px 15px; } button:disabled { opacity:.5; cursor:default; }
.refund-product { display:flex; align-items:center; gap:14px; padding:18px 20px 4px; } .refund-product :deep(.product-art) { width:54px; height:54px; flex-shrink:0; }
p { line-height:1.7; white-space:pre-wrap; overflow-wrap:anywhere; } .refund-product p { margin:4px 0; color:#7486a2; font-size:12px; }
.chat-refund .refund-amount { display:flex; justify-content:space-between; align-items:center; padding:8px 20px 16px; margin:0; } .refund-amount strong { font-size:22px; } .refund-amount small { font-size:11px; font-weight:400; }
.refund-reason { margin:0 20px; padding:12px 0; border-top:1px solid #e7edf6; } .refund-reason>div { display:flex; align-items:center; justify-content:space-between; }
.refund-reason button { border:0; color:#2563eb; } .refund-reason p { margin:6px 0; } label { display:block; font-size:12px; color:#7185a0; } textarea { display:block; box-sizing:border-box; width:100%; margin-top:8px; border:1px solid #ccd9ef; border-radius:8px; padding:10px; resize:vertical; font:inherit; color:#243957; }
.chat-refund .refund-note { margin:0 20px 16px; font-size:12px; color:#7a8da7; } .refund-entry { display:flex; align-items:center; justify-content:space-between; gap:12px; font-size:12px; color:#788ca8; }
.chat-refund .refund-progress>p,.chat-refund .refund-progress>small,.chat-refund .refund-progress>ol { display:block; margin:12px 20px; } .refund-progress>small { overflow-wrap:anywhere; color:#7890a9; } .refund-progress ol { padding-left:18px; line-height:1.9; color:#7286a2; }
a { color:#2563eb; text-decoration:none; } .refund-error,.refund-pending { padding:12px; border-radius:8px; background:#fff5e3; line-height:1.7; margin:8px 0; }
@media(max-width:1100px) { .chat-refund { margin-left:0; } }
</style>
