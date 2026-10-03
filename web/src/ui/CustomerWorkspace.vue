<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiError, coreApi, type CustomerCaseDetail, type CustomerCaseSummary, type CustomerOrderLine,
  type CustomerView, type LoginResponse, type OrderLine } from '../client'
import { formatMinorUnits } from '../money'
import Icon from './ReviewIcon.vue'
import ReviewDialog from './ReviewDialog.vue'
import AftercareProduct from './AftercareProduct.vue'
import { useAftercareProducts } from './aftercare-products'
import './customer-workspace.css'

const props = defineProps<{ account: LoginResponse }>()
const emit = defineEmits<{ expired: [] }>()
const products = useAftercareProducts(() => props.account.access_token)
const productLines = products.lines, productStates = products.states
const previousQuestions = computed(() => detail.value?.questions.filter(q => q !== currentQuestion.value) ?? [])
type Screen = 'orders' | 'applications' | 'apply' | 'detail'
const screen = ref<Screen>('orders'), loading = ref(false), writing = ref(false)
const error = ref(''), notice = ref(''), filter = ref<CustomerView>('ALL')
const orders = ref<OrderLine[]>([]), applications = ref<CustomerCaseSummary[]>([])
const orderCursor = ref<string | null>(), applicationCursor = ref<string | null>()
const applicationUpdate = ref('')
let applicationExpanded = false
const eligibility = ref<Record<string, CustomerOrderLine | null>>({})
const eligibilityErrors = ref<Record<string, string>>({})
const selectedLine = ref<CustomerOrderLine | null>(null), detail = ref<CustomerCaseDetail | null>(null)
const detailLine = ref<OrderLine | null>(null), detailId = ref('')
const description = ref(''), initialMaterial = ref(''), materialText = ref(''), answerText = ref('')
const cancelOpen = ref(false), cancelReason = ref(''), uncertainMaterial = ref(false)
const now = ref(Date.now())
let generation = 0, alive = true, timer: ReturnType<typeof setInterval> | undefined
let pendingCreate: { key: string; line: string; description: string; material: string } | null = null
const createUncertain = ref(false)
const uncertainMaterialIds = ref<string[]>([])
const drafts = new Map<string, { material: string; answer: string; uncertain: boolean; ids: string[] }>()
const labels: Record<string, string> = { QUEUED: '等待调查', ANALYZING: '正在调查', WAITING_CUSTOMER: '待补充说明',
  PENDING_REVIEW: '等待商家审核', AUTHORIZED: '已批准 · 等待执行', EXECUTING: '模拟退款执行中',
  RECONCILING: '结果待确认', CLOSED_SUCCESS: '模拟退款已完成', CLOSED_REJECTED: '申请未获批准', CANCELLED: '已撤销' }
const status = (s: string) => labels[s] ?? s
const terminal = (s: string) => ['CLOSED_SUCCESS', 'CLOSED_REJECTED', 'CANCELLED'].includes(s)
const formatTime = (t: string) => { const date = new Date(t); return Number.isNaN(date.getTime()) ? '时间未提供' : date.toLocaleString('zh-CN', { hour12: false }) }
const currentQuestion = computed(() => detail.value?.questions.find(q => q.status === 'PENDING') ?? null)
const questionExpired = computed(() => !!currentQuestion.value && now.value >= Date.parse(currentQuestion.value.expires_at))
const canAnswer = computed(() => detail.value?.allowed_actions.includes('ANSWER') && currentQuestion.value?.question_id && !questionExpired.value)
const canAppend = computed(() => detail.value?.allowed_actions.includes('APPEND_EVIDENCE'))
const sourceMaterial = computed(() => detail.value?.materials.filter(m => !m.question_id) ?? [])
const query = ref('')
const filteredApplications = computed(() => applications.value.filter(item =>
  `${item.case_id} ${item.order_id ?? ''} ${item.description ?? ''} ${productLines.value[item.line_id]?.product_name ?? ''} ${productLines.value[item.line_id]?.merchant_name ?? ''}`.toLowerCase().includes(query.value.trim().toLowerCase())))
function valid(g: number, token: string) { return alive && g === generation && props.account.access_token === token }
function failure(cause: unknown) {
  if (cause instanceof ApiError) {
    if (cause.status === 401) { emit('expired'); return }
    error.value = cause.status === 404 ? '未找到该申请或订单，或当前账号无权查看。' : cause.status === 403 ? '当前账号无权执行此操作。'
      : cause.status === 409 ? '申请状态已更新，请刷新后核对，再确认操作。' : cause.message
  } else error.value = '连接暂时中断，请重试读取；写入结果未确认时请先核对进展。'
}
function rememberDraft() {
  if (detailId.value) drafts.set(detailId.value, { material: materialText.value, answer: answerText.value, uncertain: uncertainMaterial.value, ids: uncertainMaterialIds.value })
}
function resetPage() {
  rememberDraft(); detail.value = null; detailLine.value = null; detailId.value = ''
  error.value = ''; notice.value = ''; cancelOpen.value = false
  materialText.value = ''; answerText.value = ''; uncertainMaterial.value = false; uncertainMaterialIds.value = []
}
function routeHash() {
  const line = window.location.hash.match(/^#\/customer\/apply\/([^/]+)$/)
  if (line) { try { return { screen: 'apply' as Screen, id: decodeURIComponent(line[1]) } } catch { /* Invalid path falls back to owned list. */ } }
  const match = window.location.hash.match(/^#\/customer\/applications\/([^/]+)$/)
  if (match) { try { return { screen: 'detail' as Screen, id: decodeURIComponent(match[1]) } } catch { /* Invalid path falls back to owned list. */ } }
  return { screen: window.location.hash === '#/customer/applications' ? 'applications' as Screen : 'orders' as Screen, id: '' }
}
function navigate(target: Screen, id = '') {
  if (writing.value || createUncertain.value) { error.value = '请先确认本次申请提交结果，再离开申请表。'; return }
  const hash = target === 'detail' ? `#/customer/applications/${encodeURIComponent(id)}`
    : target === 'applications' ? '#/customer/applications' : '#/customer/orders'
  window.history.pushState(null, '', hash)
  void show(target, id)
}
function browserNavigation() {
  if (writing.value || createUncertain.value) return
  const route = routeHash(); void show(route.screen, route.id)
}
async function show(target: Screen, id = '') {
  const g = ++generation; resetPage(); screen.value = target; loading.value = true
  try {
    if (target === 'detail') { detailId.value = id; const draft = drafts.get(id)
      if (draft) { materialText.value = draft.material; answerText.value = draft.answer; uncertainMaterial.value = draft.uncertain; uncertainMaterialIds.value = draft.ids }
      await readDetail()
    } else if (target === 'apply') {
      const token = props.account.access_token; await readEligibility(id, g)
      if (!valid(g, token)) return
      const context = eligibility.value[id]
      if (context?.can_apply) { selectedLine.value = context; description.value = ''; initialMaterial.value = ''; pendingCreate = null }
      else if (context?.application) navigate('detail', context.application.case_id)
      else { screen.value = 'orders'; error.value = context?.blocked_reason || '当前订单行不能申请售后，请重新读取资格。' }
    } else if (target === 'applications') await loadApplications()
    else if (target === 'orders') await loadOrders()
  } finally { if (alive && g === generation) loading.value = false }
}
async function readEligibility(lineId: string, g = generation) {
  const token = props.account.access_token
  try {
    const result = await coreApi.customerOrderLine(token, lineId)
    if (!valid(g, token)) return
    eligibility.value[lineId] = result; delete eligibilityErrors.value[lineId]
  } catch (cause) {
    if (!valid(g, token)) return
    eligibility.value[lineId] = null; eligibilityErrors.value[lineId] = '申请资格暂未读取，请重试'
    if (cause instanceof ApiError && cause.status === 401) failure(cause)
  }
}
async function loadOrders(cursor?: string) {
  const g = generation, token = props.account.access_token
  try {
    const page = await coreApi.orders(token, cursor)
    if (!valid(g, token)) return
    orders.value = cursor ? [...orders.value, ...page.items] : page.items; orderCursor.value = page.page.next_cursor
    // Small bounded groups avoid issuing two downstream reads per line all at once.
    for (let i = 0; i < page.items.length && valid(g, token); i += 4)
      await Promise.all(page.items.slice(i, i + 4).map(line => readEligibility(line.line_id, g)))
  } catch (cause) { if (valid(g, token)) failure(cause) }
}
async function loadApplications(cursor?: string) {
  const g = generation, token = props.account.access_token, view = filter.value
  try {
    const page = await coreApi.customerCases(token, view, cursor)
    if (!valid(g, token) || filter.value !== view) return
    applications.value = cursor ? [...applications.value, ...page.items] : page.items; applicationCursor.value = page.page.next_cursor
    applicationExpanded = !!cursor; applicationUpdate.value = ''
    void products.readMany(page.items.map(item => item.line_id), true)
  } catch (cause) { if (valid(g, token)) failure(cause) }
}
async function readDetail() {
  const g = generation, token = props.account.access_token, id = detailId.value
  if (!id) return
  try {
    const result = await coreApi.customerCase(token, id)
    if (!valid(g, token) || detailId.value !== id || screen.value !== 'detail') return
    if (!detail.value || result.case.version >= detail.value.case.version) detail.value = result
    if (uncertainMaterial.value && result.materials.some(m => !uncertainMaterialIds.value.includes(m.id) && m.text === materialText.value.trim())) {
      uncertainMaterial.value = false; materialText.value = ''; notice.value = '已核对：材料已保存。'
    }
    if (!detailLine.value) {
      void coreApi.customerOrderLine(token, result.case.line_id).then(line => {
        if (valid(g, token) && detailId.value === id) detailLine.value = line.order_line
      }).catch(() => { /* The application remains readable when Commerce is temporarily unavailable. */ })
    }
  } catch (cause) { if (valid(g, token)) failure(cause) }
}
async function pollApplications() {
  const g = generation, token = props.account.access_token, view = filter.value
  loading.value = true
  try {
    const page = await coreApi.customerCases(token, view)
    if (!valid(g, token) || screen.value !== 'applications' || view !== filter.value) return
    if (applicationExpanded) {
      if (JSON.stringify(applications.value.slice(0, page.items.length)) !== JSON.stringify(page.items))
        applicationUpdate.value = '申请进展有更新；点击刷新查看，已展开记录保持不变。'
    } else { applications.value = page.items; applicationCursor.value = page.page.next_cursor; applicationUpdate.value = ''; void products.readMany(page.items.map(item => item.line_id)) }
  } catch (cause) { if (valid(g, token)) failure(cause) }
  finally { if (valid(g, token)) loading.value = false }
}
async function refresh() {
  if (writing.value || loading.value) return
  error.value = ''; loading.value = true
  const g = screen.value === 'detail' ? generation : ++generation
  try {
    if (screen.value === 'detail') await readDetail()
    else if (screen.value === 'applications') await loadApplications()
    else await loadOrders()
  } finally { if (alive && generation === g) loading.value = false }
}
async function more(kind: 'orders' | 'applications') {
  if (loading.value || writing.value) return
  const cursor = kind === 'orders' ? orderCursor.value : applicationCursor.value
  if (!cursor) return
  const g = generation; loading.value = true
  try { if (kind === 'orders') await loadOrders(cursor); else await loadApplications(cursor) }
  finally { if (alive && generation === g) loading.value = false }
}
async function changeFilter() { query.value = ''; applications.value = []; applicationCursor.value = null; await refresh() }
async function apply(lineId: string) {
  if (writing.value || loading.value || createUncertain.value) return
  const g = generation, token = props.account.access_token
  loading.value = true; await readEligibility(lineId)
  if (!valid(g, token)) return
  loading.value = false
  const context = eligibility.value[lineId]
  if (!context) return
  if (!context.can_apply) { if (context.application) navigate('detail', context.application.case_id); return }
  ++generation; resetPage(); selectedLine.value = context; screen.value = 'apply'
  description.value = ''; initialMaterial.value = ''; pendingCreate = null
}
async function create() {
  if (writing.value || !selectedLine.value || !description.value.trim()) return
  const g = generation, token = props.account.access_token
  pendingCreate ??= { key: crypto.randomUUID(), line: selectedLine.value.order_line.line_id,
    description: description.value.trim(), material: initialMaterial.value.trim() }
  const request = pendingCreate
  writing.value = true; error.value = ''; notice.value = ''
  try {
    const created = await coreApi.createCase(token, request.line, request.description, request.key)
    if (!valid(g, token)) return
    pendingCreate = null; createUncertain.value = false
    resetPage(); screen.value = 'detail'; detailId.value = created.case_id
    window.history.replaceState(null, '', `#/customer/applications/${encodeURIComponent(created.case_id)}`)
    notice.value = '申请已创建。'
    await readDetail()
    if (request.material) {
      materialText.value = request.material
      await saveMaterial(true)
    }
  } catch (cause) {
    if (!valid(g, token)) return
    if (cause instanceof ApiError && cause.status < 500) {
      pendingCreate = null; createUncertain.value = false; failure(cause)
      if (cause.status === 409) await readEligibility(request.line)
    } else { createUncertain.value = true; error.value = '提交结果尚未确认。说明与幂等键已保留；点击“确认提交结果”读取原提交结果，勿重新申请。' }
  } finally { if (valid(g, token)) writing.value = false }
}
async function answer() {
  if (writing.value || !canAnswer.value || !detail.value || !currentQuestion.value?.question_id || !answerText.value.trim()) return
  const g = generation, token = props.account.access_token, before = detail.value, text = answerText.value.trim()
  const questionId = currentQuestion.value.question_id
  writing.value = true; error.value = ''; notice.value = ''
  try {
    const result = await coreApi.answerQuestion(token, before, questionId, text)
    if (!valid(g, token)) return
    detail.value = result; answerText.value = ''; notice.value = '回答已保存，正在重新调查；历史问题和原始申请均已保留。'
  } catch (cause) {
    if (!valid(g, token)) return
    await readDetail()
    const saved = detail.value?.questions.find(q => q.question_id === questionId)?.answers.some(a => a.text === text)
    if (saved && detail.value!.case.version > before.case.version) { answerText.value = ''; notice.value = '已核对：回答已保存，等待新调查。' }
    else failure(cause)
  } finally { if (valid(g, token)) writing.value = false }
}
async function saveMaterial(initial = false) {
  if (!detail.value || !materialText.value.trim() || uncertainMaterial.value || (!initial && writing.value)) return
  const g = generation, token = props.account.access_token, id = detailId.value, text = materialText.value.trim()
  const previousIds = new Set(detail.value.materials.map(m => m.id))
  writing.value = true; error.value = ''
  try {
    await coreApi.appendEvidence(token, id, text)
    if (!valid(g, token)) return
    materialText.value = ''; notice.value = initial ? '申请及初始材料均已保存。' : '材料已保存，等待新的调查结果。'
    await readDetail()
  } catch (cause) {
    if (!valid(g, token)) return
    await readDetail()
    if (detail.value?.materials.some(m => !previousIds.has(m.id) && m.text === text)) {
      materialText.value = ''; notice.value = '已核对：材料已保存。'
    } else if (cause instanceof ApiError && cause.status < 500) {
      failure(cause); if (initial) notice.value = '申请已创建；初始材料未保存。文本已保留，仅重试材料即可。'
    } else { uncertainMaterial.value = true; uncertainMaterialIds.value = [...previousIds]; error.value = '材料保存结果尚未确认，文本已保留。请刷新并核对记录，避免重复提交。' }
  } finally { if (valid(g, token)) writing.value = false }
}
async function cancel() {
  if (writing.value || !cancelReason.value.trim() || !detail.value?.allowed_actions.includes('CANCEL')) return
  const g = generation, token = props.account.access_token, id = detailId.value
  writing.value = true; error.value = ''
  try {
    await coreApi.cancelCase(token, id, cancelReason.value.trim())
    if (!valid(g, token)) return
    cancelOpen.value = false; cancelReason.value = ''; notice.value = '申请已撤销。'; await readDetail()
  } catch (cause) {
    if (!valid(g, token)) return
    await readDetail()
    if (detail.value?.case.status === 'CANCELLED') { cancelOpen.value = false; notice.value = '已核对：申请已撤销。' }
    else { cancelOpen.value = false; failure(cause) }
  } finally { if (valid(g, token)) writing.value = false }
}
onMounted(() => {
  const route = routeHash(); void show(route.screen, route.id)
  window.addEventListener('popstate', browserNavigation); window.addEventListener('hashchange', browserNavigation)
  timer = setInterval(() => {
    now.value = Date.now()
    if (!writing.value && !loading.value && !document.hidden && screen.value === 'detail' && detail.value && !terminal(detail.value.case.status)) void readDetail()
    if (!writing.value && !loading.value && !document.hidden && screen.value === 'applications') void pollApplications()
  }, 15000)
})
onBeforeUnmount(() => {
  alive = false; ++generation; products.reset(); clearInterval(timer); drafts.clear(); pendingCreate = null
  window.removeEventListener('popstate', browserNavigation); window.removeEventListener('hashchange', browserNavigation)
})
</script>

<template>
  <div class="app-shell customer-shell" :class="{ 'customer-buyer': account.buyer_id }">
    <nav v-if="!account.buyer_id" class="sidebar" aria-label="客户工作台导航">
      <a href="#/customer/orders" data-test="nav-orders" class="nav-link" :class="{ current: ['orders', 'apply'].includes(screen) }" @click.prevent="navigate('orders')"><Icon name="box" />我的订单</a>
      <a href="#/customer/applications" data-test="nav-applications" class="nav-link" :class="{ current: ['applications', 'detail'].includes(screen) }" @click.prevent="navigate('applications')"><Icon name="file" />我的申请</a>
    </nav>
    <main class="customer-main" :aria-busy="loading || writing">
      <header class="customer-heading"><div><h1>{{ screen === 'orders' ? '我的订单' : screen === 'applications' ? '我的售后' : screen === 'apply' ? '申请退款' : '售后详情' }}</h1><p class="muted">{{ account.buyer_id ? '跨店售后服务' : `${account.merchant_name || account.merchant_id} · 客户服务` }}</p></div><button v-if="screen !== 'apply'" class="secondary-button" type="button" :disabled="writing || loading" @click="refresh"><Icon name="clock" :size="18" />刷新</button></header>
      <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message success" role="status"><Icon name="check" />{{ notice }}</p>
      <section v-if="screen === 'orders'" aria-label="我的订单">
        <div v-if="!orders.length" class="panel customer-empty"><Icon name="box" :size="36" /><h3>{{ loading ? '正在读取订单…' : '暂无订单' }}</h3><p>当前账号还没有可查看的订单。</p></div>
        <div v-else class="customer-card-list">
          <article v-for="line in orders" :key="line.line_id" class="panel customer-list-card">
            <div><AftercareProduct :line="line" /><details class="customer-order-record"><summary>订单记录</summary><p>{{ line.sku }} · {{ line.order_id }}</p><time v-if="line.paid_at" data-test="order-paid-at">支付于 {{ formatTime(line.paid_at) }}</time></details></div>
            <div class="customer-list-status"><span v-if="eligibility[line.line_id]?.application" class="status-tag" :class="{ success: eligibility[line.line_id]?.application?.status === 'CLOSED_SUCCESS' }">{{ status(eligibility[line.line_id]!.application!.status) }}</span><span v-else class="muted">{{ eligibilityErrors[line.line_id] || (eligibility[line.line_id] ? '暂无申请' : '正在核对…') }}</span><p v-if="eligibility[line.line_id]?.blocked_reason">{{ eligibility[line.line_id]?.blocked_reason }}</p></div>
            <div class="customer-list-actions"><button v-if="eligibility[line.line_id]?.application && !eligibility[line.line_id]?.can_apply" type="button" class="secondary-button" @click="navigate('detail', eligibility[line.line_id]!.application!.case_id)">查看申请</button><button v-else-if="eligibility[line.line_id]?.can_apply" :data-test="`apply-${line.line_id}`" type="button" :disabled="writing || loading" @click="apply(line.line_id)">申请退款</button><button v-else-if="eligibilityErrors[line.line_id]" type="button" class="text-button" @click="readEligibility(line.line_id)">重试读取</button><button v-if="eligibility[line.line_id]?.application && eligibility[line.line_id]?.can_apply" type="button" class="text-button" @click="navigate('detail', eligibility[line.line_id]!.application!.case_id)">查看上次申请</button></div>
          </article>
        </div>
        <div v-if="orderCursor" class="customer-pagination"><button type="button" class="secondary-button" :disabled="loading || writing" @click="more('orders')">加载更多订单</button></div>
      </section>
      <section v-else-if="screen === 'applications'" data-test="applications-list" aria-label="我的申请">
        <div class="customer-filters"><select v-model="filter" aria-label="处理阶段" :disabled="loading" @change="changeFilter"><option value="ALL">全部申请</option><option value="WAITING">待补充说明</option><option value="PROCESSING">调查与退款处理中</option><option value="REVIEW">等待商家审核</option><option value="CLOSED">已结束</option></select><input v-model="query" aria-label="查找已加载申请" placeholder="搜索已加载商品或申请" /></div>
        <div v-if="!filteredApplications.length" class="panel customer-empty"><Icon name="file" :size="36" /><h3>{{ loading ? '正在读取申请…' : '暂无符合条件的申请' }}</h3><button type="button" class="secondary-button" @click="navigate('orders')">查看我的订单</button></div>
        <div v-else class="customer-card-list">
          <article v-for="item in filteredApplications" :key="item.case_id" class="panel customer-list-card">
            <div class="customer-list-product"><AftercareProduct :line="productLines[item.line_id]" :loading="productStates[item.line_id] === 'loading'" :unavailable="productStates[item.line_id] === 'unavailable'" /><p class="customer-list-description">{{ item.description || '退款申请' }}</p><button v-if="productStates[item.line_id] === 'unavailable'" type="button" class="text-button" @click="products.read(item.line_id, true)">重试商品资料</button></div>
            <div class="customer-list-status"><span class="status-tag" :class="{ waiting: item.status === 'WAITING_CUSTOMER', success: item.status === 'CLOSED_SUCCESS' }">{{ status(item.status) }}</span><time>{{ formatTime(item.updated_at) }}</time></div>
            <button type="button" class="secondary-button" @click="navigate('detail', item.case_id)">{{ item.status === 'WAITING_CUSTOMER' ? '补充说明' : '查看详情' }}</button>
          </article>
        </div>
        <p v-if="applicationUpdate" class="admin-note" role="status">{{ applicationUpdate }}</p>
        <div v-if="applicationCursor" class="customer-pagination"><button type="button" class="secondary-button" :disabled="loading" @click="more('applications')">加载更多申请</button></div>
      </section>
      <form v-else-if="screen === 'apply' && selectedLine" class="customer-apply" @submit.prevent="create">
        <button class="text-button customer-back" type="button" :disabled="writing || createUncertain" @click="navigate('orders')">← 返回我的订单</button>
        <div class="customer-detail-grid">
          <section class="panel"><h2>确认申请订单</h2><AftercareProduct :line="selectedLine.order_line" :show-amount="false" />
            <label>情况说明 <span class="customer-required">必填</span><textarea v-model="description" data-test="application-description" rows="5" maxlength="4000" :readonly="writing || createUncertain" placeholder="请说明退款原因和已经尝试的处理方式" /></label>
            <label>文本材料 <span class="muted">可选</span><textarea v-model="initialMaterial" data-test="initial-material" rows="3" maxlength="8000" :readonly="writing || createUncertain" placeholder="可粘贴物流反馈或其他文字说明" /></label>
          </section>
          <aside class="panel customer-apply-summary"><h2>退款金额</h2><strong class="customer-amount">{{ formatMinorUnits(selectedLine.order_line.line_paid_amount, selectedLine.order_line.currency) }}</strong><p>单个订单行全额模拟退款，由商家审核。</p><button data-test="create-case" type="submit" :disabled="writing || !description.trim()">{{ writing ? '正在提交…' : createUncertain ? '确认提交结果' : '提交退款申请' }}</button></aside>
        </div>
      </form>
      <template v-else-if="screen === 'detail'">
        <button type="button" class="text-button customer-back" :disabled="writing" @click="navigate('applications')">← 返回我的售后</button>
        <div v-if="!detail" class="panel customer-empty"><h3>{{ loading ? '正在读取申请…' : '暂时无法查看申请' }}</h3><p>请点击刷新重试。</p></div>
        <div v-else data-test="application-detail" class="customer-detail-grid">
          <div class="customer-detail-content">
            <section class="panel customer-result" aria-label="申请当前进展"><span class="customer-result-icon"><Icon :name="detail.case.status === 'CLOSED_SUCCESS' ? 'check' : terminal(detail.case.status) ? 'file' : 'clock'" :size="25" /></span><div><span class="status-tag" :class="{ success: detail.case.status === 'CLOSED_SUCCESS', waiting: detail.case.status === 'WAITING_CUSTOMER' }">{{ status(detail.case.status) }}</span><h2>{{ detail.result.message }}</h2><p v-if="detail.result.public_reason">{{ detail.result.public_reason }}</p><p v-if="detail.result.amount_minor !== null">{{ detail.case.status === 'CLOSED_SUCCESS' ? '模拟退款金额' : '本次批准金额' }}：<b>{{ formatMinorUnits(detail.result.amount_minor, detail.result.currency) }}</b></p><p v-if="detail.blocked_reason" class="customer-inline-note">{{ detail.blocked_reason }}</p></div></section>
            <section class="panel" aria-label="申请商品"><AftercareProduct :line="detailLine" :loading="!detailLine && loading" :unavailable="!detailLine && !loading" /><button v-if="!detailLine && !loading" class="text-button" type="button" @click="readDetail">重试商品资料</button></section>
            <section class="panel" aria-label="原始申请"><div class="customer-section-heading"><h2>原始申请</h2></div><p class="customer-text-block">{{ detail.case.description || '原始说明未提供' }}</p></section>
            <section v-if="currentQuestion" class="panel customer-questions" aria-label="当前补证问题">
              <h2>需要您补充说明</h2><p v-for="(prompt, i) in currentQuestion.prompts" :key="i" class="customer-text-block">{{ prompt }}</p><p v-if="!currentQuestion.prompts.length" class="muted">问题正文未提供，当前无法回答。</p><p class="customer-inline-note">回答截止 {{ formatTime(currentQuestion.expires_at) }}</p>
              <form v-if="canAnswer" @submit.prevent="answer"><label>您的回答<textarea v-model="answerText" data-test="answer-text" rows="4" maxlength="8000" :disabled="writing" placeholder="请针对当前问题补充说明" /></label><div class="customer-form-footer"><button type="submit" data-test="submit-answer" :disabled="writing || !answerText.trim()">{{ writing ? '正在保存…' : '提交回答' }}</button></div></form>
              <p v-else-if="questionExpired" class="customer-info">补证期限已过，请等待商家继续处理。</p>
            </section>
            <details v-if="previousQuestions.length" class="panel customer-history"><summary>历史补充问题与回答（{{ previousQuestions.length }}）</summary><article v-for="(question, index) in previousQuestions" :key="question.question_id || index" class="customer-question"><h3>{{ question.status === 'ANSWERED' ? '已回答' : question.status === 'EXPIRED' ? '已过期' : '已结束' }}</h3><p v-for="(prompt, i) in question.prompts" :key="i" class="customer-text-block">{{ prompt }}</p><p v-if="question.status === 'EXPIRED'" class="customer-info">补证期限已过，请等待商家继续处理。</p><p class="customer-inline-note">提出于 {{ formatTime(question.asked_at) }}</p><div v-for="material in question.answers" :key="material.id" class="customer-answer"><strong>我的回答</strong><p class="customer-text-block">{{ material.text }}</p></div></article></details>
            <section v-if="sourceMaterial.length || canAppend || materialText" class="panel" aria-label="我的文本材料"><h2>文本材料</h2><details v-for="material in sourceMaterial" :key="material.id" class="customer-material"><summary><Icon name="file" /><span>{{ material.text?.slice(0, 70) || '文本材料' }}</span></summary><p class="customer-text-block">{{ material.text }}</p><p class="muted">{{ material.verification_result === 'CONFIRMED' ? '人工核验：确认' : material.verification_result === 'REFUTED' ? '人工核验：不成立' : material.verification_result === 'INCONCLUSIVE' ? '人工核验：无法判定' : '客户陈述 · 尚未核验' }} · {{ formatTime(material.submitted_at) }}</p></details>
              <form v-if="canAppend" class="customer-material-form" @submit.prevent="saveMaterial()"><label>追加文本材料<textarea v-model="materialText" data-test="material-text" rows="3" maxlength="8000" :disabled="writing || uncertainMaterial" placeholder="补充新的文字说明，保存后重新调查" /></label><p v-if="uncertainMaterial" class="customer-info">保存结果待确认，请刷新核对已提交记录。当前禁止再次提交同一文本。</p><div class="customer-form-footer"><button data-test="append-evidence" type="submit" :disabled="writing || uncertainMaterial || !materialText.trim()">{{ writing ? '正在保存…' : '提交材料' }}</button></div></form><p v-else-if="materialText" class="customer-info">未保存的文本仍在本登录会话保留；当前状态不允许追加。</p>
            </section>
          </div>
          <aside class="customer-detail-aside">
            <section class="panel" aria-label="公开处理进度"><h2>处理进度</h2><p v-if="!detail.timeline.length" class="muted">暂无进度记录。</p><ol class="customer-timeline"><li v-for="(event, index) in detail.timeline.slice(-3)" :key="index"><strong>{{ event.summary }}</strong><time>{{ formatTime(event.occurred_at) }}</time></li></ol><details v-if="detail.timeline.length > 3" class="customer-history"><summary>全部处理记录</summary><ol class="customer-timeline"><li v-for="(event, index) in detail.timeline" :key="index"><strong>{{ event.summary }}</strong><time>{{ formatTime(event.occurred_at) }}</time></li></ol></details></section>
            <section class="panel"><h2>申请操作</h2><a class="text-button" href="#/shop/orders">查看我的订单 →</a><button v-if="detail.allowed_actions.includes('CANCEL')" data-test="cancel-case" class="danger-button" type="button" :disabled="writing" @click="cancelOpen = true; cancelReason = ''">撤销申请</button><details class="customer-history customer-identifiers"><summary>申请与订单编号</summary><dl class="customer-facts"><dt>申请号</dt><dd>{{ detail.case.case_id }}</dd><dt>订单号</dt><dd>{{ detail.case.order_id || '未提供' }}</dd><dt>提交时间</dt><dd>{{ formatTime(detail.case.created_at) }}</dd><dt v-if="detailLine?.paid_at">支付时间</dt><dd v-if="detailLine?.paid_at">{{ formatTime(detailLine.paid_at) }}</dd></dl></details></section>
          </aside>
        </div>
      </template>
    </main>
    <ReviewDialog v-if="cancelOpen" title="确认撤销申请" workspace="客户工作台" :busy="writing" @close="cancelOpen = false"><p>撤销后本次申请结束，已提交记录仍可查看。</p><label>撤销原因<textarea v-model="cancelReason" rows="3" maxlength="1000" :disabled="writing" placeholder="请说明撤销原因" /></label><div class="customer-form-footer"><button type="button" class="secondary-button" :disabled="writing" @click="cancelOpen = false">继续申请</button><button type="button" class="danger-button" data-test="confirm-cancel" :disabled="writing || !cancelReason.trim()" @click="cancel">确认撤销</button></div></ReviewDialog>
  </div>
</template>
