<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ApiError, type LoginResponse } from '../client'
import { shopApi, type CartGroup, type CartItem, type CartQuote } from '../shop-client'
import { readCartPending, saveCartPending, clearCartPending, type CartPending } from '../cart-pending'
import { formatMinorUnits } from '../money'
import ProductArt from './ProductArt.vue'

const props = defineProps<{ account: LoginResponse }>()
const emit = defineEmits<{ expired: []; navigate: [hash: string]; busy: [blocked: boolean] }>()
const stores = ref<CartGroup[]>([]), selected = ref<string[]>([]), loading = ref(false), writing = ref(false)
const error = ref(''), quote = ref<CartQuote | null>(null), pending = ref<CartPending | null>(null)
let alive = true, generation = 0, initialized = false
const blocked = computed(() => writing.value || !!pending.value)
const money = (v: number) => `¥ ${formatMinorUnits(v).replace(' CNY', '')}`
const reasons = { DELISTED: '商品已下架', STORE_DISABLED: '店铺暂不可购买', QUANTITY_EXCEEDED: '数量超过当前购买上限', AVAILABLE: '' }
const chosen = (s: CartGroup) => s.items.filter(i => selected.value.includes(i.sku_id) && i.availability === 'AVAILABLE')
const total = (s: CartGroup) => chosen(s).reduce((sum, i) => sum + i.total_amount, 0)
function fail(cause: unknown) {
  if (cause instanceof ApiError && cause.status === 401) { emit('expired'); return }
  error.value = cause instanceof ApiError ? cause.message : cause instanceof Error && cause.message.startsWith('保存的') ? cause.message : '连接暂时中断，请重试。'
}
function busy() { emit('busy', blocked.value) }
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
  const g = generation; writing.value = true; busy(); error.value = ''
  try {
    const q = await shopApi.cartQuote(props.account.access_token, s.store_id, s.revision, chosen(s).map(i => i.sku_id))
    if (alive && g === generation) quote.value = q
  } catch (e) { if (alive && g === generation) fail(e) }
  finally { if (alive) { writing.value = false; busy() } }
}
async function submit() {
  if (!quote.value || blocked.value) return
  const q = quote.value
  const p: CartPending = { kind: 'draft', key: crypto.randomUUID(), store: q.store_id, quote: q,
    request: { expected_revision: q.revision, lines: q.lines.map(l => ({ sku_id: l.sku_id, quantity: l.quantity, expected_sku_version: l.sku_version })) } }
  try { saveCartPending(props.account.buyer_id!, p); pending.value = p; await retry() } catch (e) { fail(e) }
}
onMounted(() => {
  try { pending.value = readCartPending(props.account.buyer_id!); if (pending.value?.kind === 'draft') quote.value = pending.value.quote; busy() } catch (e) { fail(e) }
  void load()
})
onBeforeUnmount(() => { alive = false; ++generation; emit('busy', false) })
</script>

<template>
  <main class="shop-content cart-workspace">
    <p v-if="error" class="shop-error" role="alert">{{ error }}</p>
    <div v-if="pending" class="cart-recovery" role="status"><p>上次{{ pending.kind === 'draft' ? '订单提交' : '购物车操作' }}结果待确认。</p><button class="shop-primary" :disabled="writing" @click="retry">{{ writing ? '正在确认…' : '用原请求确认结果' }}</button></div>
    <template v-if="quote">
      <button class="shop-back" :disabled="blocked" @click="quote = null">← 返回购物车</button><h1>确认订单</h1>
      <section class="checkout-address"><h2>演示收货信息</h2><p>演示买家 · 杭州市演示路 100 号</p></section>
      <section class="checkout-panel"><h2>{{ quote.store_name }}</h2>
        <div v-for="line in quote.lines" :key="line.sku_id" class="checkout-line"><ProductArt :asset="line.asset_key" :name="line.product_name" :variant="line.variant" /><div><h2>{{ line.product_name }}</h2><p>{{ line.variant }}</p></div><div><p>单价</p><strong>{{ money(line.unit_amount) }}</strong></div><div><p>数量</p><strong>{{ line.quantity }}</strong></div><div><p>小计</p><strong>{{ money(line.line_amount) }}</strong></div></div>
        <div class="checkout-total"><span>应付合计</span><strong>{{ money(quote.total_amount) }}</strong></div>
        <button v-if="!pending" class="shop-primary cart-submit" :disabled="writing" @click="submit">提交订单</button>
      </section>
    </template>
    <template v-else>
      <div class="cart-heading"><div><h1>购物车</h1><p>按店铺分别结算</p></div><button class="shop-secondary" :disabled="blocked || loading" @click="refresh">刷新购物车</button></div>
      <p v-if="loading" class="shop-empty" role="status">正在读取购物车…</p>
      <div v-else-if="!stores.some(s => s.items.length) && !error" class="shop-empty"><p>购物车还没有商品。</p><button class="shop-primary" :disabled="blocked" @click="emit('navigate', '#/shop')">去逛商城</button></div>
      <section v-for="s in stores.filter(s => s.items.length)" :key="s.store_id" class="cart-store">
        <header><span class="store-symbol">{{ s.store_name.slice(0,1) }}</span><h2>{{ s.store_name }}</h2></header>
        <div class="cart-columns" aria-hidden="true"><span></span><span>商品</span><span>单价</span><span>数量</span><span>小计</span><span>操作</span></div>
        <div v-for="i in s.items" :key="i.sku_id" class="cart-row" :data-sku="i.sku_id">
          <input v-model="selected" type="checkbox" :value="i.sku_id" :aria-label="`选择${i.product_name}`" :disabled="blocked || loading || i.availability !== 'AVAILABLE'" />
          <div class="cart-product"><ProductArt :asset="i.asset_key" :name="i.product_name" :variant="i.variant" /><div><h2>{{ i.product_name }}</h2><p>{{ i.variant }}</p><p v-if="i.availability !== 'AVAILABLE'" class="cart-unavailable">{{ reasons[i.availability] }}</p><p v-else-if="i.price_changed" class="cart-unavailable">价格已更新，请结算时确认新报价。</p></div></div>
          <strong>{{ money(i.unit_amount) }}</strong>
          <div class="cart-quantity"><button :aria-label="`减少${i.product_name}数量`" :disabled="blocked || loading || i.quantity <= 1 || i.availability !== 'AVAILABLE'" @click="change(s, i, i.quantity - 1)">−</button><span>{{ i.quantity }}</span><button :aria-label="`增加${i.product_name}数量`" :disabled="blocked || loading || i.quantity >= i.max_quantity || i.availability !== 'AVAILABLE'" @click="change(s, i, i.quantity + 1)">＋</button></div>
          <strong>{{ money(i.total_amount) }}</strong><button class="cart-remove" :aria-label="`移除${i.product_name}`" :disabled="blocked || loading" @click="change(s, i, 0)">移除</button>
        </div>
        <footer><span>已选 {{ chosen(s).length }} 种商品</span><span>店铺合计 <strong>{{ money(total(s)) }}</strong></span><button class="shop-primary cart-checkout" :disabled="blocked || loading || !chosen(s).length" @click="checkout(s)">结算{{ s.store_name }}</button></footer>
      </section>
    </template>
  </main>
</template>
