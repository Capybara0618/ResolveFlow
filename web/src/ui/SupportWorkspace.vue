<script setup lang="ts">
import StoreMark from './StoreMark.vue'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ApiError, coreApi, type LoginResponse, type OrderLine } from '../client'
import { supportApi, saveSupportPending, readSupportPending, clearSupportPending, type SupportConversation, type SupportCommand, type SupportPending } from '../support-client'
import { formatMinorUnits } from '../money'
import ProductArt from './ProductArt.vue'
import MessageIdentity from './MessageIdentity.vue'
import UserAvatar from './UserAvatar.vue'
import SupportSources from './SupportSources.vue'
import BuyerSources from './BuyerSources.vue'
import SupportContext from './SupportContext.vue'
import SupportDialog from './SupportDialog.vue'
import SupportRefundCard from './SupportRefundCard.vue'
import SupportBuyerReply from './SupportBuyerReply.vue'
import Icon from './ReviewIcon.vue'
import { assistantOffers, conversationTitle, stamp, tail } from '../support-view'
import { applySupportEvent, mergeSupportConversation, watchSupportEvents } from '../support-events'
import { readSupportSelection, saveSupportSelection } from '../tab-session'
import './support-workspace.css'
import './buyer-support.css'

const props = defineProps<{ account: LoginResponse; initialId?: string }>()
const emit = defineEmits<{ expired: [] }>()
const merchant = computed(() => props.account.role === 'MERCHANT_ADMIN')
const owner = `${props.account.role}:${props.account.buyer_id ?? props.account.merchant_id}`
const token = props.account.access_token
const items = ref<SupportConversation[]>([]), next = ref<number | null>(null)
const orders = ref<OrderLine[]>([]), orderCursor = ref<string | null>(null)
const orderLoading = ref(false), orderLoaded = ref(false), orderError = ref('')
const selected = ref<SupportConversation | null>(null), choosing = ref(false)
const search = ref(''), orderSearch = ref(''), filter = ref('ALL'), historyTab = ref(false)
const cache = reactive(new Map<string, SupportConversation>())
const workspace = ref<HTMLElement>(), messagePane = ref<HTMLElement>()
const refundEntry = ref<HTMLElement>(), contextOpen = ref(window.innerWidth > 1100)
const loading = ref(false), busy = ref(false), error = ref(''), notice = ref(''), draft = ref('')
const recipient = ref<'ASSISTANT' | 'MERCHANT'>('ASSISTANT'), replyKind = ref<'REPLY' | 'REQUEST_INFO'>('REPLY')
const preview = ref(false), summary = ref(''), share = ref<string[]>([]), previewVersion = ref(0)
const shareReport = ref(false)
const tabs = [{ key: 'ALL', label: '全部' }, { key: 'PENDING', label: '待处理' }, { key: 'WAITING_CUSTOMER', label: '待补充' }, { key: 'ANSWERED', label: '已答复' }]
const inFilter = (c: SupportConversation, key: string) => key === 'ALL' || (key === 'ANSWERED' ? ['REPLIED', 'RESOLVED'].includes(c.ticket?.status ?? '') : c.ticket?.status === key)
const itemView = (c: SupportConversation) => (cache.get(c.conversation_id)?.version ?? -1) >= c.version ? cache.get(c.conversation_id)! : c
const matching = computed(() => items.value.map(itemView).filter(c => [c.product.name, c.store_name, c.order_id, c.ticket?.summary ?? '', conversationTitle(c)].join(' ').toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())))
const visibleItems = computed(() => matching.value.filter(c => !merchant.value || inFilter(c, filter.value)))
const visibleOrders = computed(() => orders.value.filter(o => [o.product_name, o.sku, o.merchant_name, o.order_id].join(' ').toLocaleLowerCase().includes(orderSearch.value.trim().toLocaleLowerCase())))
const latestAssistant = computed(() => selected.value?.messages.find(m => m.author === 'ASSISTANT' && m.sequence === selected.value?.version && m.assistant))
const sharedCitations = computed(() => latestAssistant.value?.assistant?.citations.filter(c => c.source_type !== 'CONVERSATION') ?? [])
const assistantBusy = computed(() => !merchant.value && ['PENDING', 'RUNNING'].includes(selected.value?.assistant_turn?.status ?? ''))
const assistantState = computed(() => {
  const turn = selected.value?.assistant_turn
  if (!turn || merchant.value) return ''
  const category = selected.value?.generation?.activity
  if (turn.status === 'RUNNING' && category) return ({ ORDER: '正在核对订单…', SHIPMENT: '正在查看物流…', POLICY: '正在查阅售后政策…', GUIDE: '正在查找处理方式…', HISTORY: '正在查看之前的沟通…' } as Record<string, string>)[category] || '正在帮你查看，请稍候…'
  if (turn.status === 'RUNNING' && selected.value?.generation?.attempt_id) return generationText.value ? '' : '正在完善回答…'
  return { PENDING: '问题已收到，正在准备查看…', RUNNING: '正在帮你查看，请稍候…', SUCCEEDED: '', FAILED: '助手本次未能完成回答，可重新提问或请商家核查。', STALE: '问题已更新，旧回复不会发布。' }[turn.status]
})
const generationText = computed(() => Object.entries(selected.value?.generation?.parts ?? {}).sort(([a], [b]) => a.localeCompare(b)).map(([, text]) => text).join('\n\n'))
const pending = ref<SupportPending | null>(readSupportPending(owner))
let alive = true, generation = 0, timer: ReturnType<typeof setInterval> | undefined
let expandedHistory = false
const streamConnected = ref(false), newContent = ref(false)
let subscription: AbortController | undefined, nearBottom = true, streamRefreshNeeded = false, streamRefreshRevision = 0, refreshing = false, lastFallback = 0
const labels = { PENDING: '待商家处理', WAITING_CUSTOMER: merchant.value ? '待客户补充' : '待你补充', REPLIED: '商家已回复', RESOLVED: '咨询已解决' }
const privateMessages = computed(() => selected.value?.messages.filter(m => m.author === 'CUSTOMER' && m.recipient === 'ASSISTANT') ?? [])
function fail(cause: unknown) {
  if (cause instanceof ApiError && cause.status === 401) emit('expired')
  error.value = cause instanceof ApiError ? cause.message : '连接中断，暂时无法确认结果。'
}
function remember(value: SupportConversation) {
  cache.set(value.conversation_id, value)
  const index = items.value.findIndex(c => c.conversation_id === value.conversation_id)
  if (index >= 0) items.value[index] = { ...value, messages: [] }
  else items.value.unshift({ ...value, messages: [] })
}
function setSelected(value: SupportConversation) {
  const resetRecipient = selected.value?.conversation_id !== value.conversation_id || (!selected.value?.ticket && value.ticket)
  const same = selected.value?.conversation_id === value.conversation_id
  if (!same) expandedHistory = false
  selected.value = same ? mergeSupportConversation(selected.value!, value) : value; choosing.value = false
  const remembered = merchant.value ? value.ticket?.ticket_id : value.conversation_id
  if (remembered) saveSupportSelection(owner, remembered)
  if (resetRecipient) recipient.value = value.ticket ? 'MERCHANT' : 'ASSISTANT'
  remember(selected.value)
}
async function list(more = false) {
  const result = merchant.value ? await supportApi.tickets(token, more ? next.value : null) : await supportApi.conversations(token, more ? next.value : null)
  if (!alive) return
  items.value = more ? [...items.value, ...result.items] : result.items; next.value = result.next_before
}
async function readOrders(more = false) {
  if (orderLoading.value) return
  orderLoading.value = true; orderError.value = ''
  try {
    const result = await coreApi.orders(token, more ? orderCursor.value ?? undefined : undefined)
    if (!alive) return
    orders.value = more ? [...orders.value, ...result.items] : result.items; orderCursor.value = result.page.next_cursor ?? null; orderLoaded.value = true
  } catch (cause) {
    if (alive) orderError.value = '订单读取失败，请重试。'
    throw cause
  } finally { if (alive) orderLoading.value = false }
}
async function load() {
  loading.value = true; error.value = ''
  try { await Promise.all([list(), merchant.value ? Promise.resolve() : readOrders()]) }
  catch (cause) { if (alive) fail(cause) } finally { if (alive) loading.value = false }
  if (alive && !selected.value && !pending.value && !error.value) {
    const remembered = props.initialId ?? readSupportSelection(owner)
    if (remembered) {
      const g = generation
      try {
        const value = await supportApi.read(token, remembered, merchant.value)
        if (alive && g === generation && !selected.value && !pending.value) setSelected(value)
        return
      } catch (cause) {
        if (!(cause instanceof ApiError && cause.status === 404)) { if (alive) fail(cause); return }
      }
    }
    if (items.value.length) await open(items.value[0])
    else if (!merchant.value) choosing.value = true
  }
}
async function open(item: SupportConversation) {
  if (busy.value || pending.value) return
  const g = ++generation; loading.value = true; error.value = ''; preview.value = false; historyTab.value = false
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
  if (!c || busy.value || preview.value || choosing.value || pending.value || loading.value) return
  if (refreshing) return
  refreshing = true
  const g = generation
  const revision = streamRefreshRevision
  try {
    const value = await supportApi.read(token, merchant.value ? c.ticket!.ticket_id : c.conversation_id, merchant.value)
    if (alive && g === generation && selected.value?.conversation_id === c.conversation_id) {
      selected.value = mergeSupportConversation(selected.value, value)
      streamRefreshNeeded = revision !== streamRefreshRevision
      remember(selected.value)
      if (notice.value === '问题已发送，助手正在处理。' && value.assistant_turn && !['PENDING', 'RUNNING'].includes(value.assistant_turn.status)) notice.value = ''
      if (!quiet) error.value = ''
    }
  } catch (cause) { if (alive && g === generation && (!quiet || cause instanceof ApiError && cause.status === 401)) fail(cause) }
  finally { refreshing = false }
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
  if (merchant.value && c.ticket?.status === 'RESOLVED') return
  if (merchant.value) await submit({ kind: 'reply', id: c.ticket!.ticket_id, body: { expected_version: c.version, text: draft.value.trim(), kind: replyKind.value } })
  else await submit({ kind: 'send', id: c.conversation_id, body: { expected_version: c.version, text: draft.value.trim(), recipient: recipient.value } })
}
function pickOrder() { if (!busy.value && !pending.value && !loading.value) { orderSearch.value = ''; choosing.value = true; if (!orderLoaded.value) void readOrders().catch(fail) } }
function enter(event: KeyboardEvent) { if (!event.isComposing && event.keyCode !== 229) { event.preventDefault(); void send() } }
function fit() { if (workspace.value) workspace.value.style.setProperty('--support-height', `${Math.max(420, window.innerHeight - workspace.value.getBoundingClientRect().top)}px`) }
function reading() {
  const pane = messagePane.value
  if (pane) nearBottom = pane.scrollHeight - pane.scrollTop - pane.clientHeight <= 80
  if (nearBottom) newContent.value = false
}
function latest() {
  expandedHistory = false; nearBottom = true; newContent.value = false
  if (messagePane.value) messagePane.value.scrollTop = messagePane.value.scrollHeight
}
function refundLayout() {
  if (!expandedHistory && nearBottom) void nextTick(latest)
  else if (selected.value) newContent.value = true
}
watch(() => selected.value?.conversation_id, id => {
  subscription?.abort(); streamConnected.value = false; streamRefreshNeeded = false
  nearBottom = true; newContent.value = false
  if (!id || merchant.value) return
  const controller = new AbortController(); subscription = controller
  void watchSupportEvents(id, token, event => {
    if (!alive || controller.signal.aborted || selected.value?.conversation_id !== id) return
    const value = applySupportEvent(selected.value, event)
    if (value === null) { streamRefreshNeeded = true; ++streamRefreshRevision; void refresh(true); return }
    selected.value = value; remember(value)
    if (!value.assistant_turn || !['PENDING', 'RUNNING'].includes(value.assistant_turn.status)) notice.value = ''
  }, controller.signal, connected => { if (!controller.signal.aborted) streamConnected.value = connected })
    .catch(cause => {
      if (!alive || controller.signal.aborted) return
      if (cause instanceof Error && /HTTP 401/.test(cause.message)) emit('expired')
      streamConnected.value = false
    })
})
watch(() => [selected.value?.messages.at(-1)?.message_id, generationText.value], async () => {
  await nextTick()
  if (!expandedHistory && nearBottom && messagePane.value) latest()
  else if (selected.value) newContent.value = true
})
onMounted(() => {
  void load(); void nextTick(fit); window.addEventListener('resize', fit)
  document.fonts?.addEventListener('loadingdone', refundLayout)
  timer = setInterval(() => {
    if (document.hidden) return
    const active = ['PENDING', 'RUNNING'].includes(selected.value?.assistant_turn?.status ?? '')
    const fallback = merchant.value || !!selected.value?.ticket || active
    if (streamRefreshNeeded || (!merchant.value && !streamConnected.value && active) || (fallback && Date.now() - lastFallback >= 8000)) {
      lastFallback = Date.now(); void refresh(true)
    }
  }, 2000)
})
onBeforeUnmount(() => { alive = false; ++generation; subscription?.abort(); window.removeEventListener('resize', fit); document.fonts?.removeEventListener('loadingdone', refundLayout); if (timer) clearInterval(timer) })
</script>

<template>
  <section ref="workspace" :class="['support-workspace', { 'merchant-support': merchant, 'buyer-support': !merchant }]">
    <div v-if="error || notice || pending" class="support-alerts">
      <p v-if="error" role="alert" class="support-error">{{ error }} <button v-if="selected && !pending" @click="refresh()">刷新当前记录</button></p>
      <p v-if="notice" role="status" class="support-notice">{{ notice }}</p>
      <p v-if="pending" role="status" class="support-notice">“{{ pending.label }}”的提交结果尚待确认。<button data-action="retry" :disabled="busy" @click="retry">{{ busy ? '正在确认…' : '用原请求确认结果' }}</button></p>
    </div>
    <div class="support-grid" :class="{ 'context-collapsed': !merchant && !contextOpen }" :inert="choosing || preview ? true : undefined">
      <aside class="support-history" aria-label="咨询列表">
        <header class="support-queue-heading"><h1>{{ merchant ? '咨询核查' : '售后咨询' }} <small v-if="merchant">{{ items.length }}</small></h1><button class="icon-action" aria-label="刷新咨询列表" :disabled="loading || busy || !!pending" @click="load"><Icon name="clock" :size="17" /></button></header>
        <button v-if="!merchant" class="primary support-new" :disabled="loading || busy || !!pending" @click="pickOrder"><span>＋</span> 选择订单</button>
        <label class="support-search"><Icon name="search" :size="17" /><input v-model="search" aria-label="搜索已加载咨询" :placeholder="merchant ? '搜索客户问题或订单' : '搜索咨询记录'" /></label>
        <div v-if="merchant" class="support-filters" aria-label="核查状态筛选"><button v-for="tab in tabs" :key="tab.key" :class="{ current: filter === tab.key }" :aria-pressed="filter === tab.key" @click="filter = tab.key">{{ tab.label }} <small>{{ matching.filter(c => inFilter(c, tab.key)).length }}</small></button></div>

        <div class="support-history-scroll">
          <button v-for="item in visibleItems" :key="item.conversation_id" data-conversation :data-line-id="item.line_id" :aria-current="selected?.conversation_id === item.conversation_id ? 'true' : undefined" :disabled="busy || !!pending" :class="['support-history-item', { current: selected?.conversation_id === item.conversation_id }]" @click="open(item)">
            <ProductArt :asset="item.product.asset_key || ''" :name="item.product.name" :variant="item.product.variant ?? ''" /><div><strong :title="merchant ? conversationTitle(item) : item.product.name">{{ merchant ? conversationTitle(item) : item.product.name }}</strong><span><StoreMark v-if="!merchant" :id="item.merchant_id" :size="13" />{{ item.store_name }}<template v-if="merchant"> · {{ item.product.name }}</template></span><small v-if="!merchant && conversationTitle(item) !== item.product.name" class="buyer-history-preview" :title="conversationTitle(item)">{{ conversationTitle(item) }}</small><small v-if="merchant">订单尾号 {{ tail(item.order_id) }}</small><em v-if="merchant || item.ticket" :class="['support-tag', item.ticket?.status === 'PENDING' ? 'amber' : 'blue']">{{ item.ticket ? labels[item.ticket.status] : '咨询中' }}</em></div>
          </button>
          <p v-if="!visibleItems.length && !loading" class="support-list-empty">{{ search ? '当前已加载记录中没有匹配项。' : merchant ? '当前筛选下暂无核查单。' : '选择订单，开始一次咨询。' }}</p>
          <button v-if="next" class="support-more" :disabled="loading" @click="list(true).catch(fail)">加载更多咨询</button>
        </div>
      </aside>

      <main class="support-main" :aria-busy="loading">
        <template v-if="selected">
          <header class="support-chat-heading"><div class="support-chat-identity"><UserAvatar kind="ASSISTANT" name="售后助手" :size="34" /><div><h2 :title="merchant ? conversationTitle(selected) : '售后助手'">{{ merchant ? conversationTitle(selected) : '售后助手' }}</h2><p>{{ selected.store_name }} · {{ merchant ? `核查单 #${tail(selected.ticket!.ticket_id)}` : selected.product.name }}</p></div></div>
            <span v-if="selected.ticket" class="support-tag amber">{{ labels[selected.ticket.status] }}</span><button v-if="!merchant && !selected.ticket" data-action="handoff" class="support-heading-handoff" :disabled="busy || !!pending" @click="handoff"><Icon name="file" :size="16" />请商家核查</button>
            <button v-if="!merchant" class="support-context-toggle" data-action="toggle-context" :aria-expanded="contextOpen" aria-controls="support-order-context" @click="contextOpen = !contextOpen; refundLayout()">{{ contextOpen ? '收起资料' : '订单与物流' }}</button>
          </header>
          <div v-if="merchant" class="support-chat-tabs"><button :class="{ current: !historyTab }" @click="historyTab = false">客户沟通</button><button :class="{ current: historyTab }" @click="historyTab = true">消息记录</button></div>

          <div ref="messagePane" class="support-messages" tabindex="0" :role="historyTab ? undefined : 'log'" aria-label="咨询消息记录" @scroll="reading">
            <button v-if="selected.next_before_sequence" class="support-older" :disabled="loading" @click="older">读取更早消息</button>
            <section v-if="selected.ticket" class="support-ticket"><Icon name="file" :size="22" /><div><h3>{{ merchant ? '客户已确认转交' : '已转交商家核查' }}</h3><p>{{ selected.ticket.summary }}</p></div></section>
            <template v-if="merchant && !historyTab"><div v-if="selected.ticket?.shared_messages.length" class="support-date-divider">客户共享原文</div><article v-for="m in selected.ticket?.shared_messages" :key="m.message_id" class="support-message shared-original"><MessageIdentity :token="token" :conversation="selected.conversation_id" :message="m.message_id" :author="m.author" /><div class="support-message-content"><div class="support-message-bubble"><p>{{ m.text }}</p></div><small class="support-message-meta">客户共享原文 · {{ stamp(m.created_at, true) }}</small></div></article></template>
            <div v-if="!selected.messages.length && !merchant" class="support-welcome"><UserAvatar kind="ASSISTANT" name="售后助手" :size="40" /><h2>这件商品遇到了什么问题？</h2><div><button @click="draft = '请帮我查询这件商品的物流情况。'">查询物流</button><button @click="draft = '请说明这件商品适用的售后政策。'">了解售后政策</button></div></div>
            <p v-if="!selected.messages.length && merchant && !selected.ticket?.shared_messages.length" class="support-list-empty">客户补充与商家回复将显示在这里。</p>
            <article v-for="m in selected.messages" :key="m.message_id" :class="['support-message', m.author.toLowerCase(), { 'message-ledger': historyTab, outgoing: m.author === (merchant ? 'MERCHANT' : 'CUSTOMER') }]">
              <MessageIdentity :token="account.access_token" :conversation="selected.conversation_id" :message="m.message_id" :author="m.author" />
              <div class="support-message-content"><div class="support-message-bubble"><SupportBuyerReply v-if="!merchant && m.author === 'ASSISTANT'" :message="m" /><p v-else>{{ m.text }}</p></div>
                <small class="support-message-meta"><time :datetime="m.created_at">{{ stamp(m.created_at, true) }}</time><template v-if="m.author === 'ASSISTANT' && m.assistant?.mode === 'mock'"> · 脚本模型演示</template><template v-else-if="m.author !== 'ASSISTANT' && (merchant || m.recipient === 'MERCHANT')"> · {{ m.recipient === 'ASSISTANT' ? '仅你和助手可见' : '商家核查记录' }}</template></small>
                <BuyerSources v-if="m.assistant && !merchant" :citations="m.assistant.citations" /><SupportSources v-else-if="m.assistant" :citations="m.assistant.citations" compact />
              </div>
            </article>
            <article v-if="!merchant && selected.generation?.attempt_id && generationText" class="support-message assistant" data-generation>
              <UserAvatar kind="ASSISTANT" name="售后助手" :size="32" />
              <div class="support-message-content">
                <div class="support-message-bubble"><p>{{ generationText || '正在完善回答…' }}<span aria-hidden="true" class="support-stream-caret">▍</span></p></div>
                <small class="support-message-meta">正在生成…</small>
              </div>
            </article>
            <div v-if="assistantState" role="status" class="support-agent-state" :class="{ 'support-agent-waiting': assistantBusy }" :data-buyer-waiting="assistantBusy ? '' : undefined"><span v-if="assistantBusy" class="support-waiting-dots" aria-hidden="true"><i></i><i></i><i></i></span><span>{{ assistantState }}</span></div>
            <SupportRefundCard v-if="!merchant && !historyTab" :key="`${owner}:${selected.conversation_id}`" :token="token" :owner="owner" :conversation="selected" :entry-target="refundEntry" @layout-change="refundLayout" @expired="emit('expired')" />
            <section v-if="!merchant && !selected.ticket && latestAssistant && assistantOffers(latestAssistant, 'MERCHANT_REVIEW')" class="support-handoff-card"><Icon name="file" :size="25" /><div><h3>需要商家进一步核查</h3><p>将你的问题与相关依据整理给商家。</p><blockquote>{{ latestAssistant.assistant!.handoff_summary }}</blockquote><div><small>可编辑 · 确认后共享</small><button class="primary" data-action="preview-handoff" :disabled="busy || !!pending" @click="handoff">预览并转交商家</button></div></div></section>
          </div>

          <button v-if="newContent" class="text-action" data-action="latest-messages" @click="latest">有新内容 · 回到最新</button>
          <div class="support-compose">
            <div v-if="merchant" class="support-recipient"><button :class="{ current: replyKind === 'REPLY' }" @click="replyKind = 'REPLY'">核查回复</button><button :class="{ current: replyKind === 'REQUEST_INFO' }" @click="replyKind = 'REQUEST_INFO'">请求客户补充</button></div>
            <div v-else-if="selected.ticket" class="support-recipient"><button :class="{ current: recipient === 'MERCHANT' }" :disabled="busy || !!pending" @click="recipient = 'MERCHANT'">补充给商家</button><button :class="{ current: recipient === 'ASSISTANT' }" :disabled="busy || !!pending" @click="recipient = 'ASSISTANT'">询问智能助手</button></div>
            <div class="support-input-box"><textarea v-model="draft" aria-label="咨询消息" maxlength="4000" :disabled="busy || !!pending || (merchant && selected.ticket?.status === 'RESOLVED')" :placeholder="merchant ? '填写核查回复或需要客户补充的问题…' : recipient === 'MERCHANT' ? '补充给当前商家核查单…' : '继续描述问题，或补充、纠正之前的信息…'" @keydown.enter.exact="enter" />
              <div class="support-actions"><small v-if="merchant">客户将在原咨询中看到回复</small><button v-if="!merchant && selected.ticket?.status === 'REPLIED'" :disabled="busy || !!pending" @click="submit({ kind: 'resolve', id: selected.conversation_id, body: { expected_version: selected.version } })">确认问题已解决</button><button data-action="send" class="primary" :disabled="!draft.trim() || busy || !!pending || (merchant && selected.ticket?.status === 'RESOLVED')" @click="send">{{ busy ? '提交中…' : merchant ? '发送回复' : '发送' }}</button></div>
            </div><div class="support-compose-meta"><small v-if="!merchant && selected.ticket">{{ recipient === 'MERCHANT' ? '补充给商家核查' : '仅你和助手可见' }}</small><div v-if="!merchant" ref="refundEntry" class="support-refund-shortcut"></div><button class="text-action support-refresh" :disabled="busy || !!pending" @click="refresh()">刷新记录</button></div>
          </div>
        </template>
        <div v-else class="support-empty"><span class="support-avatar assistant"><Icon :name="loading ? 'clock' : 'queue'" :size="32" /></span><h2>{{ loading ? '正在读取咨询…' : merchant ? '本店咨询，集中核查' : '售后咨询，从这件商品开始' }}</h2><button v-if="!merchant && !loading" class="primary" @click="pickOrder">选择订单商品</button></div>
      </main>
      <SupportContext v-if="selected" id="support-order-context" :collapsed="!merchant && !contextOpen" :conversation="selected" :merchant="merchant" :disabled="loading || busy || !!pending" @change-order="pickOrder" />
      <aside v-else class="support-context support-context-empty"><Icon name="box" :size="28" /><p>选择咨询后查看订单与相关依据</p></aside>
    </div>

    <SupportDialog v-if="choosing" title="选择需要咨询的商品" subtitle="按订单商品独立咨询，切换后仍能恢复历史记录。" @close="choosing = false">
      <label class="support-search"><Icon name="search" /><input v-model="orderSearch" data-autofocus aria-label="搜索已加载订单商品" placeholder="搜索商品、店铺或订单号" /></label>
      <p v-if="orderLoading" role="status" class="support-list-empty">正在读取订单…</p><p v-if="orderError" role="alert" class="support-error">{{ orderError }} <button @click="readOrders().catch(fail)">重试读取订单</button></p>
      <div class="support-order-grid"><button v-for="line in visibleOrders" :key="line.line_id" class="support-order" :data-line-id="line.line_id" :disabled="loading || busy || !!pending" @click="choose(line)"><ProductArt :asset="line.asset_key || ''" :name="line.product_name || line.sku" :variant="line.variant_text ?? ''" /><div><strong>{{ line.product_name || line.sku }}</strong><p>{{ line.merchant_name }} · {{ line.variant_text || '默认规格' }} · {{ line.quantity }}件</p><small>{{ stamp(line.paid_at, true) || '历史订单' }} · 尾号 {{ tail(line.order_id) }}</small></div><span>¥{{ formatMinorUnits(line.line_paid_amount).replace(' CNY', '') }}<small>咨询这件商品</small></span></button></div>
      <p v-if="!visibleOrders.length && !orderLoading && !orderError" class="support-list-empty">{{ orderSearch ? '当前已加载订单中没有匹配商品。' : '暂无已付款订单，可以先在商城购买商品。' }}</p><button v-if="orderCursor" class="support-more" :disabled="orderLoading" @click="readOrders(true).catch(fail)">更多订单商品</button>
    </SupportDialog>
    <SupportDialog v-if="preview && selected" title="确认转交商家核查" subtitle="确认共享给商家的内容" @close="!busy && !pending && (preview = false)">
      <div class="support-preview"><label class="support-field">核查摘要<textarea v-model="summary" data-autofocus aria-label="核查摘要" maxlength="2000" /></label>
        <fieldset v-if="latestAssistant"><legend>调查依据</legend><label class="support-check"><input v-model="shareReport" data-share-report type="checkbox" />共享此回答的订单、物流和政策依据</label><SupportSources :citations="sharedCitations" /><p class="context-muted">对话原文仅按下方选择共享。</p></fieldset>
        <fieldset><legend>选择共享的相关原文（最多20条）</legend><label v-for="m in privateMessages" :key="m.message_id" class="support-check"><input v-model="share" type="checkbox" :value="m.message_id" :disabled="share.length >= 20 && !share.includes(m.message_id)" /><span>{{ m.text }}</span></label><p v-if="!privateMessages.length" class="context-muted">尚无私有咨询消息，可仅转交摘要。</p></fieldset>
      </div>
      <template #footer><button :disabled="busy || !!pending" @click="preview = false">返回咨询</button><button data-action="confirm-handoff" class="primary" :disabled="!summary.trim() || busy || !!pending" @click="confirmHandoff">确认转交商家</button></template>
    </SupportDialog>
  </section>
</template>
