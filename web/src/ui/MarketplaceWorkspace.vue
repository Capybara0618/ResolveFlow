<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { ApiError, type LoginResponse } from '../client'
import { shopApi, type ShopProduct, type ShopStore, type ShopQuote, type ShopDraft, type ShopDraftRequest } from '../shop-client'
import { formatMinorUnits } from '../money'
import ProductArt from './ProductArt.vue'
import Icon from './ReviewIcon.vue'
import CustomerWorkspace from './CustomerWorkspace.vue'
import SupportWorkspace from './SupportWorkspace.vue'
import BuyerOrders from './BuyerOrders.vue'
import ProductReviews from './ProductReviews.vue'
import CartWorkspace from './CartWorkspace.vue'
import { readCartPending, saveCartPending, clearCartPending, type CartPending } from '../cart-pending'
import './marketplace.css'

const props = defineProps<{ account: LoginResponse | null }>()
const emit = defineEmits<{ expired: []; login: []; logout: [] }>()
type Screen = 'home' | 'search' | 'store' | 'product' | 'checkout' | 'orders' | 'customer' | 'cart' | 'support'
const screen = ref<Screen>('home'), query = ref(''), category = ref(''), stores = ref<ShopStore[]>([])
const workspaceCatalog = ref<HTMLElement>()
const ordersRoute = ref(''), cartBusy = ref(false), added = ref(false)
let pendingAdd: Extract<CartPending, { kind: 'mutation' }> | null = null
const products = ref<ShopProduct[]>([]), store = ref<ShopStore | null>(null), product = ref<ShopProduct | null>(null)
const sku = ref(''), quantity = ref(1), quote = ref<ShopQuote | null>(null), draft = ref<ShopDraft | null>(null)
const loading = ref(false), writing = ref(false), uncertain = ref(false), error = ref(''), next = ref<string | null>(null)
let generation = 0, quoteGeneration = 0, alive = true, pending: { key: string; request: ShopDraftRequest } | null = null
const selectedSku = computed(() => product.value?.skus.find(s => s.sku_id === sku.value))
const money = (amount: number) => `¥ ${formatMinorUnits(amount).replace(' CNY', '')}`
const catalogMoney = (amount: number) => `¥${formatMinorUnits(amount).replace(' CNY', '').replace(/\.00$/, '')}`
const listingScreen = computed(() => ['home', 'search', 'store'].includes(screen.value))
const featuredOrder = ['P-1001', 'P-2001', 'P-3001', 'P-1002', 'P-1004', 'P-2002', 'P-3002', 'P-2003']
const displayedProducts = computed(() => screen.value !== 'home' ? products.value : [...products.value].sort((a, b) => {
  const rank = (id: string) => { const index = featuredOrder.indexOf(id); return index < 0 ? featuredOrder.length : index }
  return rank(a.product_id) - rank(b.product_id)
}))
function failure(cause: unknown) {
  if (cause instanceof ApiError && cause.status === 401) { emit('expired'); return }
  error.value = cause instanceof ApiError && cause.status === 404 ? '商品已下架，或当前账号无法查看这份订单。'
    : cause instanceof ApiError && cause.status === 403 ? '请使用平台买家账号购买商品。'
    : cause instanceof ApiError ? cause.message : '连接暂时中断，请重试。'
}
function go(hash: string) {
  if (writing.value || uncertain.value || cartBusy.value) { error.value = '请先确认本次订单提交结果。'; return }
  window.history.pushState(null, '', hash); void route()
}
function search() { go(`${store.value ? `#/shop/stores/${encodeURIComponent(store.value.store_id)}` : '#/shop/search'}?${new URLSearchParams({ ...(query.value.trim() ? { query: query.value.trim() } : {}), ...(category.value ? { category: category.value } : {}) })}`) }
function changeStore(event: Event) {
  const id = (event.target as HTMLSelectElement).value
  const params = new URLSearchParams({ ...(query.value.trim() ? { query: query.value.trim() } : {}), ...(category.value ? { category: category.value } : {}) }).toString()
  go(`${id ? `#/shop/stores/${encodeURIComponent(id)}` : params ? '#/shop/search' : '#/shop'}${params ? `?${params}` : ''}`)
}
async function route() {
  if (writing.value || uncertain.value || cartBusy.value) return
  const g = ++generation; ++quoteGeneration
  error.value = ''; added.value = false; quote.value = null; draft.value = null; store.value = null; product.value = null; pending = null
  products.value = []; next.value = null
  let hash = window.location.hash
  if (hash === '#/shop/support') { screen.value = 'support'; loading.value = false; if (!props.account) emit('login'); return }
  if (hash.startsWith('#/customer/')) { screen.value = 'customer'; loading.value = false; return }
  loading.value = true
  try {
    if (props.account?.buyer_id && readCartPending(props.account.buyer_id) && hash !== '#/shop/cart') {
      hash = '#/shop/cart'; window.history.replaceState(null, '', hash)
    }
    if (hash === '#/shop/cart') {
      screen.value = 'cart'; loading.value = false
      if (!props.account) emit('login')
    } else if (hash.startsWith('#/shop/orders') || /^#\/shop\/drafts\//.test(hash)) {
      screen.value = 'orders'
      ordersRoute.value = hash
      if (!props.account) { emit('login'); return }
      loading.value = false
    } else if (/^#\/shop\/products\//.test(hash)) {
      screen.value = 'product'
      const result = await shopApi.product(decodeURIComponent(hash.slice('#/shop/products/'.length)))
      if (alive && g === generation) { product.value = result; sku.value = result.skus[0].sku_id; quantity.value = 1 }
    } else {
      const isStore = hash.startsWith('#/shop/stores/'), isSearch = hash.startsWith('#/shop/search')
      screen.value = isStore ? 'store' : isSearch ? 'search' : 'home'
      const params = new URLSearchParams(hash.split('?')[1] ?? '')
      query.value = params.get('query') ?? ''; category.value = params.get('category') ?? ''
      const storeId = isStore ? decodeURIComponent(hash.slice('#/shop/stores/'.length).split('?')[0]) : undefined
      const [listing, allStores, ownStore] = await Promise.all([shopApi.products({ ...(query.value ? { query: query.value } : {}), ...(category.value ? { category: category.value } : {}), ...(storeId ? { store_id: storeId } : {}) }), shopApi.stores(), storeId ? shopApi.store(storeId) : Promise.resolve(null)])
      if (alive && g === generation) { products.value = listing.items; next.value = listing.next_after; stores.value = allStores; store.value = ownStore }
    }
  } catch (cause) { if (alive && g === generation) failure(cause) }
  finally { if (alive && g === generation) loading.value = false }
}
async function more() {
  if (!next.value || loading.value) return
  const g = generation; loading.value = true
  try {
    const result = await shopApi.products({ after: next.value, ...(query.value ? { query: query.value } : {}), ...(category.value ? { category: category.value } : {}), ...(store.value ? { store_id: store.value.store_id } : {}) })
    if (alive && g === generation) { products.value.push(...result.items); next.value = result.next_after }
  } catch (cause) { if (alive && g === generation) failure(cause) } finally { if (alive && g === generation) loading.value = false }
}
async function buy() {
  if (!props.account) { emit('login'); return }
  if (!selectedSku.value || writing.value || !Number.isInteger(quantity.value) || quantity.value < 1 || quantity.value > selectedSku.value.max_quantity) { error.value = '请选择有效规格与数量。'; return }
  const g = ++quoteGeneration; loading.value = true; error.value = ''
  const requestSku = sku.value, requestQuantity = quantity.value
  try {
    const result = await shopApi.quote(requestSku, requestQuantity)
    if (alive && g === quoteGeneration && requestSku === sku.value && requestQuantity === quantity.value) { quote.value = result; screen.value = 'checkout'; pending = null }
  } catch (cause) { if (alive && g === quoteGeneration) failure(cause) } finally { if (alive && g === quoteGeneration) loading.value = false }
}
async function submit() {
  if (!props.account || !quote.value || writing.value) return
  if (!pending) pending = { key: crypto.randomUUID(), request: { sku_id: quote.value.sku.sku_id, quantity: quote.value.quantity, expected_sku_version: quote.value.sku.version } }
  const request = pending; writing.value = true; error.value = ''
  try {
    const result = await shopApi.draft(props.account.access_token, request.request, request.key)
    if (!alive) return
    uncertain.value = false; draft.value = result; pending = null
    ordersRoute.value = `#/shop/drafts/${encodeURIComponent(result.draft_id)}`
    window.history.pushState(null, '', ordersRoute.value); screen.value = 'orders'
  } catch (cause) {
    if (!alive) return
    if (!(cause instanceof ApiError) || cause.status >= 500) { uncertain.value = true; error.value = '提交结果尚未确认，请用原请求重试确认。' }
    else { uncertain.value = false; failure(cause)
      if (cause.code === 'PRICE_CHANGED') { quote.value = null; screen.value = 'product'; error.value = '价格或规格已更新，请重新读取商品并确认报价。' }
    }
  } finally { if (alive) writing.value = false }
}
async function addCart() {
  if (!props.account) { emit('login'); return }
  if (!selectedSku.value || !product.value || writing.value || loading.value) return
  if (!Number.isInteger(quantity.value) || quantity.value < 1 || quantity.value > selectedSku.value.max_quantity) { error.value = '请选择有效规格与数量。'; return }
  const token = props.account.access_token, buyer = props.account.buyer_id!, g = generation
  writing.value = true; error.value = ''; added.value = false
  try {
    if (!pendingAdd) {
      if (readCartPending(buyer)) { writing.value = false; go('#/shop/cart'); return }
      const cart = await shopApi.cart(token)
      if (!alive || g !== generation) return
      const group = cart.stores.find(s => s.store_id === product.value!.store_id)
      if (!group) { error.value = '当前账号无法购买这家店铺的商品。'; return }
      const desired = (group.items.find(i => i.sku_id === sku.value)?.quantity ?? 0) + quantity.value
      if (desired > selectedSku.value.max_quantity) { error.value = `购物车中的数量超过上限 ${selectedSku.value.max_quantity}，请先调整购物车。`; return }
      const nextRequest: Extract<CartPending, { kind: 'mutation' }> = { kind: 'mutation', store: group.store_id, key: crypto.randomUUID(), request: { sku_id: sku.value, quantity: desired, expected_revision: group.revision, expected_sku_version: selectedSku.value.version } }
      saveCartPending(buyer, nextRequest); pendingAdd = nextRequest
    }
    const p = pendingAdd
    await shopApi.cartWrite(token, p.store, p.request, p.key)
    clearCartPending(buyer, p.key)
    if (!alive || g !== generation) return
    pendingAdd = null; uncertain.value = false; added.value = true
  } catch (cause) {
    if (!alive || g !== generation) return
    if (pendingAdd && (!(cause instanceof ApiError) || cause.status >= 500)) { uncertain.value = true; error.value = '加入结果尚未确认，请使用原请求确认结果。' }
    else { if (pendingAdd && cause instanceof ApiError && cause.status !== 401) { clearCartPending(buyer, pendingAdd.key); pendingAdd = null; uncertain.value = false } failure(cause) }
  } finally { if (alive) writing.value = false }
}
onMounted(() => { void route(); window.addEventListener('hashchange', route); window.addEventListener('popstate', route) })
onBeforeUnmount(() => { alive = false; ++generation; ++quoteGeneration; window.removeEventListener('hashchange', route); window.removeEventListener('popstate', route) })
</script>

<template>
  <div class="marketplace" :class="{ 'buyer-aftercare': screen === 'customer', 'support-marketplace': screen === 'support', 'display-chain-marketplace': listingScreen || screen === 'support' }">
    <nav class="shop-nav" aria-label="买家导航">
      <a href="#/shop" class="shop-brand" aria-label="ResolveFlow 商城首页" @click.prevent="go('#/shop')"><span class="brand-mark" aria-hidden="true"><i /><i /><i /><i /></span><span>ResolveFlow</span></a>
      <form v-if="listingScreen || screen === 'product'" class="shop-search" role="search" @submit.prevent="search"><input v-model="query" type="search" aria-label="搜索商品" placeholder="搜索商品" maxlength="80" /><button type="submit" aria-label="搜索"><Icon name="search" :size="20" /></button></form>
      <span v-else class="shop-nav-space" />
      <div class="shop-utilities">
        <a href="#/shop/orders" :class="{ current: screen === 'orders' }" @click.prevent="go('#/shop/orders')">我的订单</a>
        <a href="#/shop/support" :class="{ current: screen === 'support' }" @click.prevent="go('#/shop/support')">售后咨询</a>
        <a href="#/shop/cart" :class="{ current: screen === 'cart' }" aria-label="购物车" title="购物车" @click.prevent="go('#/shop/cart')"><Icon name="cart" :size="23" /></a>
        <details v-if="account" class="shop-account"><summary aria-label="账户菜单"><Icon name="user" :size="21" /><span>{{ account.display_name || '我的账户' }}</span></summary><div><a href="#/customer/applications" @click.prevent="go('#/customer/applications')">我的售后</a><button type="button" @click="emit('logout')">退出登录</button></div></details>
        <button v-else class="shop-login" @click="emit('login')">登录</button>
      </div>
    </nav>
    <p v-if="error" class="shop-error shop-global-error" role="alert">{{ error }}</p>
    <SupportWorkspace v-if="screen === 'support' && account" :key="account.access_token" :account="account" @expired="emit('expired')" />
    <CartWorkspace v-else-if="screen === 'cart' && account" :account="account" @expired="emit('expired')" @navigate="go" @busy="cartBusy = $event" />
    <CustomerWorkspace v-else-if="screen === 'customer' && account" :account="account" @expired="emit('expired')" />
    <BuyerOrders v-else-if="screen === 'orders' && account" :key="ordersRoute" :account="account" @expired="emit('expired')" @navigate="go" />
    <main v-else class="shop-content">

      <section v-if="screen === 'home'" class="shop-hero"><h1>选喜欢的好物，<br />让日常更舒适。</h1><a href="#shop-catalog" @click.prevent="workspaceCatalog?.scrollIntoView({ behavior: 'smooth', block: 'start' })">浏览全部</a></section>
      <template v-if="listingScreen">
        <section v-if="store" class="shop-store-banner"><Icon name="store" :size="32" /><div><h1>{{ store.name }}</h1><p>{{ store.description }}</p></div><a href="#/shop" @click.prevent="go('#/shop')">返回商城</a></section>
        <div id="shop-catalog" ref="workspaceCatalog" class="shop-section-title"><h1 v-if="screen === 'search'">{{ query ? `“${query}”的搜索结果` : '全部商品' }}</h1><h2 v-else>{{ store ? '店铺商品' : '精选好物' }}</h2><div class="shop-categories" aria-label="商品分类"><button v-for="c in [{ id: '', name: '全部' }, { id: 'electronics', name: '数码' }, { id: 'home', name: '家居' }, { id: 'outdoor', name: '户外' }]" :key="c.id" :class="{ current: category === c.id }" :aria-pressed="category === c.id" @click="category = c.id; search()">{{ c.name }}</button></div><div class="shop-store-select"><Icon name="store" :size="18" /><select :value="store?.store_id ?? ''" aria-label="选择店铺" :disabled="loading" @change="changeStore"><option value="">全部店铺</option><option v-for="s in stores" :key="s.store_id" :value="s.store_id">{{ s.name }}</option></select></div></div>
        <p v-if="loading" class="shop-empty" role="status">正在读取商品…</p>
        <p v-else-if="!products.length && !error" class="shop-empty">没有找到商品，请换个关键词或分类。</p>
        <div v-else class="shop-grid"><article v-for="p in displayedProducts" :key="p.product_id" class="product-card">
          <a :href="`#/shop/products/${p.product_id}`" class="product-image" @click.prevent="go(`#/shop/products/${p.product_id}`)"><ProductArt :asset="p.asset_key" :name="p.name" :variant="p.skus[0]?.variant" /></a>
          <div class="shop-product-copy"><a :href="`#/shop/products/${p.product_id}`" class="product-name" @click.prevent="go(`#/shop/products/${p.product_id}`)">{{ p.name }}</a><strong class="product-price">{{ catalogMoney(p.from_amount) }}<span v-if="p.skus.length > 1">起</span></strong><a :href="`#/shop/stores/${p.store_id}`" class="product-store" :aria-label="`进入${p.store_name}店铺`" @click.prevent="go(`#/shop/stores/${p.store_id}`)"><Icon name="store" :size="16" />{{ p.store_name }}</a></div>
        </article></div>
        <button v-if="next" class="shop-secondary shop-load" :disabled="loading" @click="more">加载更多商品</button>
      </template>
      <template v-else-if="screen === 'product'">
        <button class="shop-back" @click="go('#/shop')">返回商城</button>
        <p v-if="loading" class="shop-empty" role="status">正在读取商品…</p>
        <section v-if="product" class="shop-product-detail"><div class="detail-image"><ProductArt :asset="product.asset_key" :name="product.name" :variant="selectedSku?.variant" /></div><div class="detail-copy"><a class="product-store" :href="`#/shop/stores/${product.store_id}`" :aria-label="`进入${product.store_name}店铺`" @click.prevent="go(`#/shop/stores/${product.store_id}`)"><Icon name="store" :size="17" />{{ product.store_name }}</a><h1>{{ product.name }}</h1><p>{{ product.description }}</p><strong class="detail-price">{{ money(selectedSku?.unit_amount ?? product.from_amount) }}</strong><fieldset><legend>选择规格</legend><button v-for="s in product.skus" :key="s.sku_id" :class="{ selected: sku === s.sku_id }" :aria-pressed="sku === s.sku_id" :disabled="loading || writing || uncertain" @click="sku = s.sku_id; quantity = Math.min(quantity, s.max_quantity); ++quoteGeneration">{{ s.variant }}</button></fieldset><label class="quantity-label">数量 <input v-model.number="quantity" type="number" min="1" :max="selectedSku?.max_quantity" step="1" aria-label="购买数量" :disabled="loading || writing || uncertain" /></label><div class="product-buy-actions"><button class="shop-primary buy-button" :disabled="loading || writing || uncertain" @click="buy">确认购买</button><button class="shop-secondary cart-add" :disabled="loading || writing" @click="addCart">{{ writing ? '正在确认…' : uncertain && pendingAdd ? '用原请求确认结果' : '加入购物车' }}</button></div><div v-if="added" class="cart-added" role="status"><p>已加入购物车</p><button class="shop-secondary" @click="go('#/shop/cart')">查看购物车</button></div><button v-if="error && !uncertain" class="shop-secondary" @click="route">重新读取商品</button></div></section>
        <ProductReviews v-if="product" :key="product.product_id" :product="product.product_id" />
      </template>
      <template v-else-if="screen === 'checkout' && quote">
        <button class="shop-back" :disabled="writing || uncertain" @click="screen = 'product'; quote = null">修改规格与数量</button><h1>确认订单</h1>
        <section class="checkout-address" aria-label="收货信息"><h2>演示收货信息</h2><p>演示买家 · 杭州市演示路 100 号</p></section>
        <section class="checkout-panel"><h2>{{ quote.product.store_name }}</h2><div class="checkout-line"><ProductArt :asset="quote.product.asset_key" :name="quote.product.name" :variant="quote.sku.variant" /><div><h2>{{ quote.product.name }}</h2><p>{{ quote.sku.variant }}</p></div><div><p>单价</p><strong>{{ money(quote.sku.unit_amount) }}</strong></div><div><p>数量</p><strong>{{ quote.quantity }}</strong></div><div><p>小计</p><strong>{{ money(quote.total_amount) }}</strong></div></div><div class="checkout-total"><span>应付合计</span><strong>{{ money(quote.total_amount) }}</strong></div><button class="shop-primary" :disabled="writing" @click="submit">{{ writing ? '正在确认…' : uncertain ? '用原请求确认结果' : '提交订单' }}</button></section>
      </template>
    </main>
    <footer class="shop-footer">ResolveFlow · 本地演示，商品为合成素材，交易与退款均为模拟。</footer>
  </div>
</template>
