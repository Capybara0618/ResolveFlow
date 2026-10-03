<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { ApiError, type LoginResponse } from '../client'
import { shopApi, type ShopProduct, type ShopStore, type ShopQuote, type ShopDraft, type ShopDraftRequest } from '../shop-client'
import { formatMinorUnits } from '../money'
import ProductArt from './ProductArt.vue'
import CustomerWorkspace from './CustomerWorkspace.vue'
import './marketplace.css'

const props = defineProps<{ account: LoginResponse | null }>()
const emit = defineEmits<{ expired: []; login: [] }>()
type Screen = 'home' | 'search' | 'store' | 'product' | 'checkout' | 'draft' | 'customer'
const screen = ref<Screen>('home'), query = ref(''), category = ref(''), stores = ref<ShopStore[]>([])
const products = ref<ShopProduct[]>([]), store = ref<ShopStore | null>(null), product = ref<ShopProduct | null>(null)
const sku = ref(''), quantity = ref(1), quote = ref<ShopQuote | null>(null), draft = ref<ShopDraft | null>(null)
const loading = ref(false), writing = ref(false), uncertain = ref(false), error = ref(''), next = ref<string | null>(null)
let generation = 0, quoteGeneration = 0, alive = true, pending: { key: string; request: ShopDraftRequest } | null = null
const selectedSku = computed(() => product.value?.skus.find(s => s.sku_id === sku.value))
const money = (amount: number) => `¥ ${formatMinorUnits(amount).replace(' CNY', '')}`
function failure(cause: unknown) {
  if (cause instanceof ApiError && cause.status === 401) { emit('expired'); return }
  error.value = cause instanceof ApiError && cause.status === 404 ? '商品已下架，或当前账号无法查看这份订单。'
    : cause instanceof ApiError && cause.status === 403 ? '请使用平台买家账号购买商品。'
    : cause instanceof ApiError ? cause.message : '连接暂时中断，请重试。'
}
function go(hash: string) {
  if (writing.value || uncertain.value) { error.value = '请先确认本次订单提交结果。'; return }
  window.history.pushState(null, '', hash); void route()
}
function search() { go(`${store.value ? `#/shop/stores/${encodeURIComponent(store.value.store_id)}` : '#/shop/search'}?${new URLSearchParams({ ...(query.value.trim() ? { query: query.value.trim() } : {}), ...(category.value ? { category: category.value } : {}) })}`) }
async function route() {
  if (writing.value || uncertain.value) return
  const g = ++generation; ++quoteGeneration
  error.value = ''; quote.value = null; draft.value = null; store.value = null; product.value = null; pending = null
  products.value = []; next.value = null
  const hash = window.location.hash
  if (hash.startsWith('#/customer/')) { screen.value = 'customer'; loading.value = false; return }
  loading.value = true
  try {
    if (/^#\/shop\/drafts\//.test(hash)) {
      screen.value = 'draft'
      if (!props.account) { emit('login'); return }
      const result = await shopApi.readDraft(props.account.access_token, decodeURIComponent(hash.slice('#/shop/drafts/'.length)))
      if (alive && g === generation) draft.value = result
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
    uncertain.value = false; draft.value = result; screen.value = 'draft'; pending = null
    window.history.pushState(null, '', `#/shop/drafts/${encodeURIComponent(result.draft_id)}`)
  } catch (cause) {
    if (!alive) return
    if (!(cause instanceof ApiError) || cause.status >= 500) { uncertain.value = true; error.value = '提交结果尚未确认，请用原请求重试确认。' }
    else { uncertain.value = false; failure(cause)
      if (cause.code === 'PRICE_CHANGED') { quote.value = null; screen.value = 'product'; error.value = '价格或规格已更新，请重新读取商品并确认报价。' }
    }
  } finally { if (alive) writing.value = false }
}
onMounted(() => { void route(); window.addEventListener('hashchange', route); window.addEventListener('popstate', route) })
onBeforeUnmount(() => { alive = false; ++generation; ++quoteGeneration; window.removeEventListener('hashchange', route); window.removeEventListener('popstate', route) })
</script>

<template>
  <div :class="screen === 'customer' ? 'buyer-aftercare' : 'marketplace'">
    <nav class="shop-nav" aria-label="买家导航">
      <a href="#/shop" :class="{ current: screen !== 'customer' }" @click.prevent="go('#/shop')">商城</a>
      <a v-if="account" href="#/customer/orders" @click.prevent="go('#/customer/orders')">我的订单</a>
      <a v-if="account" href="#/customer/applications" @click.prevent="go('#/customer/applications')">我的售后</a>
      <button v-if="!account" class="shop-login" @click="emit('login')">登录</button>
    </nav>
    <CustomerWorkspace v-if="screen === 'customer' && account" :account="account" @expired="emit('expired')" />
    <main v-else class="shop-content">
      <p v-if="error" class="shop-error" role="alert">{{ error }}</p>
      <form v-if="['home','search','store'].includes(screen)" class="shop-search" @submit.prevent="search"><input v-model="query" aria-label="搜索商品" placeholder="搜索商品，发现喜欢的好物" maxlength="80" /><button type="submit">搜索</button></form>
      <div v-if="screen === 'home'" class="shop-hero"><div><p>数码与家居</p><h1>选喜欢的好物，<br />让日常更舒适。</h1><p>逛逛不同店铺，从这里开始。</p><button @click="category = 'electronics'; search()">浏览数码商品 →</button></div><div class="hero-art"><ProductArt asset="headphones" name="无线降噪耳机" /><ProductArt asset="lamp" name="桌面台灯" /></div></div>
      <template v-if="['home','search','store'].includes(screen)">
        <section v-if="store" class="shop-store-banner"><span class="store-symbol">{{ store.name.slice(0,1) }}</span><div><h1>{{ store.name }}</h1><p>{{ store.description }}</p></div><a href="#/shop" @click.prevent="go('#/shop')">返回全站商城 →</a></section>
        <div class="shop-section-title"><h1 v-if="screen === 'search'">{{ query ? `“${query}”的搜索结果` : '商品分类' }}</h1><h2 v-else>{{ store ? '店铺商品' : '发现好物' }}</h2><div class="shop-categories"><button v-for="c in [{ id: '', name: '全部' }, { id: 'electronics', name: '数码' }, { id: 'home', name: '家居' }]" :key="c.id" :class="{ current: category === c.id }" @click="category = c.id; search()">{{ c.name }}</button></div></div>
        <p v-if="loading" class="shop-empty" role="status">正在读取商品…</p>
        <p v-else-if="!products.length && !error" class="shop-empty">没有找到商品，请换个关键词或分类。</p>
        <div v-else class="shop-grid"><article v-for="p in products" :key="p.product_id" class="product-card">
          <a :href="`#/shop/products/${p.product_id}`" class="product-image" @click.prevent="go(`#/shop/products/${p.product_id}`)"><ProductArt :asset="p.asset_key" :name="p.name" /></a>
          <div class="product-copy"><a :href="`#/shop/products/${p.product_id}`" class="product-name" @click.prevent="go(`#/shop/products/${p.product_id}`)">{{ p.name }}</a><a :href="`#/shop/stores/${p.store_id}`" class="product-store" @click.prevent="go(`#/shop/stores/${p.store_id}`)">{{ p.store_name }} →</a><strong class="product-price">{{ money(p.from_amount) }}<span v-if="p.skus.length > 1">起</span></strong></div>
        </article></div>
        <button v-if="next" class="shop-secondary shop-load" :disabled="loading" @click="more">加载更多商品</button>
        <section v-if="screen === 'home'" class="shop-stores"><h2>逛逛店铺</h2><div><a v-for="s in stores" :key="s.store_id" :href="`#/shop/stores/${s.store_id}`" @click.prevent="go(`#/shop/stores/${s.store_id}`)"><span class="store-symbol">{{ s.name.slice(0,1) }}</span><span><strong>{{ s.name }}</strong><p>{{ s.description }}</p></span><span>→</span></a></div></section>
      </template>
      <template v-else-if="screen === 'product'">
        <button class="shop-back" @click="go('#/shop')">← 返回商城</button>
        <p v-if="loading" class="shop-empty" role="status">正在读取商品…</p>
        <section v-if="product" class="shop-product-detail"><div class="detail-image"><ProductArt :asset="product.asset_key" :name="product.name" /></div><div class="detail-copy"><a :href="`#/shop/stores/${product.store_id}`" @click.prevent="go(`#/shop/stores/${product.store_id}`)">{{ product.store_name }} →</a><h1>{{ product.name }}</h1><p>{{ product.description }}</p><strong class="detail-price">{{ money(selectedSku?.unit_amount ?? product.from_amount) }}</strong><fieldset><legend>选择规格</legend><button v-for="s in product.skus" :key="s.sku_id" :class="{ selected: sku === s.sku_id }" :disabled="loading" @click="sku = s.sku_id; quantity = Math.min(quantity, s.max_quantity); ++quoteGeneration">{{ s.variant }}</button></fieldset><label class="quantity-label">数量 <input v-model.number="quantity" type="number" min="1" :max="selectedSku?.max_quantity" step="1" aria-label="购买数量" :disabled="loading" /></label><button class="shop-primary buy-button" :disabled="loading" @click="buy">确认购买</button><button v-if="error" class="shop-secondary" @click="route">重新读取商品</button></div></section>
      </template>
      <template v-else-if="screen === 'checkout' && quote">
        <button class="shop-back" :disabled="writing || uncertain" @click="screen = 'product'; quote = null">← 修改规格与数量</button><h1>确认订单</h1>
        <section class="checkout-address"><h2>演示收货信息</h2><p>演示买家 · 杭州市演示路 100 号</p></section>
        <section class="checkout-panel"><h2>{{ quote.product.store_name }}</h2><div class="checkout-line"><ProductArt :asset="quote.product.asset_key" :name="quote.product.name" /><div><h2>{{ quote.product.name }}</h2><p>{{ quote.sku.variant }}</p></div><div><p>单价</p><strong>{{ money(quote.sku.unit_amount) }}</strong></div><div><p>数量</p><strong>{{ quote.quantity }}</strong></div><div><p>小计</p><strong>{{ money(quote.total_amount) }}</strong></div></div><div class="checkout-total"><span>应付合计</span><strong>{{ money(quote.total_amount) }}</strong></div><button class="shop-primary" :disabled="writing" @click="submit">{{ writing ? '正在确认…' : uncertain ? '用原请求确认结果' : '提交订单' }}</button></section>
      </template>
      <template v-else-if="screen === 'draft'">
        <p v-if="loading" class="shop-empty" role="status">正在读取订单…</p>
        <section v-if="draft" class="draft-result"><span class="draft-symbol">{{ draft.status === 'EXPIRED' ? '◷' : '✓' }}</span><h1>{{ draft.status === 'EXPIRED' ? '待支付订单已到期' : '订单已提交，等待付款' }}</h1><p>{{ draft.status === 'EXPIRED' ? '请返回商品页重新确认购买。' : '模拟付款将在下一批开放，本次尚未付款。' }}</p><div class="draft-product"><ProductArt :asset="draft.asset_key" :name="draft.product_name" /><div><h2>{{ draft.product_name }}</h2><p>{{ draft.store_name }} · {{ draft.variant }} × {{ draft.quantity }}</p><strong>{{ money(draft.total_amount) }}</strong></div></div><p>付款截止：{{ new Date(draft.expires_at).toLocaleString('zh-CN', { hour12: false }) }}</p><div class="draft-actions"><button class="shop-primary" @click="go(`#/shop/products/${draft.product_id}`)">返回商品</button><button class="shop-secondary" @click="route">刷新状态</button></div><details><summary>查看订单编号</summary><p>{{ draft.draft_id }}</p></details></section>
      </template>
    </main>
  </div>
</template>
