<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { ApiError, coreApi, type CustomerOrderLine, type LoginResponse } from '../client'
import { shopApi, type Purchase, type PurchaseStatus, type ShopStore } from '../shop-client'
import { formatMinorUnits } from '../money'
import ProductArt from './ProductArt.vue'
import ReviewDialog from './ReviewDialog.vue'
import './buyer-orders.css'
import FulfillmentPanel from './FulfillmentPanel.vue'
import { fulfillmentApi, type OrderFulfillment } from '../fulfillment-client'

const props = defineProps<{ account: LoginResponse }>()
const emit = defineEmits<{ expired: []; navigate: [hash: string] }>()
const fulfillment = ref<OrderFulfillment | null>(null), fulfillmentLoading = ref(false), fulfillmentError = ref('')
const items = ref<Purchase[]>([]), detail = ref<Purchase | null>(null), stores = ref<ShopStore[]>([])
const store = ref(''), status = ref<PurchaseStatus | ''>(''), next = ref<string | null>(null)
const loading = ref(false), writing = ref(false), uncertain = ref(false), cancelUnknown = ref(false), cancelOpen = ref(false)
const error = ref(''), notice = ref(''), mode = ref<'list' | 'detail' | 'payment'>('list'), now = ref(Date.now())
const eligibility = ref<Record<string, CustomerOrderLine | null>>({}), eligibilityErrors = ref<Record<string, boolean>>({})
let fulfillmentGeneration = 0
let generation = 0, alive = true, timer: ReturnType<typeof setInterval> | undefined, memoryKey = ''
const labels: Record<PurchaseStatus, string> = { WAITING_PAYMENT: '待付款', PAYMENT_PENDING: '付款结果待确认', PAID: '已付款', CANCELLED: '已取消', EXPIRED: '已到期' }
const refundLabels = { NONE: '无退款', IN_PROGRESS: '退款处理中', PARTIALLY_REFUNDED: '部分商品已退款', REFUNDED: '已全部退款' }
const money = (n: number) => `¥ ${formatMinorUnits(n).replace(' CNY', '')}`
const time = (s: string) => new Date(s).toLocaleString('zh-CN', { hour12: false })
const deadlinePassed = computed(() => detail.value?.status === 'WAITING_PAYMENT' && !!detail.value.expires_at && now.value >= Date.parse(detail.value.expires_at))
const unknown = computed(() => uncertain.value || detail.value?.status === 'PAYMENT_PENDING')
const canPay = computed(() => !!detail.value?.draft_id && !deadlinePassed.value && !cancelUnknown.value && (detail.value.status === 'WAITING_PAYMENT' || unknown.value && !!key()))
function storageName() { return `resolveflow:checkout:${props.account.buyer_id}:${detail.value?.draft_id}` }
function key() { try { return memoryKey || window.sessionStorage.getItem(storageName()) || '' } catch { return memoryKey } }
function saveKey(value: string) { memoryKey = value; try { if (value) window.sessionStorage.setItem(storageName(), value); else window.sessionStorage.removeItem(storageName()) } catch { /* The server still prevents a second unknown attempt. */ } }
function valid(g: number) { return alive && g === generation }
function failure(cause: unknown) { if (cause instanceof ApiError && cause.status === 401) { emit('expired'); return }; error.value = cause instanceof ApiError ? cause.status === 404 ? '订单不存在，或当前账号无权查看。' : cause.message : '连接暂时中断，请重试读取。' }
function navigate(hash: string) { if (writing.value) return; emit('navigate', hash) }
async function readEligibility(line: string, g = generation) {
  try { const value = await coreApi.customerOrderLine(props.account.access_token, line); if (valid(g)) { eligibility.value[line] = value; delete eligibilityErrors.value[line] } }
  catch (cause) { if (valid(g)) { eligibility.value[line] = null; eligibilityErrors.value[line] = true; if (cause instanceof ApiError && cause.status === 401) failure(cause) } }
}
async function readFulfillment(g = generation) {
  if (detail.value?.status !== 'PAID') return
  const f = ++fulfillmentGeneration
  const current = () => valid(g) && f === fulfillmentGeneration
  fulfillmentLoading.value = true; fulfillmentError.value = ''; fulfillment.value = null
  try { const result = await fulfillmentApi.buyer(props.account.access_token, detail.value.purchase_id); if (current()) fulfillment.value = result }
  catch (cause) { if (current()) { fulfillmentError.value = '暂时无法确认物流，请重新读取；未读取成功不表示未发货。'; if (cause instanceof ApiError && cause.status === 401) failure(cause) } }
  finally { if (current()) fulfillmentLoading.value = false }
}
async function readDetail(id: string, g = generation) {
  const result = await shopApi.purchase(props.account.access_token, id)
  if (!valid(g)) return
  detail.value = result
  if (['PAID', 'CANCELLED', 'EXPIRED'].includes(result.status)) { saveKey(''); uncertain.value = false; cancelUnknown.value = false }
  if (result.payment?.status === 'FAILED') { saveKey(''); uncertain.value = false }
  if (result.status === 'PAID') void readFulfillment(g)
  if (result.status === 'PAID') for (let i = 0; i < result.lines.length && valid(g); i += 4)
    await Promise.all(result.lines.slice(i, i + 4).filter(l => l.line_id).map(l => readEligibility(l.line_id!, g)))
}
async function load(cursor?: string) {
  const g = generation
  const result = await shopApi.purchases(props.account.access_token, { ...(store.value ? { store_id: store.value } : {}), ...(status.value ? { status: status.value } : {}), ...(cursor ? { cursor } : {}) })
  if (valid(g)) { items.value = cursor ? [...items.value, ...result.items] : result.items; next.value = result.next_cursor }
}
async function route() {
  if (writing.value) return
  const g = ++generation; detail.value = null; memoryKey = ''; items.value = []; next.value = null
  ++fulfillmentGeneration; fulfillment.value = null; fulfillmentError.value = ''; fulfillmentLoading.value = false
  eligibility.value = {}; eligibilityErrors.value = {}; uncertain.value = false; cancelUnknown.value = false; cancelOpen.value = false; error.value = ''; notice.value = ''; loading.value = true
  try {
    const hash = window.location.hash
    if (hash.startsWith('#/shop/drafts/')) { mode.value = 'payment'; await readDetail(`draft:${decodeURIComponent(hash.slice('#/shop/drafts/'.length))}`, g) }
    else if (hash.startsWith('#/shop/orders/')) { mode.value = 'detail'; await readDetail(decodeURIComponent(hash.slice('#/shop/orders/'.length)), g) }
    else { mode.value = 'list'; const params = new URLSearchParams(hash.split('?')[1] ?? ''); store.value = params.get('store_id') ?? ''; status.value = (params.get('status') ?? '') as PurchaseStatus
      const [allStores] = await Promise.all([shopApi.stores(), load()]); if (valid(g)) stores.value = allStores
    }
  } catch (cause) { if (valid(g)) failure(cause) } finally { if (valid(g)) loading.value = false }
}
function filter() { const params = new URLSearchParams({ ...(store.value ? { store_id: store.value } : {}), ...(status.value ? { status: status.value } : {}) }); navigate(`#/shop/orders${params.size ? `?${params}` : ''}`) }
async function more() { if (!next.value || loading.value) return; const g = generation; loading.value = true; try { await load(next.value) } catch (cause) { if (valid(g)) failure(cause) } finally { if (valid(g)) loading.value = false } }
async function refresh() {
  if (loading.value || writing.value) return
  const g = generation; loading.value = true; error.value = ''
  try { if (!detail.value) await load(); else {
    if (detail.value.draft_id) { const lookup = await shopApi.payment(props.account.access_token, detail.value.draft_id); if (!valid(g)) return; uncertain.value = lookup.payment?.status === 'UNKNOWN'; if (lookup.payment?.status === 'FAILED') saveKey('') }
    await readDetail(detail.value.purchase_id, g); if (valid(g)) cancelUnknown.value = false
  } } catch (cause) { if (valid(g)) failure(cause) } finally { if (valid(g)) loading.value = false }
}
async function pay() {
  if (!canPay.value || writing.value || loading.value || !detail.value?.draft_id) return
  if (!key()) saveKey(crypto.randomUUID())
  const g = generation, id = detail.value.draft_id, original = key(); writing.value = true; error.value = ''; notice.value = ''
  try { const payment = await shopApi.pay(props.account.access_token, id, original); if (!valid(g)) return
    uncertain.value = payment.status === 'UNKNOWN'
    await readDetail(`draft:${id}`, g)
    if (valid(g) && payment.status === 'FAILED') notice.value = '本次模拟付款未成功，可重新确认付款。'
  } catch (cause) { if (!valid(g)) return
    if (!(cause instanceof ApiError) || cause.status >= 500) { uncertain.value = true; error.value = '付款结果尚未确认，请查询原尝试；不要重复创建订单。' }
    else { failure(cause); if (cause.status === 409) await readDetail(`draft:${id}`, g).catch(() => {}) }
  } finally { if (valid(g)) writing.value = false }
}
async function cancel() {
  if (!detail.value?.draft_id || writing.value || loading.value || unknown.value || deadlinePassed.value) return
  const g = generation, id = detail.value.draft_id; writing.value = true; error.value = ''
  try { await shopApi.cancel(props.account.access_token, id); if (valid(g)) { cancelOpen.value = false; await readDetail(`draft:${id}`, g) } }
  catch (cause) { if (valid(g)) { cancelOpen.value = false; if (!(cause instanceof ApiError) || cause.status >= 500) { cancelUnknown.value = true; error.value = '取消结果尚未确认，请刷新订单状态。' } else failure(cause) } }
  finally { if (valid(g)) writing.value = false }
}
onMounted(() => { void route(); timer = setInterval(() => { now.value = Date.now() }, 1000); window.addEventListener('hashchange', route); window.addEventListener('popstate', route) })
onBeforeUnmount(() => { alive = false; ++generation; if (timer) clearInterval(timer); window.removeEventListener('hashchange', route); window.removeEventListener('popstate', route) })
</script>

<template>
  <div class="buyer-orders" :class="{ 'payment-page': mode === 'payment' }">
    <aside v-if="mode !== 'payment'" class="purchase-sidebar"><button class="current" @click="navigate('#/shop/orders')">▤ 我的订单</button><button @click="navigate('#/customer/applications')">◎ 我的售后</button></aside>
    <main class="purchase-main">
      <header class="purchase-heading"><h1>{{ mode === 'list' ? '我的订单' : mode === 'payment' ? '模拟付款' : '订单详情' }}</h1><button class="shop-secondary" :disabled="writing || loading" @click="refresh">刷新状态</button></header>
      <p v-if="error" class="shop-error" role="alert">{{ error }}</p><p v-if="notice" class="purchase-notice" role="status">{{ notice }}</p>
      <div v-if="mode === 'list'" class="purchase-filters"><div><button v-for="s in [{ id: '', name: '全部' }, { id: 'WAITING_PAYMENT', name: '待付款' }, { id: 'PAYMENT_PENDING', name: '结果待确认' }, { id: 'PAID', name: '已付款' }, { id: 'CANCELLED', name: '已取消' }, { id: 'EXPIRED', name: '已到期' }]" :key="s.id" :class="{ current: status === s.id }" :disabled="loading" @click="status = s.id as PurchaseStatus | ''; filter()">{{ s.name }}</button></div><select v-model="store" aria-label="按店铺筛选" :disabled="loading" @change="filter"><option value="">全部店铺</option><option v-for="s in stores" :key="s.store_id" :value="s.store_id">{{ s.name }}</option></select></div>
      <p v-if="loading && !detail && !items.length" class="shop-empty" role="status">正在读取订单…</p><p v-else-if="mode === 'list' && !items.length && !error" class="shop-empty">当前筛选下没有订单。</p>
      <template v-if="mode === 'list'">
        <article v-for="item in items" :key="item.purchase_id" class="purchase-card"><header><a :href="`#/shop/stores/${item.store_id}`" @click.prevent="navigate(`#/shop/stores/${item.store_id}`)">{{ item.store_name }} →</a><span class="purchase-status" :class="item.status.toLowerCase()">{{ labels[item.status] }}</span></header><div class="purchase-card-body"><div class="purchase-goods"><div v-for="line in item.lines" :key="line.sku" class="purchase-item"><ProductArt v-if="line.asset_key" :asset="line.asset_key" :name="line.product_name || line.sku" /><span v-else class="purchase-no-art" aria-label="商品图片未提供">▢</span><div><h2>{{ line.product_name || line.sku }}</h2><p>{{ line.variant }} · 数量 × {{ line.quantity }}</p><strong>{{ money(line.line_amount) }}</strong></div></div></div><div class="purchase-card-total"><span>{{ item.status === 'PAID' ? '原实付' : '订单合计' }}</span><strong>{{ money(item.total_amount) }}</strong><button class="shop-secondary" @click="navigate(`#/shop/orders/${encodeURIComponent(item.purchase_id)}`)">{{ item.status === 'WAITING_PAYMENT' ? '查看并付款' : '查看订单' }}</button></div></div></article>
        <button v-if="next" class="shop-secondary shop-load" :disabled="loading" @click="more">加载更多订单</button>
      </template>
      <template v-else-if="detail">
        <button class="shop-back" :disabled="writing" @click="navigate('#/shop/orders')">← 返回我的订单</button>
        <section class="purchase-summary" :class="detail.status.toLowerCase()"><span class="purchase-symbol">{{ detail.status === 'PAID' ? '✓' : '◷' }}</span><div><h2>{{ unknown ? '付款结果待确认' : deadlinePassed ? '付款期限已过' : labels[detail.status] }}</h2><p>{{ detail.store_name }}</p></div><div class="purchase-sum"><span>{{ detail.status === 'PAID' ? '原实付' : '订单合计' }}</span><strong>{{ money(detail.total_amount) }}</strong></div></section>
        <section class="purchase-detail-panel"><h2>订单商品</h2><div v-for="line in detail.lines" :key="line.sku" class="purchase-detail-line"><ProductArt v-if="line.asset_key" :asset="line.asset_key" :name="line.product_name || line.sku" /><span v-else class="purchase-no-art" aria-label="商品图片未提供">▢</span><div class="purchase-line-copy"><h2>{{ line.product_name || line.sku }}</h2><p>{{ line.variant }} · 数量 × {{ line.quantity }}</p><p v-if="line.unit_amount !== null">单价 {{ money(line.unit_amount) }}</p></div><strong>{{ money(line.line_amount) }}</strong></div></section>
        <section v-if="detail.status === 'WAITING_PAYMENT' || unknown" class="purchase-payment-panel"><h2>本地模拟付款</h2><p v-if="detail.expires_at && !unknown">付款截止 {{ time(detail.expires_at) }}</p><p v-if="unknown">只查询原付款尝试，确认后再进行下一步。</p><div class="purchase-actions"><button v-if="canPay" class="shop-primary" data-test="pay" :disabled="writing || loading" @click="pay">{{ writing ? '正在确认…' : unknown || key() ? '重试原付款请求' : '确认模拟付款' }}</button><button v-if="unknown" class="shop-secondary" :disabled="writing || loading" @click="refresh">查询原付款结果</button><button v-if="detail.status === 'WAITING_PAYMENT' && !unknown && !deadlinePassed && !cancelUnknown" class="shop-secondary" :disabled="writing || loading" @click="cancelOpen = true">取消订单</button></div></section>
        <FulfillmentPanel v-if="detail.status === 'PAID'" :fact="fulfillment" :lines="detail.lines" :loading="fulfillmentLoading" :error="fulfillmentError" @retry="readFulfillment()" />
        <section v-if="detail.status === 'PAID'" class="purchase-detail-panel"><h2>付款与售后</h2><p v-if="detail.refund_status && detail.refund_status !== 'NONE'">{{ refundLabels[detail.refund_status] }}</p><p v-if="detail.paid_at">{{ detail.draft_id ? '模拟付款完成于' : '原订单支付于' }} {{ time(detail.paid_at) }}</p><div v-for="line in detail.lines.filter(l => l.line_id)" :key="line.line_id!" class="purchase-aftercare"><strong>{{ line.product_name || line.sku }}</strong><template v-if="eligibility[line.line_id!]"> <p>{{ eligibility[line.line_id!]!.blocked_reason || '可提交整行全额退款申请，需商家审核。' }}</p><button v-if="eligibility[line.line_id!]!.application" class="shop-secondary" @click="navigate(`#/customer/applications/${eligibility[line.line_id!]!.application!.case_id}`)">查看售后申请</button><button v-else-if="eligibility[line.line_id!]!.can_apply" class="shop-secondary" @click="navigate(`#/customer/apply/${encodeURIComponent(line.line_id!)}`)">申请售后</button></template><button v-else class="shop-secondary" :disabled="loading || writing" @click="readEligibility(line.line_id!)">{{ eligibilityErrors[line.line_id!] ? '重新读取售后资格' : '读取售后资格' }}</button></div></section>
        <section class="purchase-detail-panel purchase-times"><p>提交于 {{ time(detail.created_at) }}</p><p v-if="['CANCELLED','EXPIRED'].includes(detail.status)">本订单没有付款，可回到商城重新购买。</p><details><summary>查看交易编号</summary><p>订单 {{ detail.order_id || detail.draft_id }}</p><p v-if="detail.payment">付款尝试 {{ detail.payment.attempt_id }} · {{ detail.payment.status }}</p></details></section>
      </template>
    </main>
    <ReviewDialog v-if="cancelOpen" title="取消待付款订单" workspace="我的订单" :busy="writing" @close="cancelOpen = false"><p>确认取消这份待付款订单？取消后需重新购买。</p><div class="purchase-actions"><button class="shop-secondary" :disabled="writing" @click="cancelOpen = false">返回</button><button class="shop-primary" :disabled="writing" @click="cancel">确认取消</button></div></ReviewDialog>
  </div>
</template>
