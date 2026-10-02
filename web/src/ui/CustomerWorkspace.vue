<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiError, coreApi, type CustomerCaseDetail, type CustomerCaseSummary, type CustomerOrderLine,
  type CustomerView, type LoginResponse, type OrderLine } from '../client'
import { formatMinorUnits } from '../money'
import { paidAtOf, productNameMissing, productTitle, variantOf } from './order-line-format'
import Icon from './ReviewIcon.vue'
import ReviewDialog from './ReviewDialog.vue'
import './customer-workspace.css'

const props = defineProps<{ account: LoginResponse }>()
const emit = defineEmits<{ expired: [] }>()
type Screen = 'orders' | 'applications' | 'apply' | 'detail'
const screen = ref<Screen>('orders'), loading = ref(false), writing = ref(false)
const error = ref(''), notice = ref(''), filter = ref<CustomerView>('ALL')
const orders = ref<OrderLine[]>([]), applications = ref<CustomerCaseSummary[]>([])
const orderCursor = ref<string | null>(), applicationCursor = ref<string | null>()
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
  `${item.case_id} ${item.order_id ?? ''} ${item.description ?? ''}`.toLowerCase().includes(query.value.trim().toLowerCase())))
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
  }, 15000)
})
onBeforeUnmount(() => {
  alive = false; ++generation; clearInterval(timer); drafts.clear(); pendingCreate = null
  window.removeEventListener('popstate', browserNavigation); window.removeEventListener('hashchange', browserNavigation)
})
</script>

<template>
  <div class="app-shell customer-shell">
    <nav class="sidebar" aria-label="客户工作台导航">
      <a href="#/customer/orders" data-test="nav-orders" class="nav-link" :class="{ current: ['orders', 'apply'].includes(screen) }" @click.prevent="navigate('orders')"><Icon name="box" />我的订单</a>
      <a href="#/customer/applications" data-test="nav-applications" class="nav-link" :class="{ current: ['applications', 'detail'].includes(screen) }" @click.prevent="navigate('applications')"><Icon name="file" />我的申请</a>
      <div class="sidebar-note"><p>让售后更简单<br />让每一次服务都有结果</p><small>单订单行 · 全量模拟退款</small><span>© 2026 ResolveFlow</span></div>
    </nav>
    <main class="customer-main" :aria-busy="loading || writing">
      <header class="customer-heading"><div><p class="eyebrow">{{ account.merchant_name || account.merchant_id }} · 客户服务</p><h1>{{ screen === 'orders' ? '我的订单' : screen === 'applications' ? '我的申请' : screen === 'apply' ? '申请退款' : '申请详情' }}</h1><p class="muted">{{ screen === 'orders' ? '查看本人订单，发起与跟踪售后申请' : screen === 'applications' ? '查看申请进展，及时回答商家的补充问题' : '原始信息、补充说明和处理进展都在这里' }}</p></div><button v-if="screen !== 'apply'" class="secondary-button" type="button" :disabled="writing || loading" @click="refresh"><Icon name="clock" :size="16" />刷新</button></header>
      <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message success" role="status"><Icon name="check" />{{ notice }}</p>
      <section v-if="screen === 'orders'" class="panel customer-table-panel" aria-label="我的订单">
        <div class="customer-section-heading"><h2>订单记录</h2><span class="muted">已加载 {{ orders.length }} 条订单行</span></div>
        <div v-if="!orders.length" class="customer-empty"><Icon name="box" :size="36" /><h3>{{ loading ? '正在读取订单…' : '暂无订单' }}</h3><p>当前账号还没有可查看的订单行。</p></div>
        <table v-else class="customer-table"><thead><tr><th>商品 / 订单</th><th>实付金额</th><th>付款状态</th><th>售后状态</th><th>操作</th></tr></thead><tbody>
          <tr v-for="line in orders" :key="line.line_id" class="order-row"><td><div class="customer-product"><span class="customer-product-placeholder" aria-label="商品图片未提供"><Icon name="box" :size="27" /></span><div><strong data-test="order-product" :class="{ 'name-missing': productNameMissing(line) }">{{ productTitle(line) }}</strong><small v-if="variantOf(line)" data-test="order-variant">{{ variantOf(line) }} · 数量 × {{ line.quantity }}</small><small>{{ line.sku }} · 订单 {{ line.order_id }}</small><small v-if="paidAtOf(line)" data-test="order-paid-at">支付于 {{ formatTime(paidAtOf(line)!) }}</small></div></div></td>
            <td><b>{{ formatMinorUnits(line.line_paid_amount, line.currency) }}</b></td><td>{{ line.status === 'PAID' ? '已支付' : line.status }}</td><td><span v-if="eligibility[line.line_id]?.application" class="status-tag" :class="{ success: eligibility[line.line_id]?.application?.status === 'CLOSED_SUCCESS' }">{{ status(eligibility[line.line_id]!.application!.status) }}</span><span v-else class="muted">{{ eligibilityErrors[line.line_id] || (eligibility[line.line_id] ? '暂无申请' : '正在核对…') }}</span><small v-if="eligibility[line.line_id]?.blocked_reason" class="customer-inline-note">{{ eligibility[line.line_id]?.blocked_reason }}</small></td>
            <td><button v-if="eligibility[line.line_id]?.application && !eligibility[line.line_id]?.can_apply" type="button" class="text-button" @click="navigate('detail', eligibility[line.line_id]!.application!.case_id)">查看申请<Icon name="chevron" :size="14" /></button><button v-else-if="eligibility[line.line_id]?.can_apply" :data-test="`apply-${line.line_id}`" type="button" class="secondary-button" :disabled="writing || loading" @click="apply(line.line_id)">申请退款</button><button v-else-if="eligibilityErrors[line.line_id]" type="button" class="text-button" @click="readEligibility(line.line_id)">重试读取</button><span v-else class="muted">{{ eligibility[line.line_id] ? '暂不可申请' : '读取中' }}</span><button v-if="eligibility[line.line_id]?.application && eligibility[line.line_id]?.can_apply" type="button" class="text-button" @click="navigate('detail', eligibility[line.line_id]!.application!.case_id)">查看上次申请</button></td>
          </tr>
        </tbody></table><div class="customer-pagination"><span>仅本人订单 · 金额以订单记录为准</span><button v-if="orderCursor" type="button" class="secondary-button" :disabled="loading || writing" @click="more('orders')">加载更多订单</button></div>
      </section>
      <section v-else-if="screen === 'applications'" data-test="applications-list" class="panel customer-table-panel" aria-label="我的申请">
        <div class="customer-filters"><label>处理阶段<select v-model="filter" :disabled="loading" @change="changeFilter"><option value="ALL">全部申请</option><option value="WAITING">待补充说明</option><option value="PROCESSING">调查与退款处理中</option><option value="REVIEW">等待商家审核</option><option value="CLOSED">已结束</option></select></label><label>当前已加载记录<input v-model="query" aria-label="查找已加载申请" placeholder="申请号、订单号或情况说明" /></label></div>
        <p v-if="filter === 'WAITING'" class="customer-info"><Icon name="file" />请打开申请详情，查看并回答当前问题。</p>
        <div v-if="!filteredApplications.length" class="customer-empty"><Icon name="file" :size="36" /><h3>{{ loading ? '正在读取申请…' : '暂无符合条件的申请' }}</h3><p>可以切换处理阶段、加载更多，或从我的订单发起申请。</p><button type="button" class="secondary-button" @click="navigate('orders')">查看我的订单</button></div>
        <table v-else class="customer-table"><thead><tr><th>申请 / 情况说明</th><th>订单</th><th>当前状态</th><th>更新时间</th><th>操作</th></tr></thead><tbody><tr v-for="item in filteredApplications" :key="item.case_id"><td><strong>{{ item.description || '退款申请' }}</strong><small class="customer-id">{{ item.case_id }}</small></td><td><span class="customer-id">{{ item.order_id || '订单编号未提供' }}</span><small class="customer-inline-note">订单行 {{ item.line_id }}</small></td><td><span class="status-tag" :class="{ waiting: item.status === 'WAITING_CUSTOMER', success: item.status === 'CLOSED_SUCCESS' }">{{ status(item.status) }}</span></td><td>{{ formatTime(item.updated_at) }}</td><td><button type="button" class="text-button" @click="navigate('detail', item.case_id)">{{ item.status === 'WAITING_CUSTOMER' ? '查看问题并回答' : '查看详情' }}<Icon name="chevron" :size="14" /></button></td></tr></tbody></table>
        <div class="customer-pagination"><span>已加载 {{ applications.length }} 条 · 筛选由服务器执行，文本查找仅限已加载记录</span><button v-if="applicationCursor" type="button" class="secondary-button" :disabled="loading" @click="more('applications')">加载更多申请</button></div>
      </section>
      <form v-else-if="screen === 'apply' && selectedLine" class="panel customer-apply" @submit.prevent="create">
        <button class="text-button" type="button" :disabled="writing || createUncertain" @click="navigate('orders')">← 返回我的订单</button>
        <h2>确认申请订单</h2><div class="customer-product customer-order-summary"><span class="customer-product-placeholder" aria-label="商品图片未提供"><Icon name="box" :size="30" /></span><div><strong>{{ productTitle(selectedLine.order_line) }}</strong><small>{{ variantOf(selectedLine.order_line) }} · 数量 × {{ selectedLine.order_line.quantity }}</small><small>订单 {{ selectedLine.order_line.order_id }}</small></div><b>{{ formatMinorUnits(selectedLine.order_line.line_paid_amount, selectedLine.order_line.currency) }}</b></div>
        <div class="customer-info"><Icon name="shield" /><span>申请单个订单行全额模拟退款。实际结果由商家审核和模拟执行确认。</span></div>
        <label>情况说明 <span class="customer-required">必填</span><textarea v-model="description" data-test="application-description" rows="5" maxlength="4000" :readonly="writing || createUncertain" placeholder="请说明遇到的问题，例如商品损坏、物流异常，以及已尝试的处理方式" /></label><small class="customer-inline-note">{{ description.length }} / 4000</small>
        <label>初始文本材料 <span class="muted">可选</span><textarea v-model="initialMaterial" data-test="initial-material" rows="3" maxlength="8000" :readonly="writing || createUncertain" placeholder="可粘贴物流反馈或其他文字说明。本项目暂不支持图片、视频上传" /></label>
        <div class="customer-form-footer"><span>申请金额 <b>{{ formatMinorUnits(selectedLine.order_line.line_paid_amount, selectedLine.order_line.currency) }}</b></span><button data-test="create-case" type="submit" :disabled="writing || !description.trim()">{{ writing ? '正在提交…' : createUncertain ? '确认提交结果' : '提交退款申请' }}<Icon name="arrow" :size="17" /></button></div>
      </form>
      <template v-else-if="screen === 'detail'">
        <button type="button" class="text-button customer-back" :disabled="writing" @click="navigate('applications')">← 返回我的申请</button>
        <div v-if="!detail" class="panel customer-empty"><Icon name="file" :size="36" /><h3>{{ loading ? '正在读取申请…' : '暂时无法查看申请' }}</h3><p>请确认账号和访问权限，或点击刷新重试。</p></div>
        <div v-else data-test="application-detail" class="customer-detail-grid">
          <div class="customer-detail-content">
            <section class="panel customer-result" aria-label="申请当前进展"><span class="customer-result-icon"><Icon :name="detail.case.status === 'CLOSED_SUCCESS' ? 'check' : terminal(detail.case.status) ? 'file' : 'clock'" :size="25" /></span><div><span class="status-tag" :class="{ success: detail.case.status === 'CLOSED_SUCCESS', waiting: detail.case.status === 'WAITING_CUSTOMER' }">{{ status(detail.case.status) }}</span><h2>{{ detail.result.message }}</h2><p v-if="detail.result.public_reason">处理说明：{{ detail.result.public_reason }}</p><p v-if="detail.result.amount_minor !== null">{{ detail.case.status === 'CLOSED_SUCCESS' ? '模拟退款金额' : '本次批准金额' }}：<b>{{ formatMinorUnits(detail.result.amount_minor, detail.result.currency) }}</b></p><p class="muted">模拟退款演示，不涉及真实资金。处理可能因新材料重新调查。</p><p v-if="detail.blocked_reason" class="customer-inline-note">{{ detail.blocked_reason }}</p></div></section>
            <section class="panel" aria-label="原始申请"><div class="customer-section-heading"><h2>原始申请</h2><time class="muted">{{ formatTime(detail.case.created_at) }}</time></div><p class="customer-text-block">{{ detail.case.description || '原始说明未提供' }}</p><div class="customer-meta"><span>申请号 {{ detail.case.case_id }}</span><span>订单 {{ detail.case.order_id || '编号未提供' }}</span></div></section>
            <section v-if="detail.questions.length" class="panel customer-questions" aria-label="补证问题与回答历史">
              <div class="customer-section-heading"><h2>补充问题与回答</h2><span class="muted">已发出 {{ detail.questions.length }} / 2 轮问题</span></div>
              <article v-for="(question, index) in detail.questions" :key="question.question_id || index" class="customer-question" :class="{ pending: question === currentQuestion }"><div class="customer-section-heading"><h3>第 {{ index + 1 }} 轮补充说明</h3><span class="muted">{{ question.status === 'ANSWERED' ? '已回答' : question.status === 'PENDING' && !questionExpired ? '待回答' : question.status === 'EXPIRED' || (question === currentQuestion && questionExpired) ? '已过期' : question.status === 'UNAVAILABLE' ? '问题记录不完整' : '已结束' }}</span></div><p v-for="(prompt, i) in question.prompts" :key="i" class="customer-text-block">{{ prompt }}</p><p v-if="!question.prompts.length" class="muted">历史问题正文未提供，当前无法回答。</p><small class="customer-inline-note">提出于 {{ formatTime(question.asked_at) }} · 回答截止 {{ formatTime(question.expires_at) }}</small><div v-for="material in question.answers" :key="material.id" class="customer-answer"><strong>我的回答</strong><p class="customer-text-block">{{ material.text }}</p><small>{{ formatTime(material.submitted_at) }}</small></div></article>
              <form v-if="canAnswer" @submit.prevent="answer"><label>回答当前问题<textarea v-model="answerText" data-test="answer-text" rows="4" maxlength="8000" :disabled="writing" placeholder="请针对上方当前问题补充说明" /></label><div class="customer-form-footer"><span class="muted">提交后重新调查，原始记录保留</span><button type="submit" data-test="submit-answer" :disabled="writing || !answerText.trim()">{{ writing ? '正在保存…' : '提交回答' }}</button></div></form>
              <p v-else-if="questionExpired || detail.questions.some(q => q.status === 'EXPIRED')" class="customer-info">补证期限已过，请等待商家继续处理。</p>
            </section>
            <section class="panel" aria-label="我的文本材料"><div class="customer-section-heading"><h2>已提交文本材料</h2><span class="muted">{{ sourceMaterial.length }} 条</span></div><p v-if="!sourceMaterial.length" class="muted">尚未单独提交文本材料，原始情况说明仍保留在上方。</p><details v-for="material in sourceMaterial" :key="material.id" class="customer-material"><summary><Icon name="file" /><span>{{ material.text?.slice(0, 70) || '文本材料' }}</span><span class="muted">{{ material.verification_result === 'CONFIRMED' ? '人工核验：确认' : material.verification_result === 'REFUTED' ? '人工核验：不成立' : material.verification_result === 'INCONCLUSIVE' ? '人工核验：无法判定' : '客户陈述 · 尚未核验' }}</span></summary><p class="customer-text-block">{{ material.text }}</p><small class="muted">提交于 {{ formatTime(material.submitted_at) }}</small></details>
              <form v-if="canAppend" class="customer-material-form" @submit.prevent="saveMaterial()"><label>追加文本材料<textarea v-model="materialText" data-test="material-text" rows="3" maxlength="8000" :disabled="writing || uncertainMaterial" placeholder="补充新的文字说明，保存后将重新调查" /></label><p v-if="uncertainMaterial" class="customer-info">保存结果待确认，请刷新核对已提交记录。当前禁止再次提交同一文本。</p><div class="customer-form-footer"><span class="muted">文本属于客户陈述，核验结论由商家记录</span><button data-test="append-evidence" type="submit" :disabled="writing || uncertainMaterial || !materialText.trim()">{{ writing ? '正在保存…' : '提交材料' }}</button></div></form>
              <p v-else-if="materialText" class="customer-info">未保存的文本仍在本登录会话保留；当前状态不允许追加。</p>
            </section>
          </div>
          <aside class="customer-detail-aside">
            <section class="panel" aria-label="申请订单"><h2>订单信息</h2><div v-if="detailLine" class="customer-product customer-detail-product"><span class="customer-product-placeholder" aria-label="商品图片未提供"><Icon name="box" :size="28" /></span><div><strong>{{ productTitle(detailLine) }}</strong><small>{{ variantOf(detailLine) }} · 数量 × {{ detailLine.quantity }}</small><small>{{ detailLine.sku }}</small></div></div><p v-else class="muted">订单展示资料暂不可用，申请记录仍可查看。</p><dl v-if="detailLine" class="customer-facts"><dt>订单实付</dt><dd>{{ formatMinorUnits(detailLine.line_paid_amount, detailLine.currency) }}</dd><dt>支付时间</dt><dd>{{ detailLine.paid_at ? formatTime(detailLine.paid_at) : '未提供' }}</dd></dl></section>
            <section class="panel" aria-label="公开处理进度"><h2>处理进度</h2><p v-if="!detail.timeline.length" class="muted">暂无进度记录。</p><ol class="customer-timeline"><li v-for="(event, index) in detail.timeline" :key="index"><strong>{{ event.summary }}</strong><time>{{ formatTime(event.occurred_at) }}</time></li></ol><p class="muted">可点击刷新查看最新进展。</p></section>
            <section v-if="detail.allowed_actions.includes('CANCEL')" class="panel"><h2>申请操作</h2><p class="muted">撤销前请确认不再需要本次申请；开始退款执行后无法撤销。</p><button data-test="cancel-case" class="danger-button" type="button" :disabled="writing" @click="cancelOpen = true; cancelReason = ''">撤销申请</button></section>
          </aside>
        </div>
      </template>
    </main>
    <ReviewDialog v-if="cancelOpen" title="确认撤销申请" workspace="客户工作台" :busy="writing" @close="cancelOpen = false"><p>撤销后本次申请结束，已提交记录仍可查看。</p><label>撤销原因<textarea v-model="cancelReason" rows="3" maxlength="1000" :disabled="writing" placeholder="请说明撤销原因" /></label><div class="customer-form-footer"><button type="button" class="secondary-button" :disabled="writing" @click="cancelOpen = false">继续申请</button><button type="button" class="danger-button" data-test="confirm-cancel" :disabled="writing || !cancelReason.trim()" @click="cancel">确认撤销</button></div></ReviewDialog>
  </div>
</template>
