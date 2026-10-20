<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiError, coreApi, type LoginResponse, type OrderLine } from '../client'
import { supportApi, saveSupportPending, readSupportPending, clearSupportPending, type SupportConversation, type SupportCommand, type SupportPending } from '../support-client'
import { formatMinorUnits } from '../money'
import ProductArt from './ProductArt.vue'
import SupportSources from './SupportSources.vue'
import './support-workspace.css'

const props = defineProps<{ account: LoginResponse }>()
const emit = defineEmits<{ expired: [] }>()
const merchant = computed(() => props.account.role === 'MERCHANT_ADMIN')
const owner = `${props.account.role}:${props.account.buyer_id ?? props.account.merchant_id}`
const token = props.account.access_token
const items = ref<SupportConversation[]>([]), next = ref<number | null>(null)
const orders = ref<OrderLine[]>([]), orderCursor = ref<string | null>(null)
const selected = ref<SupportConversation | null>(null), choosing = ref(!merchant.value)
const loading = ref(false), busy = ref(false), error = ref(''), notice = ref(''), draft = ref('')
const recipient = ref<'ASSISTANT' | 'MERCHANT'>('ASSISTANT'), replyKind = ref<'REPLY' | 'REQUEST_INFO'>('REPLY')
const preview = ref(false), summary = ref(''), share = ref<string[]>([]), previewVersion = ref(0)
const shareReport = ref(false)
const latestAssistant = computed(() => selected.value?.messages.find(m => m.author === 'ASSISTANT' && m.sequence === selected.value?.version && m.assistant))
const sharedCitations = computed(() => latestAssistant.value?.assistant?.citations.filter(c => c.source_type !== 'CONVERSATION') ?? [])
const assistantState = computed(() => {
  const turn = selected.value?.assistant_turn
  if (!turn || merchant.value) return ''
  return { PENDING: '助手正在等待处理，你可以继续补充问题。', RUNNING: '助手正在查阅资料，你可以补充或纠正问题。', SUCCEEDED: '', FAILED: '助手本次未能完成回答，可重新提问或请商家核查。', STALE: '问题已更新，旧回复不会发布。' }[turn.status]
})
const pending = ref<SupportPending | null>(readSupportPending(owner))
let alive = true, generation = 0, timer: ReturnType<typeof setInterval> | undefined
let expandedHistory = false
const labels = { PENDING: '待商家处理', WAITING_CUSTOMER: merchant.value ? '待客户补充' : '待你补充', REPLIED: '商家已回复', RESOLVED: '咨询已解决' }
const privateMessages = computed(() => selected.value?.messages.filter(m => m.author === 'CUSTOMER' && m.recipient === 'ASSISTANT') ?? [])
const time = (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false })
function fail(cause: unknown) {
  if (cause instanceof ApiError && cause.status === 401) emit('expired')
  error.value = cause instanceof ApiError ? cause.message : '连接中断，暂时无法确认结果。'
}
function setSelected(value: SupportConversation) {
  expandedHistory = false
  selected.value = value; choosing.value = false
  recipient.value = value.ticket ? 'MERCHANT' : 'ASSISTANT'
  const index = items.value.findIndex(c => c.conversation_id === value.conversation_id)
  if (index >= 0) items.value[index] = { ...value, messages: [] }
  else items.value.unshift({ ...value, messages: [] })
}
async function list(more = false) {
  const result = merchant.value ? await supportApi.tickets(token, more ? next.value : null) : await supportApi.conversations(token, more ? next.value : null)
  if (!alive) return
  items.value = more ? [...items.value, ...result.items] : result.items; next.value = result.next_before
}
async function readOrders(more = false) {
  const result = await coreApi.orders(token, more ? orderCursor.value ?? undefined : undefined)
  if (!alive) return
  orders.value = more ? [...orders.value, ...result.items] : result.items; orderCursor.value = result.page.next_cursor ?? null
}
async function load() {
  loading.value = true; error.value = ''
  try { await Promise.all([list(), merchant.value ? Promise.resolve() : readOrders()]) }
  catch (cause) { if (alive) fail(cause) } finally { if (alive) loading.value = false }
}
async function open(item: SupportConversation) {
  if (busy.value || pending.value) return
  const g = ++generation; loading.value = true; error.value = ''; preview.value = false
  selected.value = null; draft.value = ''
  try {
    const value = await supportApi.read(token, merchant.value ? item.ticket!.ticket_id : item.conversation_id, merchant.value)
    if (alive && g === generation) setSelected(value)
  } catch (cause) { if (alive && g === generation) fail(cause) }
  finally { if (alive && g === generation) loading.value = false }
}
async function choose(line: OrderLine) {
  if (busy.value || pending.value) return
  const g = ++generation; loading.value = true; error.value = ''; preview.value = false
  selected.value = null; draft.value = ''
  try { const value = await supportApi.open(token, line.line_id); if (alive && g === generation) setSelected(value) }
  catch (cause) { if (alive && g === generation) fail(cause) } finally { if (alive && g === generation) loading.value = false }
}
async function refresh(quiet = false) {
  const c = selected.value
  if (!c || busy.value || preview.value || pending.value || loading.value) return
  if (quiet && expandedHistory) return
  const g = generation
  try {
    const value = await supportApi.read(token, merchant.value ? c.ticket!.ticket_id : c.conversation_id, merchant.value)
    if (alive && g === generation && selected.value?.conversation_id === c.conversation_id) {
      selected.value = value; expandedHistory = false
      if (notice.value === '问题已发送，助手正在处理。' && value.assistant_turn && !['PENDING', 'RUNNING'].includes(value.assistant_turn.status)) notice.value = ''
      if (!quiet) error.value = ''
    }
  } catch (cause) { if (alive && g === generation) fail(cause) }
}
async function older() {
  const c = selected.value; if (!c?.next_before_sequence || loading.value) return
  const g = generation; loading.value = true
  try {
    const value = await supportApi.read(token, merchant.value ? c.ticket!.ticket_id : c.conversation_id, merchant.value, c.next_before_sequence)
    if (alive && g === generation && selected.value?.conversation_id === c.conversation_id) { selected.value = { ...selected.value, messages: [...value.messages, ...selected.value.messages], next_before_sequence: value.next_before_sequence }; expandedHistory = true }
  } catch (cause) { if (alive && g === generation) fail(cause) } finally { if (alive && g === generation) loading.value = false }
}
function handoff() {
  if (!selected.value || pending.value) return
  summary.value = draft.value.trim() || latestAssistant.value?.assistant?.handoff_summary || ''; share.value = []; shareReport.value = false; previewVersion.value = selected.value.version; preview.value = true; error.value = ''
}
function confirmHandoff() {
  const c = selected.value
  if (!c) return
  return submit({ kind: 'handoff', id: c.conversation_id, body: { expected_version: previewVersion.value, summary: summary.value.trim(), shared_message_ids: [...share.value], ...(shareReport.value && latestAssistant.value ? { assistant_message_id: latestAssistant.value.message_id } : {}) } })
}
async function submit(command: SupportCommand) {
  if (busy.value || pending.value || !selected.value) return
  const p: SupportPending = { ...command, key: crypto.randomUUID(), label: selected.value.product.name }
  try { saveSupportPending(owner, p) } catch { error.value = '浏览器暂时无法保存请求，请稍后重试。'; return }
  pending.value = p; await retry()
}
async function retry() {
  const p = pending.value; if (!p || busy.value) return
  busy.value = true; error.value = ''
  try {
    const value = await supportApi.mutate(token, p)
    clearSupportPending(owner)
    if (!alive) return
    pending.value = null; setSelected(value); preview.value = false; draft.value = ''; notice.value = p.kind === 'handoff' ? '已转交商家核查，没有提交退款申请。' : p.kind === 'send' && p.body.recipient === 'ASSISTANT' ? '问题已发送，助手正在处理。' : '已保存。'
    await list()
  } catch (cause) {
    if (!alive) return
    fail(cause)
    if (cause instanceof ApiError && cause.status < 500 && cause.status !== 401) { clearSupportPending(owner); pending.value = null; if (cause.status === 409) preview.value = false }
  } finally { if (alive) busy.value = false }
}
async function send() {
  const c = selected.value; if (!c || !draft.value.trim()) return
  if (merchant.value) await submit({ kind: 'reply', id: c.ticket!.ticket_id, body: { expected_version: c.version, text: draft.value.trim(), kind: replyKind.value } })
  else await submit({ kind: 'send', id: c.conversation_id, body: { expected_version: c.version, text: draft.value.trim(), recipient: recipient.value } })
}
onMounted(() => { void load(); timer = setInterval(() => { if (!document.hidden) void refresh(true) }, 8000) })
onBeforeUnmount(() => { alive = false; ++generation; if (timer) clearInterval(timer) })
</script>

<template>
  <section class="support-workspace">
    <header class="support-heading"><div><h1>{{ merchant ? '咨询核查' : '售后咨询' }}</h1><p>{{ merchant ? '查看客户共享的问题与材料，在此核查并回复。' : '选择需要咨询的商品，每件商品保留独立记录。人工咨询无需申请退款。' }}</p></div><button :disabled="loading || busy" @click="load">刷新列表</button></header>
    <p v-if="error" role="alert" class="support-error">{{ error }} <button v-if="selected && !pending" @click="refresh()">刷新当前记录</button></p>
    <p v-if="notice" role="status" class="support-notice">{{ notice }}</p>
    <div v-if="pending" role="status" class="support-notice">“{{ pending.label }}”的提交结果尚待确认。<button data-action="retry" :disabled="busy" @click="retry">{{ busy ? '正在确认…' : '用原请求确认结果' }}</button></div>
    <div class="support-grid">
      <aside class="support-history"><h2>{{ merchant ? '本店核查单' : '我的咨询' }}</h2><button v-if="!merchant" :disabled="busy || !!pending" @click="choosing = true; ++generation; selected = null; preview = false; draft = ''">＋ 选择订单商品</button>
        <button v-for="item in items" :key="item.conversation_id" data-conversation :data-line-id="item.line_id" :disabled="busy || !!pending" :class="{ current: selected?.conversation_id === item.conversation_id }" @click="open(item)"><strong>{{ item.product.name }}</strong><span>{{ item.store_name }}</span><small>{{ item.ticket ? labels[item.ticket.status] : '咨询记录' }}</small></button>
        <p v-if="!items.length && !loading">{{ merchant ? '暂无客户提交的核查单。' : '还没有咨询记录。' }}</p>
        <button v-if="next" :disabled="loading" @click="list(true).catch(fail)">更多记录</button>
      </aside>
      <main class="support-main">
        <p v-if="loading" role="status">正在读取…</p>
        <template v-if="choosing && !merchant"><h2>选择需要咨询的商品</h2><div class="support-order-grid"><article v-for="line in orders" :key="line.line_id" class="support-order" :data-line-id="line.line_id"><ProductArt :asset="line.asset_key || ''" :name="line.product_name || line.sku" /><div><p>{{ line.merchant_name }}</p><h3>{{ line.product_name || line.sku }}</h3><p>{{ line.variant_text }} · {{ line.quantity }} 件 · ¥{{ formatMinorUnits(line.line_paid_amount).replace(' CNY','') }}</p><button :disabled="loading || busy || !!pending" @click="choose(line)">咨询这件商品</button></div></article></div><p v-if="!loading && !orders.length">暂无已付款订单，可以先在商城购买商品。</p><button v-if="orderCursor" @click="readOrders(true).catch(fail)">更多订单商品</button></template>
        <template v-else-if="selected">
          <header class="support-product"><ProductArt :asset="selected.product.asset_key || ''" :name="selected.product.name" /><div><h2>{{ selected.product.name }}</h2><p>{{ selected.store_name }} · {{ selected.product.variant }} · {{ selected.product.quantity }} 件 · 实付 ¥{{ formatMinorUnits(selected.product.amount_minor).replace(' CNY','') }}</p></div><strong>{{ selected.ticket ? labels[selected.ticket.status] : '咨询记录' }}</strong></header>
          <div v-if="selected.ticket" class="support-ticket"><h3>已确认的核查摘要</h3><p>{{ selected.ticket.summary }}</p><div v-if="selected.ticket.report" class="support-report"><h3>客户确认共享的调查依据</h3><p v-if="selected.ticket.report.mode === 'mock'" class="muted">脚本模型演示</p><SupportSources :citations="selected.ticket.report.citations" /></div><template v-if="merchant"><h3>客户共享原文</h3><p v-if="!selected.ticket.shared_messages.length">本次仅共享摘要，未共享原文。</p><blockquote v-for="m in selected.ticket.shared_messages" :key="m.message_id">{{ m.text }}</blockquote></template></div>
          <div v-if="preview" class="support-preview"><h3>确认转交商家核查</h3><p>商家将收到以下摘要及你选择的原文；不会提交退款申请。</p><label>核查摘要<textarea v-model="summary" aria-label="核查摘要" maxlength="2000" /></label><fieldset v-if="latestAssistant"><legend>调查依据</legend><label><input v-model="shareReport" data-share-report type="checkbox" />共享此回答的订单、物流和政策依据</label><SupportSources :citations="sharedCitations" /><p>对话原文仅按下方选择共享。</p></fieldset><fieldset><legend>选择共享的相关原文（最多20条）</legend><label v-for="m in privateMessages" :key="m.message_id"><input v-model="share" type="checkbox" :value="m.message_id" :disabled="share.length >= 20 && !share.includes(m.message_id)" />{{ m.text }}</label><p v-if="!privateMessages.length">尚无私有咨询消息，可仅转交摘要。</p></fieldset><button data-action="confirm-handoff" class="primary" :disabled="!summary.trim() || busy || !!pending" @click="confirmHandoff">确认转交商家</button><button :disabled="busy || !!pending" @click="preview = false">返回咨询</button></div>
          <template v-else><div class="support-messages"><button v-if="selected.next_before_sequence" :disabled="loading" @click="older">读取更早消息</button><p v-if="!selected.messages.length">{{ merchant ? '客户补充与商家回复将显示在这里。' : '可以描述问题、补充情况，或直接请求商家核查。' }}</p><article v-for="m in selected.messages" :key="m.message_id" :class="['support-message', m.author.toLowerCase()]"><header><strong>{{ m.author === 'ASSISTANT' ? '售后助手' : m.author === 'MERCHANT' ? '商家' : merchant ? '客户' : '我' }}</strong><span>{{ m.author === 'ASSISTANT' ? (m.assistant?.mode === 'mock' ? '脚本模型演示' : '智能回答') : m.recipient === 'ASSISTANT' ? '与助手的私有咨询' : '商家核查记录' }} · {{ time(m.created_at) }}</span></header><p>{{ m.text }}</p><SupportSources v-if="m.assistant" :citations="m.assistant.citations" /></article><p v-if="assistantState" role="status" class="support-notice">{{ assistantState }}</p></div>
          <div class="support-compose"><template v-if="!merchant"><div v-if="selected.ticket" class="support-recipient"><button :class="{ current: recipient === 'MERCHANT' }" :disabled="busy || !!pending" @click="recipient = 'MERCHANT'">补充给商家</button><button :class="{ current: recipient === 'ASSISTANT' }" :disabled="busy || !!pending" @click="recipient = 'ASSISTANT'">询问智能助手</button></div><p v-if="recipient === 'ASSISTANT'" class="muted">可以直接提问、补充或纠正情况；需要商家核查时，先确认共享内容。</p></template><label v-else>回复方式<select v-model="replyKind" :disabled="busy || !!pending"><option value="REPLY">核查回复</option><option value="REQUEST_INFO">请求客户补充</option></select></label>
          <textarea v-model="draft" aria-label="咨询消息" maxlength="4000" :disabled="busy || !!pending" :placeholder="merchant ? '填写核查回复或需要客户补充的问题' : recipient === 'MERCHANT' ? '补充给当前商家核查单' : '描述问题，或补充、纠正之前的情况'" />
          <div class="support-actions"><button data-action="send" class="primary" :disabled="!draft.trim() || busy || !!pending || (merchant && selected.ticket?.status === 'RESOLVED')" @click="send">{{ merchant ? '发送商家回复' : recipient === 'MERCHANT' ? '发送给商家' : '发送给助手' }}</button><button v-if="!merchant && !selected.ticket" data-action="handoff" :disabled="busy || !!pending" @click="handoff">请商家核查</button><button v-if="!merchant && selected.ticket?.status === 'REPLIED'" :disabled="busy || !!pending" @click="submit({ kind: 'resolve', id: selected.conversation_id, body: { expected_version: selected.version } })">确认问题已解决</button><button :disabled="busy || !!pending" @click="refresh()">刷新进度</button></div></div></template>
          <details class="support-source"><summary>订单与核查编号</summary><p>订单：{{ selected.order_id }} · 商品行：{{ selected.line_id }}</p><p v-if="selected.ticket">核查单：{{ selected.ticket.ticket_id }}</p></details>
        </template>
        <p v-else-if="!loading && merchant">从左侧选择核查单，查看共享材料并回复客户。</p>
      </main>
    </div>
  </section>
</template>
