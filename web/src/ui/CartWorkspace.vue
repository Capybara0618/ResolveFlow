<script setup lang="ts">
import { ref, computed, nextTick, watch, onMounted, onBeforeUnmount } from 'vue'
import { ApiError, type LoginResponse } from '../client'
import { shopApi, type CartGroup, type CartItem, type CartQuote } from '../shop-client'
import { readCartPending, saveCartPending, clearCartPending, type CartPending } from '../cart-pending'
import { formatMinorUnits } from '../money'
import ProductArt from './ProductArt.vue'
import AddressPicker from './AddressPicker.vue'
import type { ShippingSelection } from '../account-client'
import Icon from './ReviewIcon.vue'
import OrderSummary from './OrderSummary.vue'
import ReviewDialog from './ReviewDialog.vue'
import './purchase-layout.css'

const props = defineProps<{ account: LoginResponse; initialSelection?: string[]; initialStore?: string }>()
const emit = defineEmits<{ expired: []; navigate: [hash: string]; busy: [blocked: boolean]; selection: [ids: string[]]; ready: []; store: [id: string] }>()
const stores = ref<CartGroup[]>([]), selected = ref<string[]>(props.initialSelection ?? []), loading = ref(false), writing = ref(false)
const error = ref(''), quote = ref<CartQuote | null>(null), pending = ref<CartPending | null>(null)
const shipping = ref<ShippingSelection | null>(null), addressBusy = ref(false)
let alive = true, generation = 0, initialized = props.initialSelection !== undefined
const slowLoading = ref(false)
let loadingTimer: ReturnType<typeof setTimeout> | undefined, positionFrame: number | undefined, listPosition = 0
watch(loading, value => { clearTimeout(loadingTimer); slowLoading.value = false; if (value) loadingTimer = setTimeout(() => { slowLoading.value = true }, 150) })
watch(selected, ids => emit('selection', [...ids]))
async function position(top: number) { await nextTick(); cancelAnimationFrame(positionFrame ?? 0); positionFrame = requestAnimationFrame(() => { if (alive) window.scrollTo({top, behavior:'auto'}) }) }
function backWithin() { if (!quote.value || blocked.value) return false; quote.value = null; void position(listPosition); return true }
function openProduct(id: string) { if (!blocked.value && !loading.value) emit('navigate', `#/shop/products/${encodeURIComponent(id)}`) }
const blocked = computed(() => writing.value || !!pending.value || addressBusy.value)
const money = (v: number) => `¥ ${formatMinorUnits(v).replace(' CNY', '')}`
const reasons = { DELISTED: '商品已下架', STORE_DISABLED: '店铺暂不可购买', QUANTITY_EXCEEDED: '数量超过当前购买上限', AVAILABLE: '' }
const checkoutStoreId = ref(props.initialStore ?? '')
const removeTarget = ref<{ store: CartGroup; item: CartItem } | null>(null)
const cartStores = computed(() => stores.value.filter(s => s.items.length))
const checkoutStore = computed(() => cartStores.value.find(s => s.store_id === checkoutStoreId.value) ?? cartStores.value[0])
watch(checkoutStore, s => { if (s) emit('store', s.store_id) })
async function remove() { const target = removeTarget.value; if (!target || blocked.value) return; await change(target.store, target.item, 0); if (alive) removeTarget.value = null }
const chosen = (s: CartGroup) => s.items.filter(i => selected.value.includes(i.sku_id) && i.availability === 'AVAILABLE')
const total = (s: CartGroup) => chosen(s).reduce((sum, i) => sum + i.total_amount, 0)
function fail(cause: unknown) {
  if (cause instanceof ApiError && cause.status === 401) { emit('expired'); return }
  error.value = cause instanceof ApiError ? cause.message : cause instanceof Error && cause.message.startsWith('保存的') ? cause.message : '连接暂时中断，请重试。'
}
function busy() { emit('busy', blocked.value) }
watch(addressBusy, busy)
async function load() {
  const g = ++generation; loading.value = true
  try {
    const result = await shopApi.cart(props.account.access_token)
    if (!alive || g !== generation) return
    stores.value = result.stores
    const available = result.stores.flatMap(s => s.items).filter(i => i.availability === 'AVAILABLE').map(i => i.sku_id)
    selected.value = initialized ? selected.value.filter(id => available.includes(id)) : available
    initialized = true
  } catch (e) { if (alive && g === generation) fail(e) }
  finally { if (alive && g === generation) loading.value = false }
}
async function refresh() { if (blocked.value) return; error.value = ''; quote.value = null; await load() }
async function change(s: CartGroup, i: CartItem, qty: number) {
  if (blocked.value || loading.value) return
  const p: CartPending = { kind: 'mutation', store: s.store_id, key: crypto.randomUUID(), request: { sku_id: i.sku_id, quantity: qty, expected_revision: s.revision, expected_sku_version: qty === 0 ? null : i.sku_version } }
  try { saveCartPending(props.account.buyer_id!, p); pending.value = p; await retry() } catch (e) { fail(e) }
}
async function retry() {
  const p = pending.value
  if (!p || writing.value) return
  const g = generation; writing.value = true; busy(); error.value = ''
  try {
    if (p.kind === 'mutation') {
      await shopApi.cartWrite(props.account.access_token, p.store, p.request, p.key)
      clearCartPending(props.account.buyer_id!, p.key)
      if (!alive || g !== generation) return
      pending.value = null; await load()
    } else {
      const d = await shopApi.cartDraft(props.account.access_token, p.store, p.request, p.key)
      clearCartPending(props.account.buyer_id!, p.key)
      if (!alive || g !== generation) return
      pending.value = null; writing.value = false; busy(); emit('navigate', `#/shop/drafts/${encodeURIComponent(d.draft_id!)}`)
    }
  } catch (e) {
    if (!alive || g !== generation) return
    if (e instanceof ApiError && e.status < 500 && e.status !== 401) {
      clearCartPending(props.account.buyer_id!, p.key); pending.value = null; quote.value = null; fail(e)
      await load()
    } else if (e instanceof ApiError && e.status === 401) fail(e)
    else error.value = '本次操作结果尚未确认，请使用原请求确认结果。'
  } finally { if (alive) { writing.value = false; busy() } }
}
async function checkout(s: CartGroup) {
  if (blocked.value || loading.value || !chosen(s).length) return
  listPosition = window.scrollY
  const g = generation; writing.value = true; busy(); error.value = ''
  try {
    const q = await shopApi.cartQuote(props.account.access_token, s.store_id, s.revision, chosen(s).map(i => i.sku_id))
    if (alive && g === generation) { quote.value = q; void position(0) }
  } catch (e) { if (alive && g === generation) fail(e) }
  finally { if (alive) { writing.value = false; busy() } }
}
async function submit() {
  if (!quote.value || blocked.value || addressBusy.value || !shipping.value) return
  const q = quote.value
  const p: CartPending = { kind: 'draft', key: crypto.randomUUID(), store: q.store_id, quote: q,
    request: { expected_revision: q.revision, lines: q.lines.map(l => ({ sku_id: l.sku_id, quantity: l.quantity, expected_sku_version: l.sku_version })), shipping: shipping.value } }
  try { saveCartPending(props.account.buyer_id!, p); pending.value = p; await retry() } catch (e) { fail(e) }
}
onMounted(() => {
  try { pending.value = readCartPending(props.account.buyer_id!); if (pending.value?.kind === 'draft') quote.value = pending.value.quote; busy() } catch (e) { fail(e) }
  void load().then(() => { if (alive) emit('ready') })
})
onBeforeUnmount(() => { alive = false; ++generation; clearTimeout(loadingTimer); cancelAnimationFrame(positionFrame ?? 0); emit('busy', false) })
defineExpose({ navigationBlocked: blocked, backWithin, viewScroll: () => quote.value ? listPosition : window.scrollY })
</script>

<template>
  <main class="shop-content cart-workspace" :aria-busy="loading || writing">
    <p v-if="error" class="shop-error" role="alert">{{ error }}</p>
    <div v-if="pending" class="cart-recovery" role="status"><p>上次{{ pending.kind === 'draft' ? '订单提交' : '购物车操作' }}结果待确认。</p><button class="shop-primary" :disabled="writing" @click="retry">{{ writing ? '正在确认…' : '用原请求确认结果' }}</button></div>
    <template v-if="quote">
      <header class="checkout-heading" data-page-reveal><h1>确认订单</h1><button class="shop-text" :disabled="blocked" @click="backWithin">返回购物车</button></header>
      <div class="purchase-layout"><div class="purchase-main-column">
        <AddressPicker v-model="shipping" :account="account" :disabled="blocked" @working="addressBusy = $event" @expired="emit('expired')" />
        <section class="checkout-panel"><h2>{{ quote.store_name }}</h2>
          <div v-for="line in quote.lines" :key="line.sku_id" class="checkout-line"><ProductArt :asset="line.asset_key" :name="line.product_name" :variant="line.variant" /><div><h2>{{ line.product_name }}</h2><p>{{ line.variant }} · 数量 {{ line.quantity }}</p><p>单价 {{ money(line.unit_amount) }}</p></div><strong>{{ money(line.line_amount) }}</strong></div>
        </section>
      </div><OrderSummary :amount="quote.total_amount" :quantity="quote.lines.reduce((n,l) => n + l.quantity, 0)" :show-action="!pending" action-class="cart-submit" :disabled="blocked || !shipping" :busy="writing" @submit="submit" /></div>
    </template>
    <template v-else>
      <div class="cart-heading" data-page-reveal><h1>购物车</h1><button class="shop-text" :disabled="blocked || loading" @click="refresh">刷新购物车</button></div>
      <div v-if="loading && slowLoading && !stores.length" class="cart-skeleton" role="status" aria-label="正在读取购物车"><div v-for="i in 2" :key="i" aria-hidden="true"><i /><span /></div></div>
      <div v-else-if="!loading && !stores.some(s => s.items.length) && !error" class="shop-empty"><p>购物车还没有商品。</p><button class="shop-primary" :disabled="blocked" @click="emit('navigate', '#/shop')">去逛商城</button></div>
      <div v-if="cartStores.length" class="purchase-layout"><div class="cart-groups"><section v-for="s in cartStores" :key="s.store_id" class="cart-store" data-page-reveal>
        <header><Icon name="store" :size="20" /><h2>{{ s.store_name }}</h2></header>
        <div class="cart-columns" aria-hidden="true"><span></span><span>商品</span><span>数量</span><span>小计</span><span>操作</span></div>
        <div v-for="i in s.items" :key="i.sku_id" class="cart-row" :data-sku="i.sku_id">
          <input v-model="selected" type="checkbox" :value="i.sku_id" :aria-label="`选择${i.product_name}`" :disabled="blocked || loading || i.availability !== 'AVAILABLE'" />
          <div class="cart-product"><a :href="`#/shop/products/${i.product_id}`" :aria-label="`查看${i.product_name}`" :aria-disabled="blocked || loading" @click.prevent="openProduct(i.product_id)"><ProductArt :asset="i.asset_key" :name="i.product_name" :variant="i.variant" /></a><div><h2><a :href="`#/shop/products/${i.product_id}`" :aria-disabled="blocked || loading" @click.prevent="openProduct(i.product_id)">{{ i.product_name }}</a></h2><p>{{ i.variant }}<span class="cart-inline-unit">单价 {{ money(i.unit_amount) }}</span></p><p v-if="i.availability !== 'AVAILABLE'" class="cart-unavailable">{{ reasons[i.availability] }}</p><p v-else-if="i.price_changed" class="cart-unavailable">价格已更新，请结算时确认新报价。</p></div></div>
          <div class="cart-quantity"><button :aria-label="`减少${i.product_name}数量`" :disabled="blocked || loading || i.quantity <= 1 || i.availability !== 'AVAILABLE'" @click="change(s, i, i.quantity - 1)">−</button><span>{{ i.quantity }}</span><button :aria-label="`增加${i.product_name}数量`" :disabled="blocked || loading || i.quantity >= i.max_quantity || i.availability !== 'AVAILABLE'" @click="change(s, i, i.quantity + 1)">＋</button></div>
          <strong class="cart-line-total"><span class="cart-mobile-label">小计</span>{{ money(i.total_amount) }}</strong><button class="cart-remove" :aria-label="`移除${i.product_name}`" :disabled="blocked || loading" @click="removeTarget = { store: s, item: i }">移除</button>
        </div>
      </section></div><OrderSummary v-if="checkoutStore" class="cart-settlement" title="结算" :amount="total(checkoutStore)" :quantity="chosen(checkoutStore).reduce((n,i) => n + i.quantity, 0)" action="确认结算" action-class="cart-checkout" :disabled="blocked || loading || !chosen(checkoutStore).length" :busy="writing" @submit="checkout(checkoutStore)">
        <div class="cart-store-choices" aria-label="结算店铺"><button v-for="s in cartStores" :key="s.store_id" type="button" :data-checkout-store="s.store_id" :aria-pressed="s.store_id === checkoutStore.store_id" :disabled="blocked || loading" @click="checkoutStoreId = s.store_id"><Icon name="store" :size="16" />{{ s.store_name }}</button></div>
      </OrderSummary></div>
    </template>
    <ReviewDialog :open="!!removeTarget" title="移除这件商品？" compact :busy="writing" @close="removeTarget = null"><p>{{ removeTarget?.item.product_name }}将从购物车移除。</p><template #footer><button class="shop-secondary" :disabled="writing" @click="removeTarget = null">保留商品</button><button class="dialog-danger" :disabled="writing" @click="remove">移除商品</button></template></ReviewDialog>
  </main>
</template>
