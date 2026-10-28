<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ApiError } from '../client'
import type { SupportConversation } from '../support-client'
import { refundApi, clearRefundRequest, readRefundRequest, saveRefundRequest, type RefundRequest, type RefundView } from '../support-refund'
import { formatMinorUnits } from '../money'
import ProductArt from './ProductArt.vue'
import Icon from './ReviewIcon.vue'
import { assistantOffers } from '../support-view'
import BuyerApplicationProgress from './BuyerApplicationProgress.vue'

const props = defineProps<{ token: string; owner: string; conversation: SupportConversation }>()
const emit = defineEmits<{ expired: []; 'layout-change': [] }>()
const id = props.conversation.conversation_id
const value = ref<RefundView>({ draft: null, application: null })
const pending = ref(readRefundRequest(props.owner, id)), busy = ref(false), reading = ref(false), loaded = ref(false)
const error = ref(''), expanded = ref(false), editing = ref(false), reason = ref('')
const dismissed = ref(false), now = ref(Date.now())
let alive = true, timer: ReturnType<typeof setInterval> | undefined, readSequence = 0
let offeredMessage = ''
const offer = computed(() => [...props.conversation.messages].reverse().find(m => m.author === 'ASSISTANT' && m.sequence === props.conversation.version && assistantOffers(m, 'REFUND_APPLICATION')))
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
watch(() => [showDraft.value, editing.value, d.value?.draft_id, d.value?.revision, application.value?.case.status], async () => {
  await nextTick()
  if (alive) emit('layout-change')
})
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
      <BuyerApplicationProgress :application="application" compact>
        <a :href="`#/customer/applications/${encodeURIComponent(application.case.case_id)}`">{{ application.case.status === 'WAITING_CUSTOMER' ? '补充说明' : '查看申请详情' }}</a><button :disabled="busy || reading" @click="read">刷新进度</button>
      </BuyerApplicationProgress>
    </article>
    <article v-if="showDraft" class="refund-summary">
      <header><strong><Icon name="file" :size="18" />退款申请</strong><small>{{ outdated ? '请重新核对' : '待你确认' }}</small></header>
      <div class="refund-overview"><div class="refund-product"><ProductArt :asset="conversation.product.asset_key || ''" :name="conversation.product.name" :variant="conversation.product.variant ?? ''" /><div><strong>{{ conversation.product.name }}</strong><p>{{ conversation.product.variant || '默认规格' }} · {{ d?.quantity ?? conversation.product.quantity }}件</p><span class="refund-store"><Icon name="store" :size="14" />{{ conversation.store_name }}</span></div></div>
      <p class="refund-amount"><span>退款金额</span><strong>{{ d ? `¥${formatMinorUnits(d.amount_minor).replace(' CNY', '')}` : '核对后显示' }}</strong></p></div>
      <div class="refund-reason"><div><span>你的申请原因</span><button v-if="!editing" data-refund="edit" :disabled="busy || !!pending" @click="editing = true">{{ outdated ? '重新核对' : '编辑' }}</button></div>
        <label v-if="editing">确认要提交给商家的原因<textarea v-model="reason" aria-label="退款申请原因" maxlength="4000" rows="3" :disabled="busy || !!pending" /></label><p v-else tabindex="0">{{ d?.reason }}</p>
      </div>
      <p class="refund-note">确认后提交给商家审核，私有聊天不会自动共享。</p>
      <p v-if="outdated" class="refund-note">申请内容已更新或过期，请重新核对金额和原因。</p>
      <footer><button :disabled="busy || !!pending" @click="d?.status === 'DRAFT' && !outdated ? send('cancel') : (expanded = false, editing = false, dismissed = true)">暂不申请</button>
        <button v-if="editing" data-refund="save" class="primary" :disabled="!reason.trim() || busy || !!pending" @click="save">{{ d && !outdated ? '保存原因' : '核对申请摘要' }}</button>
        <button v-else-if="!outdated" data-refund="confirm" class="primary" :disabled="busy || !!pending" @click="send('confirm')">确认提交申请</button>
      </footer>
    </article>
    <div v-if="!showDraft && !blockingApplication && !pending" class="refund-entry"><span v-if="!loaded">{{ reading ? offer ? '正在核对退款信息，请稍候…' : '正在读取退款信息…' : '未能核对退款信息，请重试读取。' }}</span><button data-refund="start" :disabled="busy || !loaded" @click="start">申请退款</button></div>
  </section>
</template>

<style scoped>
.chat-refund { margin: 16px 0 4px; color: var(--support-ink, #202c2a); font-size: 14px; }
.refund-summary, .refund-progress { border: 1px solid #cddfd8; border-radius: 10px; overflow: hidden; background: white; margin-bottom: 10px; }
.refund-progress { padding: 16px; }
header, footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 16px; }
header { background: #f0f7f4; }
header > strong { display: inline-flex; align-items: center; gap: 7px; color: #176b5c; font-size: 16px; font-weight: 600; }
header small { color: #94611d; background: #fff3dd; padding: 3px 8px; border-radius: 5px; }
footer { border-top: 1px solid #e5ebe6; justify-content: flex-end; flex-wrap: wrap; }
button { padding: 7px 10px; border-radius: 6px; border: 1px solid #d9e1da; background: white; color: #3f5c52; cursor: pointer; }
button.primary { background: #176b5c; color: white; border-color: #176b5c; padding: 9px 15px; }
button:disabled { opacity: .5; cursor: default; }
.refund-overview { display: flex; align-items: center; gap: 14px; padding: 14px 16px; }
.refund-product { display: flex; align-items: center; gap: 12px; flex: 1; min-width: 0; }
.refund-product > div { min-width: 0; }
.refund-product strong { font-size: 15px; font-weight: 600; }
.refund-product :deep(.product-art) { display: block; width: 58px; height: 58px; flex: 0 0 58px; border-radius: 7px; object-fit: cover; }
p { line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere; }
.refund-product p { margin: 3px 0; color: #727f77; font-size: 12px; }
.refund-store { display: inline-flex; align-items: center; gap: 5px; color: #727f77; font-size: 12px; }
.chat-refund .refund-amount { display: flex; flex: none; flex-direction: column; align-items: flex-end; gap: 3px; margin: 0; padding: 0; white-space: nowrap; }
.refund-amount > span { color: #727f77; font-size: 12px; }
.refund-amount strong { font-size: 24px; font-weight: 600; letter-spacing: -.6px; }
.refund-amount small { font-size: 10px; font-weight: 400; letter-spacing: 0; }
.refund-reason { margin: 0 16px 12px; padding: 10px 12px; background: #f6f7f3; border-radius: 6px; }
.refund-reason > div { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 12px; color: #6a786f; }
.refund-reason button { border: 0; color: #176b5c; }
.refund-reason p { margin: 5px 0 0; max-height: 180px; overflow: auto; }
.refund-reason p:focus-visible { outline: 2px solid #176b5c; outline-offset: 3px; }
label { display: block; font-size: 12px; color: #6a786f; }
.chat-refund .refund-reason textarea { display: block; box-sizing: border-box; width: 100%; min-height: 82px; max-height: 180px; margin-top: 7px; border: 1px solid #c9d6cd; border-radius: 6px; padding: 9px; background: white; resize: vertical; font: inherit; color: #202c2a; }
.chat-refund .refund-note { margin: 0 16px 12px; font-size: 12px; color: #727f77; }
.refund-entry { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 0; border-top: 1px solid #e5ebe6; font-size: 12px; color: #727f77; }
.chat-refund .refund-progress > p, .chat-refund .refund-progress > small, .chat-refund .refund-progress > ol { display: block; margin: 12px 16px; }
.refund-progress > small { overflow-wrap: anywhere; color: #727f77; }
.refund-progress ol { padding-left: 18px; line-height: 1.9; color: #727f77; }
.buyer-progress-details { margin: 12px 16px; color: #727f77; font-size: 12px; }
.buyer-progress-details summary { cursor: pointer; width: fit-content; }
.buyer-progress-details small { display: block; margin-top: 10px; overflow-wrap: anywhere; }
.refund-progress footer { justify-content: space-between; }
a { color: #176b5c; text-decoration: none; }
.refund-error, .refund-pending { padding: 12px; border-radius: 8px; background: #fff5e3; line-height: 1.7; margin: 8px 0; }
@media(max-width:1100px) { .refund-overview { gap: 10px; }.refund-product :deep(.product-art) { width: 46px; height: 46px; flex-basis: 46px; }.refund-amount strong { font-size: 21px; } }
@media(max-width:520px) { .refund-overview { flex-wrap: wrap; }.chat-refund .refund-amount { flex-direction: row; flex-basis: 100%; align-items: center; justify-content: space-between; } }
</style>
