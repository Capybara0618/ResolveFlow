<script setup lang="ts">
import { useCursorPages } from '../cursor-pages'
import ListPagination from './ListPagination.vue'

import { ref, onMounted, onBeforeUnmount } from 'vue'
import { ApiError, type LoginResponse } from '../client'
import { fulfillmentApi, fulfillmentLabels, type MerchantTrade, type FulfillmentStatus } from '../fulfillment-client'
import { shipmentOwner, readShipmentPending, saveShipmentPending, clearShipmentPending, type ShipmentPending } from '../shipment-pending'
import { formatMinorUnits } from '../money'
import ProductArt from './ProductArt.vue'
import ShippingSummary from './ShippingSummary.vue'
import FulfillmentPanel from './FulfillmentPanel.vue'
import ReviewDialog from './ReviewDialog.vue'
import './admin-trades.css'
const props = defineProps<{ account: LoginResponse }>()
const emit = defineEmits<{ expired: []; working: [value: boolean]; aftercare: [order: string] }>()
const { pageIndex, pageCursor, acceptPage } = useCursorPages<string>()
const items = ref<MerchantTrade[]>([]), detail = ref<MerchantTrade | null>(null), status = ref<FulfillmentStatus | ''>(''), next = ref<string | null>(null)
const loading = ref(false), writing = ref(false), confirming = ref(false), error = ref(''), notice = ref(''), pending = ref<ShipmentPending | null>(null), storageError = ref('')
let owner = '', generation = 0, alive = true
const valid = (g: number) => alive && g === generation
const money = (n: number) => `¥ ${formatMinorUnits(n).replace(' CNY', '')}`
const date = (s: string) => new Date(s).toLocaleString('zh-CN', { hour12: false })
const refunds = { NONE: '无退款', IN_PROGRESS: '退款处理中', PARTIALLY_REFUNDED: '部分商品已退款', REFUNDED: '全部商品已退款' }
const aftercare = { FREE: '无退款占用', RESERVED: '退款金额占用中', CONSUMED: '已退款', MISSING: '售后记录缺失' }
function failure(cause: unknown) { if (cause instanceof ApiError && cause.status === 401) { emit('expired'); return }; error.value = cause instanceof ApiError ? cause.message : '连接暂时中断，请重试读取。' }
async function list(page = 0) {
  if (loading.value || writing.value) return
  const g = ++generation; loading.value = true; error.value = ''; detail.value = null
  try { const result = await fulfillmentApi.orders(props.account.access_token, { ...(status.value ? { status: status.value } : {}), ...(pageCursor(page) ? { cursor: pageCursor(page) } : {}) })
    if (valid(g)) { items.value = result.items; next.value = result.next_cursor; acceptPage(page, next.value) }
  } catch (cause) { if (valid(g)) failure(cause) } finally { if (valid(g)) loading.value = false }
}
async function open(id: string) {
  if (loading.value || writing.value) return
  const g = ++generation; loading.value = true; error.value = ''; detail.value = null
  try { const result = await fulfillmentApi.order(props.account.access_token, id); if (valid(g)) detail.value = result }
  catch (cause) { if (valid(g)) failure(cause) } finally { if (valid(g)) loading.value = false }
}
async function refresh() { if (detail.value?.purchase.order_id) await open(detail.value.purchase.order_id); else await list(pageIndex.value) }
async function ship(original?: ShipmentPending) {
  if (writing.value || loading.value || storageError.value) return
  const target = detail.value
  if (!original && (!target?.can_ship || !target.purchase.order_id || !target.fulfillment.version || pending.value)) return
  const request: ShipmentPending = original || { order: target!.purchase.order_id!, key: crypto.randomUUID(), request: { expected_version: target!.fulfillment.version! } }
  try { saveShipmentPending(owner, request); pending.value = request }
  catch { storageError.value = '浏览器无法保存原发货请求，暂不能发货。请检查会话存储后重新打开本页。'; return }
  const g = generation; writing.value = true; emit('working', true); error.value = ''; notice.value = ''
  try {
    const result = await fulfillmentApi.ship(props.account.access_token, request.order, request.request, request.key)
    if (!valid(g)) return
    clearShipmentPending(owner, request.key); pending.value = null; confirming.value = false
    notice.value = '模拟发货已确认。'
    if (detail.value?.purchase.order_id === request.order) detail.value = { ...detail.value, fulfillment: result, can_ship: false, blocked_reason: '此订单已完成首次模拟发货。' }
    const fresh = await fulfillmentApi.order(props.account.access_token, request.order)
    if (valid(g)) detail.value = fresh
  } catch (cause) {
    if (!valid(g)) return
    confirming.value = false
    if (pending.value && (!(cause instanceof ApiError) || cause.status >= 500)) error.value = '发货结果尚未确认。请读取订单或重试原请求，不要另发一单。'
    else if (cause instanceof ApiError && cause.status === 401) failure(cause)
    else { if (detail.value) detail.value = { ...detail.value, can_ship: false, blocked_reason: '发货请求被拒绝，请刷新订单核对当前状态。' }; try { clearShipmentPending(owner, request.key); pending.value = null } catch { storageError.value = '原发货请求暂不能更新，请保留浏览器会话。' }; failure(cause) }
  } finally { if (valid(g)) { writing.value = false; emit('working', false) } }
}
onMounted(async () => {
  try { owner = shipmentOwner(props.account); pending.value = readShipmentPending(owner) }
  catch (cause) { storageError.value = cause instanceof Error ? cause.message : '原发货请求无法读取。' }
  if (pending.value) await open(pending.value.order); else await list(pageIndex.value)
})
onBeforeUnmount(() => { alive = false; ++generation; emit('working', false) })
</script>
<template>
  <main class="admin-workspace merchant-trades">
    <header class="trade-heading"><div><h1>{{ detail ? '订单详情' : '交易订单' }}</h1><p>{{ account.merchant_name || account.merchant_id }}</p></div><button class="secondary-button" :disabled="loading || writing" @click="refresh">刷新订单</button></header>
    <p v-if="error" role="alert" class="trade-error">{{ error }}</p><p v-if="notice" role="status" class="trade-notice">{{ notice }}</p><p v-if="storageError" role="alert" class="trade-error">{{ storageError }}</p>
    <section v-if="pending" class="trade-recovery" aria-label="原发货请求"><h2>发货结果待确认</h2><p>保留原请求，确认后才能继续发货。</p><div class="trade-actions"><button class="secondary-button" :disabled="loading || writing" @click="open(pending.order)">读取原订单</button><button class="primary-button" :disabled="loading || writing || !!storageError" data-test="retry-shipment" @click="ship(pending)">重试原发货请求</button></div></section>
    <p v-if="loading" role="status" class="trade-loading">正在读取订单…</p>
    <template v-if="detail">
      <ShippingSummary v-if="detail.purchase.order_id" :token="account.access_token" :purchase="detail.purchase.order_id" merchant @expired="emit('expired')" />
      <button class="text-button trade-back" :disabled="loading || writing" @click="list(pageIndex)">返回交易订单</button>
      <section class="trade-summary"><div><h2>已付款</h2><p>{{ detail.purchase.paid_at ? date(detail.purchase.paid_at) : '支付时间未提供' }}</p></div><div><span>原实付</span><strong>{{ money(detail.purchase.total_amount) }}</strong></div><div><span>售后汇总</span><strong class="trade-refund">{{ refunds[detail.purchase.refund_status || 'NONE'] }}</strong></div></section>
      <div class="trade-detail-layout"><section class="trade-goods"><h2>订单商品</h2><article v-for="line in detail.purchase.lines" :key="line.line_id || line.sku" class="trade-product"><ProductArt v-if="line.asset_key" :asset="line.asset_key" :name="line.product_name || line.sku" :variant="line.variant ?? ''" /><div><h3>{{ line.product_name || line.sku }}</h3><p>{{ line.variant || '规格未提供' }} · 数量 × {{ line.quantity }}</p><strong>实付 {{ money(line.line_amount) }}</strong><template v-for="fact in detail.line_aftercare.filter(f => f.line_id === line.line_id)" :key="fact.line_id"><p class="trade-line-refund">{{ aftercare[fact.state] }}<span v-if="fact.reserved_amount"> · {{ money(fact.reserved_amount) }}</span></p></template></div></article><button class="text-button" :disabled="writing" @click="emit('aftercare', detail.purchase.order_id!)">查看此订单的售后工单 →</button><details class="trade-ids"><summary>查看订单编号</summary><p>{{ detail.purchase.order_id }}</p><p v-for="line in detail.purchase.lines" :key="line.sku">商品行 {{ line.line_id }}</p></details></section>
      <aside><FulfillmentPanel :fact="detail.fulfillment" :lines="detail.purchase.lines" /><section class="trade-dispatch"><h2>商家操作</h2><p v-if="!detail.can_ship">{{ detail.blocked_reason || '当前订单不能发货。' }}</p><template v-else><button class="primary-button" :disabled="loading || writing || !!pending || !!storageError" data-test="open-shipment" @click="confirming = true">模拟发货</button></template></section></aside></div>
    </template>
    <template v-else>
      <div class="trade-filters"><button :class="{ current: !status }" :disabled="loading || writing" @click="status = ''; list()">全部已付订单</button><button v-for="(label, value) in fulfillmentLabels" :key="value" :class="{ current: status === value }" :disabled="loading || writing" @click="status = value; list()">{{ label }}</button></div>
      <ListPagination :page="pageIndex" :has-next="!!next" :disabled="loading || writing || !!pending" label="交易订单分页" @change="list" /><p v-if="!items.length && !loading && !error" class="trade-empty">当前筛选下没有订单。</p>
      <article v-for="trade in items" :key="trade.purchase.order_id!" class="trade-order"><header><span>{{ trade.purchase.paid_at ? date(trade.purchase.paid_at) : '支付时间未提供' }}</span><span class="fulfillment-chip">{{ fulfillmentLabels[trade.fulfillment.status] }}</span></header><div class="trade-order-body"><div class="trade-list-goods"><div v-for="line in trade.purchase.lines" :key="line.line_id || line.sku" class="trade-list-product"><ProductArt v-if="line.asset_key" :asset="line.asset_key" :name="line.product_name || line.sku" :variant="line.variant ?? ''" /><div><h2>{{ line.product_name || line.sku }}</h2><p>{{ line.variant || '规格未提供' }} · 数量 × {{ line.quantity }}</p></div></div></div><div class="trade-list-total"><span>原实付</span><strong>{{ money(trade.purchase.total_amount) }}</strong><p>{{ refunds[trade.purchase.refund_status || 'NONE'] }}</p><button class="secondary-button" :disabled="loading || writing" @click="open(trade.purchase.order_id!)">查看订单</button></div></div></article>
      <ListPagination :page="pageIndex" :has-next="!!next" :disabled="loading || writing || !!pending" label="交易订单分页" @change="list" />
    </template>
    <ReviewDialog v-if="confirming && detail" title="确认模拟发货" workspace="交易订单" :busy="writing" @close="confirming = false"><div class="trade-confirm"><p>将这笔订单的 {{ detail.purchase.lines.length }} 类商品全部标记为已发货？</p><div class="trade-actions"><button class="secondary-button" :disabled="writing" @click="confirming = false">返回</button><button class="primary-button" :disabled="writing" data-test="confirm-shipment" @click="ship()">{{ writing ? '正在确认…' : '确认模拟发货' }}</button></div></div></ReviewDialog>
  </main>
</template>
