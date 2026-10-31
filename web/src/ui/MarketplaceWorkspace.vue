<script setup lang="ts">
import { beginBuyerNavigation, pushBuyerNavigation, hasBuyerPrevious } from '../buyer-navigation'
import { createPageMotion } from './page-motion'
import StoreMark from './StoreMark.vue'
import { useDismissible } from './useDismissible'
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch, reactive } from 'vue'
import { ApiError, type LoginResponse } from '../client'
import { shopApi, type ShopProduct, type ShopStore, type ShopQuote, type ShopDraft, type ShopDraftRequest } from '../shop-client'
import { formatMinorUnits } from '../money'
import ProductArt from './ProductArt.vue'
import ProductGallery from './ProductGallery.vue'
import StoreProfile from './StoreProfile.vue'
import CatalogImage from './CatalogImage.vue'
import Icon from './ReviewIcon.vue'
import CustomerWorkspace from './CustomerWorkspace.vue'
import SupportWorkspace from './SupportWorkspace.vue'
import BuyerOrders from './BuyerOrders.vue'
import ProductReviews from './ProductReviews.vue'
import type { ReviewSummary } from '../review-client'
import CartWorkspace from './CartWorkspace.vue'
import OrderSummary from './OrderSummary.vue'
import './purchase-layout.css'
import AccountWorkspace from './AccountWorkspace.vue'
import type { AccountEditMemory } from './account-edit-memory'
import type { CursorPageMemory } from '../cursor-pages'
import NotificationCenter from './NotificationCenter.vue'
import PersonalCenter from './PersonalCenter.vue'
import EnrollmentForm from './EnrollmentForm.vue'
import type { Notification } from '../notification-client'
import UserAvatar from './UserAvatar.vue'
import AddressPicker from './AddressPicker.vue'
import type { AccountProfile, ShippingSelection } from '../account-client'
import { readCartPending, saveCartPending, clearCartPending, type CartPending } from '../cart-pending'
import './marketplace.css'

const notificationMemory: CursorPageMemory<string> = { index: 0, cursors: [undefined] }
const accountEditMemory = reactive<AccountEditMemory>({})
const props = defineProps<{ account: LoginResponse | null }>()
const emit = defineEmits<{ expired: []; reauthenticate: [loginName: string]; login: []; logout: []; profile: [value: AccountProfile] }>()
type Screen = 'home' | 'search' | 'store' | 'product' | 'checkout' | 'orders' | 'customer' | 'cart' | 'support' | 'profile' | 'addresses' | 'me' | 'messages' | 'security'
const windowHash = ref(window.location.hash)
const supportInitialId = computed(() => new URLSearchParams(windowHash.value.split('?')[1] ?? '').get('conversation') ?? undefined)
const screen = ref<Screen>('home'), query = ref(''), category = ref(''), stores = ref<ShopStore[]>([])
const workspaceCatalog = ref<HTMLElement>()
const pageSurface = ref<HTMLElement>()
const pageMotion = createPageMotion(() => pageSurface.value ?? null)
let previousDepth = 0
const accountMenu = ref<HTMLDetailsElement>()
useDismissible(accountMenu, () => !!accountMenu.value?.open, () => { if (accountMenu.value) accountMenu.value.open = false })
const ordersRoute = ref(''), cartBusy = ref(false), added = ref(false)
const shipping = ref<ShippingSelection | null>(null), addressBusy = ref(false)
let pendingAdd: Extract<CartPending, { kind: 'mutation' }> | null = null
const products = ref<ShopProduct[]>([]), store = ref<ShopStore | null>(null), product = ref<ShopProduct | null>(null)
const reviewSummary = ref<ReviewSummary | null>(null), reviewsAnchor = ref<HTMLElement>()
const sku = ref(''), quantity = ref(1), quote = ref<ShopQuote | null>(null), draft = ref<ShopDraft | null>(null)
const loading = ref(false), writing = ref(false), uncertain = ref(false), error = ref(''), next = ref<string | null>(null)
const pageIndex = ref(0), pageCursors = ref<Array<string | undefined>>([undefined])
const activeWorkspace = ref<{ navigationBlocked: boolean; backWithin?: () => boolean; viewScroll?: () => number }>()
const navigationOwner = () => props.account?.buyer_id ?? 'visitor'
const hasPrevious = ref(false)
const navigationBlocked = computed(() => writing.value || uncertain.value || cartBusy.value || addressBusy.value || activeWorkspace.value?.navigationBlocked === true)
function back() {
  if (navigationBlocked.value) return
  if (accountMenu.value) accountMenu.value.open = false
  if (screen.value === 'cart' && activeWorkspace.value?.backWithin?.()) return
  if (screen.value === 'checkout') { leaveCheckout(); return }
  rememberView()
  if (hasBuyerPrevious(navigationOwner())) window.history.back()
  else { window.history.replaceState(null, '', '#/shop'); void route() }
}
let generation = 0, quoteGeneration = 0, alive = true, pending: { key: string; request: ShopDraftRequest } | null = null
// Memory belongs to this account's workspace; history stores only the entry identity.
type BrowseView = { hash: string; at: number; scroll: number; listing?: { products: ShopProduct[]; next: string | null; index: number; cursors: Array<string | undefined>; store: ShopStore | null }; product?: { sku: string; quantity: number }; cart?: string[]; cartStore?: string }
const views = new Map<string, BrowseView>()
const cartInitialStore = ref<string | undefined>(), cartStore = ref('')
const cartInitial = ref<string[] | undefined>(), cartSelection = ref<string[]>([]), slowLoading = ref(false)
let currentHash = '', currentEntry = '', cartPosition = 0, productPosition = 0, catalogReadAt = 0
let positionFrame: number | undefined, loadingTimer: ReturnType<typeof setTimeout> | undefined
let previousScrollRestoration: ScrollRestoration
watch(loading, value => { clearTimeout(loadingTimer); slowLoading.value = false; if (value) loadingTimer = setTimeout(() => { slowLoading.value = true }, 150) })
function rememberView() {
  if (!currentEntry || loading.value || error.value || !['home','search','store','product','cart'].includes(screen.value)) return
  const value: BrowseView = { hash: currentHash, at: Date.now(), scroll: window.scrollY }
  if (listingScreen.value) { value.at = catalogReadAt; value.listing = { products: products.value, next: next.value, index: pageIndex.value, cursors: [...pageCursors.value], store: store.value } }
  if (screen.value === 'product' && product.value) value.product = { sku: sku.value, quantity: quantity.value }
  if (screen.value === 'cart') { value.cart = [...cartSelection.value]; value.cartStore = cartStore.value; value.scroll = activeWorkspace.value?.viewScroll?.() ?? value.scroll }
  views.delete(currentEntry); views.set(currentEntry, value)
  if (views.size > 12) views.delete(views.keys().next().value!)
}
watch([sku, quantity], rememberView)
async function position(top: number, g = generation) {
  await nextTick(); cancelAnimationFrame(positionFrame ?? 0)
  positionFrame = requestAnimationFrame(() => { if (alive && g === generation) window.scrollTo({ top, behavior: 'auto' }) })
}
function restoreCart() { if (screen.value === 'cart') void position(cartPosition) }
function leaveCheckout() { void pageMotion.navigate(() => { ++quoteGeneration; quote.value = null; screen.value = 'product'; error.value = ''; void position(productPosition) }, { direction: 'back', native: false }) }

watch([sku, quantity], () => { added.value = false })
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
  if (accountMenu.value) accountMenu.value.open = false
  if (navigationBlocked.value) { error.value = '请先确认本次订单提交结果。'; return }
  rememberView(); pushBuyerNavigation(hash, navigationOwner()); void route()
}
function openNotification(item: Notification) { go(item.target === 'APPLICATION' ? `#/customer/applications/${encodeURIComponent(item.target_id)}` : `#/shop/support?conversation=${encodeURIComponent(item.target_id)}`) }
function search() { go(`${store.value ? `#/shop/stores/${encodeURIComponent(store.value.store_id)}` : '#/shop/search'}?${new URLSearchParams({ ...(query.value.trim() ? { query: query.value.trim() } : {}), ...(category.value ? { category: category.value } : {}) })}`) }
function changeStore(event: Event) {
  const id = (event.target as HTMLSelectElement).value
  const params = new URLSearchParams({ ...(query.value.trim() ? { query: query.value.trim() } : {}), ...(category.value ? { category: category.value } : {}) }).toString()
  go(`${id ? `#/shop/stores/${encodeURIComponent(id)}` : params ? '#/shop/search' : '#/shop'}${params ? `?${params}` : ''}`)
}
async function route(force = false) {
  if (navigationBlocked.value || !force && window.location.hash === currentHash) return
  const depth = window.history.state?.resolveflow_buyer_navigation?.depth ?? 0
  const direction = depth < previousDepth ? 'back' : 'forward'
  previousDepth = depth
  const hash = window.location.hash
  let target = (hash === '#/shop' || hash.startsWith('#/shop/search') || hash.startsWith('#/shop/stores/')) ? product.value?.product_id : undefined
  try { if (hash.startsWith('#/shop/products/')) target = decodeURIComponent(hash.slice('#/shop/products/'.length)) } catch { target = undefined }
  // Snapshot transitions are reserved for shared product images. Ordinary pages
  // enter on the live DOM so navigation stays clickable throughout loading.
  await pageMotion.navigate(() => readRoute(force), { direction, product: target, native: !!target, initial: !currentHash || force })
}
async function readRoute(force = false) {
  if (navigationBlocked.value || !force && window.location.hash === currentHash) return
  rememberView()
  currentHash = window.location.hash
  const historyEntry = window.history.state?.resolveflow_browse
  currentEntry = typeof historyEntry === 'string' && historyEntry.length < 80 ? historyEntry : crypto.randomUUID()
  if (currentEntry !== historyEntry) window.history.replaceState({ ...window.history.state, resolveflow_browse: currentEntry }, '')
  const candidate = views.get(currentEntry)
  const saved = candidate?.hash === currentHash && Date.now() - candidate.at < 300000 ? candidate : undefined
  cartInitialStore.value = saved?.cartStore; cartStore.value = saved?.cartStore ?? ''; cartInitial.value = saved?.cart; cartSelection.value = saved?.cart ?? []; cartPosition = saved?.scroll ?? 0
  beginBuyerNavigation(navigationOwner()); hasPrevious.value = hasBuyerPrevious(navigationOwner())
  const g = ++generation; ++quoteGeneration
  error.value = ''; added.value = false; quote.value = null; draft.value = null; store.value = null; product.value = null; reviewSummary.value = null; pending = null
  products.value = []; next.value = null; pageIndex.value = 0; pageCursors.value = [undefined]
  let hash = window.location.hash; windowHash.value = hash
  if (hash === '#/shop/profile' || hash === '#/shop/addresses') { screen.value = hash.endsWith('/profile') ? 'profile' : 'addresses'; loading.value = false; if (!props.account) emit('login'); return }
  if (hash === '#/shop/security') { screen.value = 'security'; loading.value = false; if (!props.account) emit('login'); return }
  if (hash === '#/shop/me' || hash === '#/shop/messages') { screen.value = hash.endsWith('/me') ? 'me' : 'messages'; loading.value = false; if (!props.account) emit('login'); return }
  if (hash.startsWith('#/shop/support')) { screen.value = 'support'; loading.value = false; if (!props.account) emit('login'); return }
  if (hash.startsWith('#/customer/')) { screen.value = 'customer'; loading.value = false; return }
  loading.value = true
  try {
    if (props.account?.buyer_id && readCartPending(props.account.buyer_id) && hash !== '#/shop/cart') {
      hash = '#/shop/cart'; window.history.replaceState({ ...window.history.state }, '', hash); currentHash = hash; windowHash.value = hash
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
      if (alive && g === generation) { product.value = result; const choice = result.skus.find(s => s.sku_id === saved?.product?.sku) ?? result.skus[0]; sku.value = choice.sku_id; quantity.value = Math.max(1, Math.min(Number.isInteger(saved?.product?.quantity) ? saved!.product!.quantity : 1, choice.max_quantity)) }
    } else {
      const isStore = hash.startsWith('#/shop/stores/'), isSearch = hash.startsWith('#/shop/search')
      screen.value = isStore ? 'store' : isSearch ? 'search' : 'home'
      const params = new URLSearchParams(hash.split('?')[1] ?? '')
      query.value = params.get('query') ?? ''; category.value = params.get('category') ?? ''
      const storeId = isStore ? decodeURIComponent(hash.slice('#/shop/stores/'.length).split('?')[0]) : undefined
      const remembered = window.history.state?.resolveflow_listing
      if (remembered?.hash === hash && Number.isInteger(remembered.index) && remembered.index > 0 && Array.isArray(remembered.cursors) && remembered.cursors.length <= 1000 && remembered.index < remembered.cursors.length && remembered.cursors.every((c: unknown) => c === undefined || typeof c === 'string') && typeof remembered.cursors[remembered.index] === 'string') { pageIndex.value = remembered.index; pageCursors.value = remembered.cursors }
      if (saved?.listing) { catalogReadAt = saved.at; products.value = saved.listing.products; next.value = saved.listing.next; pageIndex.value = saved.listing.index; pageCursors.value = [...saved.listing.cursors]; store.value = saved.listing.store; return }
      const after = pageCursors.value[pageIndex.value]
      const [listing, allStores, ownStore] = await Promise.all([shopApi.products({ ...(after ? { after } : {}), ...(query.value ? { query: query.value } : {}), ...(category.value ? { category: category.value } : {}), ...(storeId ? { store_id: storeId } : {}) }), shopApi.stores(), storeId ? shopApi.store(storeId) : Promise.resolve(null)])
      if (alive && g === generation) { catalogReadAt = Date.now(); products.value = listing.items; next.value = listing.next_after; stores.value = allStores; store.value = ownStore }
    }
  } catch (cause) { if (alive && g === generation) failure(cause) }
  finally { if (alive && g === generation) { loading.value = false; if (listingScreen.value || screen.value === 'product') void position(saved?.scroll ?? 0, g) } }
}
async function changePage(target: number) {
  if (loading.value || target < 0 || target > pageIndex.value + 1 || target > pageIndex.value && !next.value) return
  const cursor = target === pageIndex.value + 1 ? next.value! : pageCursors.value[target]
  const direction = target < pageIndex.value ? 'back' : 'forward'
  await pageMotion.navigate(async () => {
  const g = ++generation; loading.value = true; error.value = ''
  try {
    const result = await shopApi.products({ ...(cursor ? { after: cursor } : {}), ...(query.value ? { query: query.value } : {}), ...(category.value ? { category: category.value } : {}), ...(store.value ? { store_id: store.value.store_id } : {}) })
    if (alive && g === generation) { catalogReadAt = Date.now(); products.value = result.items; next.value = result.next_after; pageCursors.value[target] = cursor; pageIndex.value = target; window.history.replaceState({ ...window.history.state, resolveflow_listing: { hash: windowHash.value, index: target, cursors: [...pageCursors.value] } }, ''); workspaceCatalog.value?.scrollIntoView({ block: 'start' }) }
  } catch (cause) { if (alive && g === generation) failure(cause) } finally { if (alive && g === generation) loading.value = false }
  }, { direction, native: false })
}

async function buy() {
  if (!props.account) { emit('login'); return }
  if (!selectedSku.value || writing.value || !Number.isInteger(quantity.value) || quantity.value < 1 || quantity.value > selectedSku.value.max_quantity) { error.value = '请选择有效规格与数量。'; return }
  rememberView(); productPosition = window.scrollY
  const g = ++quoteGeneration; loading.value = true; error.value = ''
  const requestSku = sku.value, requestQuantity = quantity.value
  try {
    const result = await shopApi.quote(requestSku, requestQuantity)
    if (alive && g === quoteGeneration && requestSku === sku.value && requestQuantity === quantity.value) await pageMotion.navigate(() => {
      if (!alive || g !== quoteGeneration) return
      quote.value = result; screen.value = 'checkout'; loading.value = false; pending = null; void position(0)
    }, { native: false })
  } catch (cause) { if (alive && g === quoteGeneration) failure(cause) } finally { if (alive && g === quoteGeneration) loading.value = false }
}
async function submit() {
  if (!props.account || !quote.value || writing.value || addressBusy.value || !shipping.value && !pending) return
  if (!pending) pending = { key: crypto.randomUUID(), request: { sku_id: quote.value.sku.sku_id, quantity: quote.value.quantity, expected_sku_version: quote.value.sku.version, shipping: shipping.value! } }
  const request = pending; writing.value = true; error.value = ''
  try {
    const result = await shopApi.draft(props.account.access_token, request.request, request.key)
    if (!alive) return
    uncertain.value = false; draft.value = result; pending = null
    ordersRoute.value = `#/shop/drafts/${encodeURIComponent(result.draft_id)}`
    pushBuyerNavigation(ordersRoute.value, navigationOwner()); hasPrevious.value = hasBuyerPrevious(navigationOwner()); screen.value = 'orders'
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
const handleRoute = () => { void route() }
onMounted(() => { previousScrollRestoration = window.history.scrollRestoration; window.history.scrollRestoration = 'manual'; void route(); window.addEventListener('hashchange', handleRoute); window.addEventListener('popstate', handleRoute); window.addEventListener('scroll', rememberView, { passive: true }) })
onBeforeUnmount(() => { pageMotion.dispose(); alive = false; ++generation; ++quoteGeneration; clearTimeout(loadingTimer); cancelAnimationFrame(positionFrame ?? 0); views.clear(); window.history.scrollRestoration = previousScrollRestoration; window.removeEventListener('hashchange', handleRoute); window.removeEventListener('popstate', handleRoute); window.removeEventListener('scroll', rememberView) })
</script>

<template>
  <div class="marketplace" :class="{ 'buyer-aftercare': screen === 'customer', 'support-marketplace': screen === 'support' }">
    <nav class="shop-nav" aria-label="买家导航">
      <div class="shop-brand-block"><a href="#/shop" class="shop-brand" aria-label="ResolveFlow 商城首页" @click.prevent="go('#/shop')"><span class="brand-mark" aria-hidden="true"><i /><i /><i /><i /></span><span>ResolveFlow</span></a><button type="button" class="shop-back" aria-label="返回上一页" :disabled="navigationBlocked || (screen === 'home' && !hasPrevious)" @click="back">返回</button></div>
      <form v-if="listingScreen || screen === 'product'" class="shop-search" role="search" @submit.prevent="search"><input v-model="query" type="search" aria-label="搜索商品" placeholder="搜索商品" maxlength="80" /><button type="submit" aria-label="搜索"><Icon name="search" :size="20" /></button></form>
      <span v-else class="shop-nav-space" />
      <div class="shop-utilities">
        <a href="#/shop/orders" :class="{ current: screen === 'orders' }" @click.prevent="go('#/shop/orders')">我的订单</a>
        <a href="#/shop/support" :class="{ current: screen === 'support' }" @click.prevent="go('#/shop/support')">售后咨询</a>
        <a href="#/shop/cart" :class="{ current: screen === 'cart' }" aria-label="购物车" title="购物车" @click.prevent="go('#/shop/cart')"><Icon name="cart" :size="23" /></a>
        <NotificationCenter v-if="account" :token="account.access_token" :disabled="writing || uncertain || cartBusy || addressBusy" @expired="emit('expired')" @open="openNotification" />
        <details v-if="account" ref="accountMenu" class="shop-account"><summary aria-label="账户菜单"><UserAvatar :token="account.access_token" source="/api/v1/account/avatar" :name="account.display_name" :size="32" /><span>{{ account.display_name || '我的账户' }}</span></summary><div><a href="#/shop/me" @click.prevent="go('#/shop/me')">个人中心</a><a href="#/shop/profile" @click.prevent="go('#/shop/profile')">个人资料</a><a href="#/shop/addresses" @click.prevent="go('#/shop/addresses')">收货地址</a><a href="#/customer/applications" @click.prevent="go('#/customer/applications')">我的售后</a><button type="button" @click="emit('logout')">退出登录</button></div></details>
        <button v-else class="shop-login" @click="emit('login')">登录</button>
      </div>
    </nav>
    <p v-if="error" class="shop-error shop-global-error" role="alert">{{ error }}</p>
    <div ref="pageSurface" class="buyer-route-frame">
    <AccountWorkspace :key="account.access_token" v-if="(screen === 'profile' || screen === 'addresses') && account" :account="account" :mode="screen" :memory="accountEditMemory" @reauthenticate="emit('reauthenticate', $event)" @saved="emit('profile', $event)" @working="cartBusy = $event" @expired="emit('expired')" />
    <EnrollmentForm v-else-if="screen === 'security' && account" mode="rotate" :token="account.access_token" @working="cartBusy = $event" @close="go('#/shop/me')" @expired="emit('expired')" />
    <PersonalCenter v-else-if="screen === 'me' && account" :account="account" @navigate="go" @expired="emit('expired')" />
    <NotificationCenter v-else-if="screen === 'messages' && account" :token="account.access_token" expanded :memory="notificationMemory" @expired="emit('expired')" @open="openNotification" />
    <SupportWorkspace ref="activeWorkspace" v-else-if="screen === 'support' && account" :key="account.access_token + windowHash" :initial-id="supportInitialId" :account="account" @expired="emit('expired')" />
    <CartWorkspace :initial-store="cartInitialStore" @store="cartStore = $event" ref="activeWorkspace" :initial-selection="cartInitial" @selection="cartSelection = $event" @ready="restoreCart" v-else-if="screen === 'cart' && account" :account="account" @expired="emit('expired')" @navigate="go" @busy="cartBusy = $event" />
    <CustomerWorkspace ref="activeWorkspace" v-else-if="screen === 'customer' && account" :account="account" @expired="emit('expired')" />
    <BuyerOrders ref="activeWorkspace" v-else-if="screen === 'orders' && account" :route-key="ordersRoute" :account="account" @expired="emit('expired')" @navigate="go" />
    <main v-else :key="windowHash + screen" class="shop-content shop-view" :aria-busy="loading">

      <section v-if="screen === 'home'" class="shop-hero" data-page-reveal><h1>选喜欢的好物，<br />让日常更舒适。</h1><a href="#shop-catalog" @click.prevent="workspaceCatalog?.scrollIntoView({ behavior: 'smooth', block: 'start' })">浏览全部</a></section>
      <template v-if="listingScreen">
        <StoreProfile v-if="store" :id="store.store_id" :name="store.name" :description="store.description" @contact="go('#/shop/support')" />
        <div id="shop-catalog" ref="workspaceCatalog" class="shop-section-title" data-page-reveal><h1 v-if="screen === 'search'">{{ query ? `“${query}”的搜索结果` : '全部商品' }}</h1><h2 v-else>{{ store ? '店铺商品' : '精选好物' }}</h2><div class="shop-categories" aria-label="商品分类"><button v-for="c in [{ id: '', name: '全部' }, { id: 'electronics', name: '数码' }, { id: 'home', name: '家居' }, { id: 'outdoor', name: '户外' }]" :key="c.id" :class="{ current: category === c.id }" :aria-pressed="category === c.id" @click="category = c.id; search()">{{ c.name }}</button></div><div class="shop-store-select"><Icon name="store" :size="18" /><select :value="store?.store_id ?? ''" aria-label="选择店铺" :disabled="loading" @change="changeStore"><option value="">全部店铺</option><option v-for="s in stores" :key="s.store_id" :value="s.store_id">{{ s.name }}</option></select></div></div>
        <div v-if="loading && slowLoading && !products.length" class="shop-grid catalog-skeleton" role="status" aria-label="正在读取商品"><div v-for="i in 8" :key="i" aria-hidden="true"><i /><span /><span /></div></div>
        <p v-else-if="!loading && !products.length && !error" class="shop-empty">没有找到商品，请换个关键词或分类。</p>
        <div v-else class="shop-grid" data-page-reveal><article v-for="p in displayedProducts" :key="p.product_id" class="product-card">
          <a :href="`#/shop/products/${p.product_id}`" class="product-image" :data-motion-product="p.product_id" @click.prevent="go(`#/shop/products/${p.product_id}`)"><CatalogImage v-if="p.cover_image_id" :id="p.cover_image_id" :name="p.name" /><ProductArt v-else :asset="p.asset_key" :name="p.name" :variant="p.skus[0]?.variant" /></a>
          <div class="shop-product-copy"><a :href="`#/shop/products/${p.product_id}`" class="product-name" @click.prevent="go(`#/shop/products/${p.product_id}`)">{{ p.name }}</a><strong class="product-price">{{ catalogMoney(p.from_amount) }}<span v-if="p.skus.length > 1">起</span></strong><a :href="`#/shop/stores/${p.store_id}`" class="product-store" :aria-label="`进入${p.store_name}店铺`" @click.prevent="go(`#/shop/stores/${p.store_id}`)"><StoreMark :id="p.store_id" :size="16" />{{ p.store_name }}</a></div>
        </article></div>
        <nav v-if="products.length || pageIndex" class="catalog-pagination" aria-label="商品分页"><button class="shop-secondary" aria-label="上一页" :disabled="loading || pageIndex === 0" @click="changePage(pageIndex - 1)">上一页</button><span aria-live="polite">第 {{ pageIndex + 1 }} 页</span><button class="shop-secondary" aria-label="下一页" :disabled="loading || !next" @click="changePage(pageIndex + 1)">下一页</button></nav>
      </template>
      <template v-else-if="screen === 'product'">
        <div v-if="loading && slowLoading && !product" class="product-skeleton" role="status" aria-label="正在读取商品"><i /><div><i /><i /><i /></div></div>
        <section v-if="product" class="shop-product-detail"><ProductGallery :product="product.product_id" :asset="product.asset_key" :name="product.name" :variant="selectedSku?.variant" /><div class="detail-copy" data-page-reveal><a class="product-store" :href="`#/shop/stores/${product.store_id}`" :aria-label="`进入${product.store_name}店铺`" @click.prevent="go(`#/shop/stores/${product.store_id}`)"><StoreMark :id="product.store_id" :size="17" />{{ product.store_name }}</a><h1>{{ product.name }}</h1><p>{{ product.description }}</p><strong class="detail-price">{{ money(selectedSku?.unit_amount ?? product.from_amount) }}</strong><button v-if="reviewSummary?.count" class="product-review-entry" aria-label="查看买家评价" @click="reviewsAnchor?.scrollIntoView({ behavior: 'smooth', block: 'start' })"><span>{{ reviewSummary.average?.toFixed(1) }} 分</span><span>{{ reviewSummary.count }} 条评价</span></button><fieldset><legend>选择规格</legend><button v-for="s in product.skus" :key="s.sku_id" :class="{ selected: sku === s.sku_id }" :aria-pressed="sku === s.sku_id" :disabled="loading || writing || uncertain" @click="sku = s.sku_id; quantity = Math.min(quantity, s.max_quantity); ++quoteGeneration">{{ s.variant }}</button></fieldset><div class="quantity-label"><span>数量</span><div class="product-quantity"><button type="button" aria-label="减少购买数量" :disabled="loading || writing || uncertain || quantity <= 1" @click="quantity--">−</button><input v-model.number="quantity" type="number" min="1" :max="selectedSku?.max_quantity" step="1" aria-label="购买数量" :disabled="loading || writing || uncertain" /><button type="button" aria-label="增加购买数量" :disabled="loading || writing || uncertain || !selectedSku || quantity >= selectedSku.max_quantity" @click="quantity++">+</button></div></div><div class="product-buy-actions"><button class="shop-primary buy-button" :disabled="loading || writing || uncertain" @click="buy">立即购买</button><button class="shop-secondary cart-add" :disabled="loading || writing" @click="addCart">{{ writing ? '正在确认…' : uncertain && pendingAdd ? '用原请求确认结果' : '加入购物车' }}</button></div><div class="cart-feedback"><div v-if="added" class="cart-added" role="status"><span>已加入购物车</span><button class="shop-secondary" @click="go('#/shop/cart')">查看购物车</button></div></div><button v-if="error && !uncertain" class="shop-secondary" @click="route(true)">重新读取商品</button></div></section>
        <div v-if="product" ref="reviewsAnchor" class="product-review-anchor"><ProductReviews :key="product.product_id" :product="product.product_id" @summary="reviewSummary = $event" /></div>
      </template>
      <template v-else-if="screen === 'checkout' && quote">
        <header class="checkout-heading" data-page-reveal><h1>确认订单</h1><button class="shop-text" :disabled="writing || uncertain || addressBusy" @click="leaveCheckout">修改规格与数量</button></header>
        <div class="purchase-layout" data-page-reveal><div class="purchase-main-column">
          <AddressPicker v-if="account" v-model="shipping" :account="account" :disabled="writing || uncertain" @working="addressBusy = $event" @expired="emit('expired')" />
          <section class="checkout-panel"><h2>{{ quote.product.store_name }}</h2><div class="checkout-line"><ProductArt :asset="quote.product.asset_key" :name="quote.product.name" :variant="quote.sku.variant" /><div><h2>{{ quote.product.name }}</h2><p>{{ quote.sku.variant }} · 数量 {{ quote.quantity }}</p><p>单价 {{ money(quote.sku.unit_amount) }}</p></div><strong>{{ money(quote.total_amount) }}</strong></div></section>
        </div><OrderSummary :amount="quote.total_amount" :quantity="quote.quantity" :action="uncertain ? '用原请求确认结果' : '提交订单'" action-class="checkout-submit" :disabled="addressBusy || (!shipping && !uncertain)" :busy="writing" @submit="submit" /></div>
      </template>
    </main>
    </div>
  </div>
</template>
