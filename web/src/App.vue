<script setup lang="ts">
import ListPagination from './ui/ListPagination.vue'
import { useCursorPages } from './cursor-pages'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ApiError, coreApi, type CaseCollaboration, type CaseSnapshot, type LoginResponse, type OrderLine, type ReviewContext, type ReviewItem, type ReviewQueueCounts, type ReviewScope } from './client'
import { watchCaseEvents } from './events'
import { formatMinorUnits } from './money'
import Icon from './ui/ReviewIcon.vue'
import UserAvatar from './ui/UserAvatar.vue'
import NotificationCenter from './ui/NotificationCenter.vue'
import EnrollmentForm from './ui/EnrollmentForm.vue'
import type { Notification } from './notification-client'
import AccountWorkspace from './ui/AccountWorkspace.vue'
import type { AccountProfile } from './account-client'
import ReviewDialog from './ui/ReviewDialog.vue'
import MerchantDecisionForm from './ui/MerchantDecisionForm.vue'
import ReviewerWorkspace from './ui/ReviewerWorkspace.vue'
import CaseAssignment from './ui/CaseAssignment.vue'
import CustomerWorkspace from './ui/CustomerWorkspace.vue'
import MarketplaceWorkspace from './ui/MarketplaceWorkspace.vue'
import AdminPeople from './ui/AdminPeople.vue'
import AdminProducts from './ui/AdminProducts.vue'
import PlatformWorkspace from './ui/PlatformWorkspace.vue'
import AdminOverview from './ui/AdminOverview.vue'
import AdminPolicies from './ui/AdminPolicies.vue'
import AdminTrades from './ui/AdminTrades.vue'
import MerchantReviews from './ui/MerchantReviews.vue'
import SupportWorkspace from './ui/SupportWorkspace.vue'
import InvestigationSources from './ui/InvestigationSources.vue'
import PolicyCitations from './ui/PolicyCitations.vue'
import { paidAtOf, productNameMissing, productTitle, variantOf } from './ui/order-line-format'
import './ui/workbench.css'
import './ui/admin-workspace.css'
import './ui/aftercare.css'
import './ui/merchant-review.css'
import './ui/interface.css'
import './ui/interaction-motion.css'
import AftercareProduct from './ui/AftercareProduct.vue'
import MerchantCaseDetail from './ui/MerchantCaseDetail.vue'
import { useAftercareProducts } from './ui/aftercare-products'
import { fulfillmentApi, fulfillmentLabels, type MerchantTrade } from './fulfillment-client'
import { clearTabSession, readTabSession, saveTabSession } from './tab-session'

const loginNotice = ref('')
const username = ref('')
const password = ref('')
const account = ref<LoginResponse | null>(readTabSession())
const notificationTicket = ref<string | undefined>()
const overviewOrderId = ref<string | undefined>()
function openNotification(item: Notification) {
  if (busy.value) return
  if (item.target === 'TICKET') { notificationTicket.value = item.target_id; changeMerchantPage('support') }
  else if (item.target === 'CASE') overviewCase(item.target_id)
}
const profileOpen = ref(false), profileBusy = ref(false)
function loginNameChanged(name: string) { logout(); username.value = name; password.value = ''; loginNotice.value = '账号已修改，请使用新账号登录。' }
function updateProfile(value: AccountProfile) { if (account.value) { account.value = { ...account.value, display_name: value.display_name }; saveTabSession(account.value) } }
const products = useAftercareProducts(() => account.value?.access_token)
const productLines = products.lines, productStates = products.states
const merchantCaseOpen = ref(false)
const merchantTrade = ref<MerchantTrade | null>(null)
const tradeReadState = ref<'idle' | 'loading' | 'unavailable'>('idle')
const shopVisitor = ref(window.location.hash.startsWith('#/shop'))
const enrollmentMode = ref<'register' | 'recover' | null>(null), enrollmentBusy = ref(false)
function finishEnrollment(name?: string) { loginNotice.value = ''; enrollmentMode.value = null; if (name) username.value = name; password.value = ''; error.value = '' }
const shopReturn = ref('')
function updateShopVisitor() { shopVisitor.value = window.location.hash.startsWith('#/shop') }
function shopLogin() { shopReturn.value = window.location.hash; window.history.pushState(null, '', '#/login'); shopVisitor.value = false }
onMounted(() => { window.addEventListener('hashchange', updateShopVisitor); window.addEventListener('popstate', updateShopVisitor) })
onUnmounted(() => { window.removeEventListener('hashchange', updateShopVisitor); window.removeEventListener('popstate', updateShopVisitor) })
const error = ref('')
const notice = ref('')
const busy = ref(false)
const reviewItems = ref<ReviewItem[]>([])
const reviewCursor = ref<string | undefined>()
const { pageIndex: reviewPageIndex, pageCursor: reviewPageCursor, acceptPage: acceptReviewPage, resetPages: resetReviewPages } = useCursorPages<string>()
const reviewView = ref('REVIEW')
const reviewQuery = ref('')
const reviewSearch = ref('')
const reviewScope = ref<ReviewScope>('PUBLIC')
const reviewCounts = ref<ReviewQueueCounts | null>(null)
const queueScopes = [{ key: 'PUBLIC' as const, label: '公共', count: 'public' as const },
  { key: 'MINE' as const, label: '我的', count: 'mine' as const },
  { key: 'UNCLAIMED' as const, label: '未领取', count: 'unclaimed' as const }]
let queueGeneration = 0
let actionGeneration = 0
const queueUpdate = ref('')
let pollingQueue = false, queueTimer: ReturnType<typeof setInterval> | undefined
const lookupId = ref('')
const snapshot = ref<CaseSnapshot | null>(null)
const selectedOrderLine = ref<OrderLine | null>(null)
const orderContextState = ref<'idle' | 'loading' | 'unavailable'>('idle')
const decisionReason = ref('')
type ReviewDecision = 'APPROVE' | 'REJECT' | 'REQUEST_INFO'
const reviewDecision = ref<ReviewDecision | null>(null)
const reviewTarget = ref<CaseSnapshot | null>(null)
const reviewLine = ref<OrderLine | null>(null)
const reviewAmount = computed(() => typeof reviewTarget.value?.proposal?.recomputed_amount_minor === 'number' ? reviewTarget.value.proposal.recomputed_amount_minor : null)
const collaboration = ref<CaseCollaboration | null>(null)
const reviewCollaborationTarget = ref<CaseCollaboration | null>(null)
/** Review permissions and execution data belong to the current case version. */
const reviewContext = ref<ReviewContext | null>(null)
const reviewContextLoading = ref(false)
const reviewContextError = ref('')
let reviewContextGeneration = 0
/** The clause a citation asked to open, plus a nonce so the same clause can be re-opened. */
const focusedPolicy = ref<string | null>(null)
const focusNonce = ref(0)
const queryOpen = ref(false)
type MerchantPage = 'review' | 'people' | 'overview' | 'policies' | 'orders' | 'products' | 'support' | 'reviews'
const merchantPage = ref<MerchantPage>('review')
function changeMerchantPage(page: MerchantPage, query = false) {
  if (busy.value || (isSingleMerchant.value && page === 'people')) return
  const returning = merchantPage.value !== 'review' && page === 'review'
  if (isSingleMerchant.value) closeMerchantCase()
  closeReview(); merchantPage.value = page; queryOpen.value = query
  if (page !== 'review') stopStream()
  overviewOrderId.value = undefined
  if (returning) void act(async () => { if (!await loadReviewQueue()) return; if (!isSingleMerchant.value && snapshot.value) await openCase(snapshot.value.case.case_id) })
}

function quickQueue(view: string, scope: ReviewScope) {
  if (busy.value) return
  if (isSingleMerchant.value) closeMerchantCase()
  closeReview()
  merchantPage.value = 'review'; reviewView.value = view; reviewScope.value = scope
  reviewQuery.value = ''; filterQueue()
}
function tradeAftercare(order: string) {
  if (busy.value) return
  changeMerchantPage('review'); queryOpen.value = false; reviewView.value = 'ALL'; reviewScope.value = 'PUBLIC'; reviewQuery.value = order
  filterQueue()
}

function overviewOrder(id: string) { if (busy.value) return; changeMerchantPage('orders'); overviewOrderId.value = id }
function overviewSupport(id?: string) { if (busy.value) return; changeMerchantPage('support'); notificationTicket.value = id }
function overviewCase(id: string) {
  if (busy.value) return
  merchantPage.value = 'review'; queryOpen.value = true
  void act(async () => { await loadReviewQueue(); await openCase(id) })
}
async function pollQueue() {
  if (!isReviewer.value || merchantPage.value !== 'review' || busy.value || pollingQueue || document.hidden) return
  pollingQueue = true
  try { await loadReviewQueue(undefined, true) } catch (cause) { fail(cause) }
  finally { pollingQueue = false }
}

/**
 * Whether the right-hand context column is folded into the detail column.
 *
 * The breakpoint matches the CSS: below 1300px the three-column reviewer grid no longer leaves the
 * detail at least ~620px, so the order/authorisation/payment facts move below it and become a
 * disclosure the reviewer opens when they want them. Markup rather than a CSS override of
 * `<details>` on purpose — a closed `<details>` cannot be reopened by CSS, and an always-open one
 * cannot be collapsed.
 */
const contextFolded = ref(false)
/** The fold's own state, so opening it once keeps it open across re-renders. */
const contextOpen = ref(false)
/** Below the stacking breakpoint the queue and the detail share one column, so a case needs a way
 * back to the list; above it both are on screen and the control would be noise. */
const narrowScreen = ref(false)
let contextQuery: MediaQueryList | null = null
let narrowQuery: MediaQueryList | null = null
function closeMerchantCase() {
  closeReview(); stopStream(); merchantCaseOpen.value = false; lookupId.value = ''; snapshot.value = null
  selectedOrderLine.value = null; merchantTrade.value = null; tradeReadState.value = 'idle'
  focusedPolicy.value = null
  ++reviewContextGeneration; reviewContext.value = null; collaboration.value = null; reviewContextLoading.value = false; reviewContextError.value = ''
}
function backToList() {
  if (isSingleMerchant.value) { if (!busy.value) closeMerchantCase(); return }
  document.getElementById(isReviewer.value ? 'queue-panel' : 'order-panel')?.scrollIntoView?.({ block: 'start' })
}
onMounted(() => {
  queueTimer = setInterval(() => { void pollQueue() }, 30000)
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
  contextQuery = window.matchMedia('(max-width: 1299px)')
  contextFolded.value = contextQuery.matches
  contextQuery.addEventListener('change', event => { contextFolded.value = event.matches })
  narrowQuery = window.matchMedia('(max-width: 850px)')
  narrowScreen.value = narrowQuery.matches
  narrowQuery.addEventListener('change', event => { narrowScreen.value = event.matches })
})
onUnmounted(() => {
  clearInterval(queueTimer)
  contextQuery?.removeEventListener('change', () => undefined)
  narrowQuery?.removeEventListener('change', () => undefined)
})
const decisionLabels = { APPROVE: '批准退款', REJECT: '拒绝申请', REQUEST_INFO: '请客户补充说明' }
const reviewSubmitLabels = { APPROVE: '确认批准', REJECT: '确认拒绝', REQUEST_INFO: '发送问题' }
function beginReview(decision: ReviewDecision) {
  if (!snapshot.value || !collaboration.value?.is_owner || snapshot.value.authorization?.status !== 'PENDING_REVIEW') return
  reviewTarget.value = snapshot.value
  reviewLine.value = selectedOrderLine.value
  reviewCollaborationTarget.value = collaboration.value
  reviewDecision.value = decision
  decisionReason.value = ''
  error.value = ''
}
function closeReview() { reviewDecision.value = null; reviewTarget.value = null; reviewLine.value = null; reviewCollaborationTarget.value = null; decisionReason.value = '' }

const verificationReason = ref('')
const streamStatus = ref('未连接')
let streamController: AbortController | null = null

const isCustomer = computed(() => account.value?.role === 'CUSTOMER')
const isReviewer = computed(() => ['REVIEWER', 'MERCHANT_ADMIN', 'OPERATOR'].includes(account.value?.role ?? ''))
const isSingleMerchant = computed(() => account.value?.role === 'MERCHANT_ADMIN' && account.value.single_operator === true)
const canHumanReview = computed(() => isReviewer.value && collaboration.value?.is_owner === true && !reviewContextLoading.value)
const canVerifyEvidence = computed(() => canHumanReview.value && !!snapshot.value
  && !['EXECUTING', 'RECONCILING', 'CLOSED_SUCCESS', 'CLOSED_REJECTED', 'CANCELLED'].includes(snapshot.value.case.status)
  && snapshot.value.authorization?.status !== 'CONSUMED')
const caseStatusLabels: Record<string, string> = {
  QUEUED: '等待调查', ANALYZING: '调查中', WAITING_CUSTOMER: '待客户补证',
  PENDING_REVIEW: '待人工审核', AUTHORIZED: '已批准待执行', EXECUTING: '退款执行中',
  RECONCILING: '退款对账中', CLOSED_SUCCESS: '退款已完成',
  CLOSED_REJECTED: '已拒绝', CANCELLED: '已取消',
}
const statusLabel = (status: string) => caseStatusLabels[status] ?? status
const authorizationStatusLabels: Record<string, string> = {
  PENDING_REVIEW: '待人工审核', APPROVED: '已批准', CONSUMED: '已消费（不可重审）',
  REJECTED: '已拒绝', EXPIRED: '已失效', REVOKED: '已撤销',
}
const authorizationStatusLabel = (status: string) => authorizationStatusLabels[status] ?? status
const categoryLabels: Record<string, string> = { apparel: '服饰商品', electronics: '电子产品', home: '家居商品', beauty: '美妆商品' }
const evidenceLabels: Record<string, string> = {
  ORDER_LINE: '订单行记录', PAYMENT_LEDGER: '支付记录', SHIPMENT: '物流记录',
  SHIPMENT_TRACK: '物流轨迹', CUSTOMER_STATEMENT: '客户陈述',
  REVIEWER_VERIFICATION: '人工核验', POLICY_RULE: '政策条款',
}
const verificationLabels: Record<string, string> = {
  CONFIRMED: '确认', REFUTED: '驳回', INCONCLUSIVE: '无法判定',
}
const verifiedEvidence = computed(() => new Map(
  snapshot.value?.evidence.filter(item => item.reviewed_evidence_id && item.verification_result)
    .map(item => [item.reviewed_evidence_id!, item.verification_result!]) ?? [],
))
const timelineLabels: Record<string, string> = {
  CASE_CREATED: '工单已创建', AGENT_STARTED: 'Agent 开始调查', PROPOSAL_READY: '调查建议已生成',
  EVIDENCE_APPENDED: '工单材料已更新', EVIDENCE_REVIEWED: '材料已核验', REVIEW_APPROVED: '审核已批准',
  REVIEW_REJECTED: '审核已拒绝', REVIEW_REQUESTED_INFO: '等待客户补证',
  APPROVAL_REQUIRED: '等待人工审批', AUTHORIZATION_DECIDED: '人工审核决定',
  EXECUTION_UPDATED: '退款执行更新', CASE_CLOSED: '工单已结束',
  AGENT_FAILED: '调查失败，已转人工复核', QUESTION_REQUIRED: '等待客户回答补证问题',
  REVIEWER_ACTION: '人工处理已记录',
}
const actionLabels: Record<string, string> = {
  REFUND: '建议全额退款', REQUEST_INFO: '建议补充信息', REJECT: '建议拒绝', MANUAL_REVIEW: '建议人工复核',
}
const proposalAction = (proposal: Record<string, unknown>) =>
  actionLabels[String(proposal.recommended_action ?? '')] ?? '请人工核对方案'
const proposalSourceLabel = (proposal: Record<string, unknown>) =>
  proposal.origin === 'HUMAN' ? '人工方案' : proposal.origin === 'AGENT' ? 'Agent 建议' : '调查建议'
function proposalRevisionLabel(proposal: Record<string, unknown>) {
  const revision = typeof proposal.input_revision === 'number' ? proposal.input_revision : null
  if (!snapshot.value || revision === null) return ''
  return revision < snapshot.value.case.input_revision
    ? `第 ${revision} 版 · 旧版已失效`
    : `第 ${revision} 版 · 当前建议`
}
function validatedRefundAmount(proposal?: Record<string, unknown>) {
  const amount = proposal?.recomputed_amount_minor
  return proposal?.status === 'VALIDATED' && typeof amount === 'number' && Number.isSafeInteger(amount) && amount > 0
    ? amount : null
}
const proposalEvidenceRefs = computed(() => {
  const refs = snapshot.value?.proposal?.evidence_refs
  return Array.isArray(refs) ? refs : []
})
const proposalPolicyRefs = computed(() => {
  const refs = snapshot.value?.proposal?.policy_refs
  return Array.isArray(refs) ? refs : []
})
const proposalCitationCount = computed(() => proposalEvidenceRefs.value.length + proposalPolicyRefs.value.length)
/** Ask the bound-policy list to open the clause a citation named, on its full identity. */
function focusPolicy(key: string) {
  if (!key) return
  focusedPolicy.value = key
  focusNonce.value += 1
}
async function loadReviewContext(view: CaseSnapshot | null) {
  const request = ++reviewContextGeneration
  reviewContext.value = null
  collaboration.value = null
  reviewContextError.value = ''
  if (!view || !isReviewer.value) return
  const sessionToken = token()
  const caseId = view.case.case_id
  reviewContextLoading.value = true
  try {
    const [result, ownership] = await Promise.all([coreApi.reviewContext(sessionToken, caseId), coreApi.collaboration(sessionToken, caseId)])
    if (request !== reviewContextGeneration || token() !== sessionToken || lookupId.value !== caseId
      || snapshot.value?.case.version !== view.case.version) return
    if (result.case_version !== view.case.version) {
      // The context the reviewer would read belongs to a newer case version; enabling actions
      // from it would submit against a page they never saw.
      reviewContextError.value = '工单已变化，请刷新后查看当前操作。'
      return
    }
    reviewContext.value = result
    if (ownership.case_id !== caseId) throw new Error('负责人信息与当前工单不一致，请刷新后重试。')
    collaboration.value = ownership
  } catch (cause) {
    if (request === reviewContextGeneration && token() === sessionToken && lookupId.value === caseId) {
      if (cause instanceof ApiError && cause.status === 401) { fail(cause); return }
      reviewContextError.value = cause instanceof Error ? cause.message : '无法读取审核依据'
    }
  } finally {
    if (request === reviewContextGeneration && token() === sessionToken && lookupId.value === caseId) reviewContextLoading.value = false
  }
}
function headline(value?: string) {
  const text = value?.trim().replace(/\s+/g, ' ') || '退款申请'
  const firstThought = text.split(/[；。]/, 1)[0]
  const title = firstThought.length >= 8 ? firstThought : text
  return title.length > 36 ? `${title.slice(0, 36)}…` : title
}
function formatTimestamp(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date)
}
const token = () => account.value?.access_token ?? ''
const fail = (cause: unknown) => {
  if (cause instanceof ApiError && cause.status === 401 && account.value) { logout(); error.value = '登录已失效，请重新登录。'; return }
  error.value = cause instanceof Error ? cause.message : String(cause)
}

async function act(work: () => Promise<void>) {
  const generation = ++actionGeneration
  busy.value = true
  error.value = ''
  notice.value = ''
  try { await work() } catch (cause) { if (generation === actionGeneration) fail(cause) }
  finally { if (generation === actionGeneration) busy.value = false }
}
async function loadReviewQueue(cursor?: string, background = false, targetPage = 0) {
  const generation = ++queueGeneration
  const sessionToken = token()
  const stage = reviewView.value, query = reviewSearch.value, scope = reviewScope.value
  if (background) { targetPage = reviewPageIndex.value; cursor = reviewPageCursor(targetPage) }
  let page
  try { page = await coreApi.reviewQueue(sessionToken, cursor, stage, query, scope) }
  catch (cause) {
    if (generation !== queueGeneration || account.value?.access_token !== sessionToken) return false
    throw cause
  }
  if (generation !== queueGeneration || account.value?.access_token !== sessionToken ||
      reviewView.value !== stage || reviewScope.value !== scope || reviewSearch.value !== query) return false
  reviewCounts.value = page.counts ?? null
  reviewItems.value = page.items
  reviewCursor.value = page.page.next_cursor ?? undefined
  acceptReviewPage(targetPage, reviewCursor.value); queueUpdate.value = ''
  if (isSingleMerchant.value) void products.readMany(page.items.map(item => item.line_id), !background)
  return true
}
function filterQueue() {
  if (isSingleMerchant.value) closeMerchantCase()
  reviewSearch.value = reviewQuery.value.trim()
  reviewItems.value = []; reviewCursor.value = undefined; reviewCounts.value = null
  queryOpen.value = false
  void act(async () => {
    if (!await loadReviewQueue()) return
    if (!isSingleMerchant.value && reviewItems.value.length) await openCase(reviewItems.value[0].case_id)
    else { closeReview(); stopStream(); snapshot.value = null; selectedOrderLine.value = null }
  })
}
function chooseScope(scope: ReviewScope) { reviewScope.value = scope; filterQueue() }
function stopStream() {
  streamController?.abort()
  streamController = null
  streamStatus.value = '未连接'
}
async function refreshCase(caseId: string) {
  const sessionToken = token()
  const next = await coreApi.case(sessionToken, caseId)
  if (lookupId.value === caseId && token() === sessionToken) {
    if (snapshot.value?.case.case_id === caseId && snapshot.value.case.version > next.case.version) return
    const changed = snapshot.value?.case.version !== next.case.version
    snapshot.value = next
    if (['CLOSED_SUCCESS', 'CLOSED_REJECTED', 'CANCELLED'].includes(next.case.status)) stopStream()
    if (changed) void loadReviewContext(next)
  }
}
async function loadOrderContext(view: CaseSnapshot, sessionToken: string) {
  if (!view.case.order_id) return
  try {
    const order = await coreApi.order(sessionToken, view.case.order_id)
    if (lookupId.value !== view.case.case_id || token() !== sessionToken) return
    selectedOrderLine.value = order.items.find(line => line.line_id === view.case.line_id) ?? null
    orderContextState.value = selectedOrderLine.value ? 'idle' : 'unavailable'
  } catch {
    if (lookupId.value !== view.case.case_id || token() !== sessionToken) return
    orderContextState.value = 'unavailable'
  }
}
async function loadTrade(view: CaseSnapshot, sessionToken: string) {
  if (!view.case.order_id) return
  tradeReadState.value = 'loading'; merchantTrade.value = null
  try {
    const result = await fulfillmentApi.order(sessionToken, view.case.order_id)
    if (token() !== sessionToken || lookupId.value !== view.case.case_id) return
    if (!result.purchase.lines.some(line => line.line_id === view.case.line_id)) throw new Error('订单行不匹配')
    merchantTrade.value = result; tradeReadState.value = 'idle'
  } catch { if (token() === sessionToken && lookupId.value === view.case.case_id) tradeReadState.value = 'unavailable' }
}
async function openCase(caseId: string) {
  merchantCaseOpen.value = isSingleMerchant.value; merchantTrade.value = null; tradeReadState.value = 'idle'; contextOpen.value = false
  closeReview()
  stopStream()
  lookupId.value = caseId.trim()
  snapshot.value = null
  selectedOrderLine.value = null
  orderContextState.value = 'idle'
  const sessionToken = token()
  const requestedId = lookupId.value
  const current = await coreApi.case(sessionToken, requestedId)
  if (token() !== sessionToken || lookupId.value !== requestedId) return
  snapshot.value = current
  if (isSingleMerchant.value) void loadTrade(current, sessionToken)
  void loadReviewContext(current)
  if (current.case.order_id) {
    orderContextState.value = 'loading'
    void loadOrderContext(current, sessionToken)
  }
  if (['CLOSED_SUCCESS', 'CLOSED_REJECTED', 'CANCELLED'].includes(current.case.status)) return
  const controller = new AbortController()
  streamController = controller
  streamStatus.value = '已连接，等待事件'
  const initialId = current.timeline.at(-1)?.event_id ?? null
  void watchCaseEvents(lookupId.value, sessionToken, () => {
    void refreshCase(caseId).catch(fail)
  }, controller.signal, initialId).catch((cause) => {
    if (!controller.signal.aborted) { streamStatus.value = '连接失败'; fail(cause) }
  })
}
async function enterSession(session: LoginResponse) {
  stopStream()
  products.reset(); merchantCaseOpen.value = false; merchantTrade.value = null
  account.value = session
  if (session.single_operator) merchantPage.value = 'overview'
  if (session.buyer_id && !window.location.hash.startsWith('#/shop') && !window.location.hash.startsWith('#/customer/')) window.history.replaceState(null, '', (shopReturn.value.startsWith('#/shop') || shopReturn.value.startsWith('#/customer/')) ? shopReturn.value : '#/shop')
  shopReturn.value = ''
  password.value = ''
  reviewItems.value = []; reviewCounts.value = null; reviewCursor.value = undefined
  reviewScope.value = 'PUBLIC'; reviewView.value = session.single_operator ? 'ALL' : 'REVIEW'; reviewQuery.value = ''; reviewSearch.value = ''
  snapshot.value = null; selectedOrderLine.value = null
  if (['REVIEWER', 'MERCHANT_ADMIN', 'OPERATOR'].includes(session.role)) {
    if (!await loadReviewQueue()) return
    if (!isSingleMerchant.value && reviewItems.value.length) await openCase(reviewItems.value[0].case_id)
  }
}
function login() {
  loginNotice.value = ''
  void act(async () => {
    const session = await coreApi.login(username.value, password.value)
    saveTabSession(session)
    await enterSession(session)
  })
}
onMounted(() => {
  const session = readTabSession()
  if (session) void act(() => enterSession(session))
})
function logout() {
  loginNotice.value = ''
  enrollmentMode.value = null
  profileOpen.value = false; profileBusy.value = false; notificationTicket.value = undefined
  clearTabSession()
  // An explicit account boundary must not reopen the previous customer's private route.
  window.history.replaceState(null, '', window.location.pathname + window.location.search)
  products.reset(); merchantCaseOpen.value = false; merchantTrade.value = null
  closeReview(); stopStream(); account.value = null; snapshot.value = null; selectedOrderLine.value = null
  ++queueGeneration
  ++reviewContextGeneration; reviewContext.value = null; reviewContextLoading.value = false; reviewContextError.value = ''
  lookupId.value = ''; queryOpen.value = false; verificationReason.value = ''; focusedPolicy.value = null
  ++actionGeneration; busy.value = false
  reviewItems.value = []; reviewCursor.value = undefined; reviewCounts.value = null; collaboration.value = null; error.value = ''
  merchantPage.value = 'review'; notice.value = ''; resetReviewPages(); queueUpdate.value = ''
  shopVisitor.value = false
  shopReturn.value = ''
}
function verifyEvidence(evidenceId: string, result: 'CONFIRMED' | 'REFUTED' | 'INCONCLUSIVE') {
  void act(async () => {
    if (!snapshot.value || !verificationReason.value.trim()) throw new Error('请填写核验理由')
    const caseId = snapshot.value.case.case_id
    try {
      await coreApi.reviewEvidence(token(), caseId, evidenceId, result, verificationReason.value.trim(), snapshot.value, collaboration.value)
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        await refreshCase(caseId)
        if (snapshot.value?.case.case_id === caseId) await loadReviewContext(snapshot.value)
        throw new Error('工单或负责人已变化，页面已重新加载，请核对后再核验。')
      }
      throw cause
    }
    verificationReason.value = ''
    await refreshCase(caseId)
    notice.value = '核验已记录，原方案和授权可能已失效。请查看新调查结果，或形成人工退款方案。'
  })
}
function review(decision: ReviewDecision) {
  void act(async () => {
    if (!reviewTarget.value || !decisionReason.value.trim()) throw new Error('请填写审核理由')
    const current = reviewTarget.value
    try {
      await coreApi.review(token(), current, decision, decisionReason.value.trim(), reviewCollaborationTarget.value)
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        await refreshCase(current.case.case_id)
        if (snapshot.value?.case.case_id === current.case.case_id) await loadReviewContext(snapshot.value)
        closeReview()
        throw new Error('工单或授权已变化，页面已重新加载，请核对后再决定')
      }
      throw cause
    }
    closeReview()
    await refreshCase(current.case.case_id)
    await loadReviewQueue()
    notice.value = '审核决定已提交；批准不等于退款已执行'
  })
}
async function refreshWorkspace() {
  if (!snapshot.value) return
  await act(async () => {
    await refreshCase(snapshot.value!.case.case_id)
    await loadReviewContext(snapshot.value)
    await loadReviewQueue()
  })
}
onUnmounted(() => { stopStream(); products.reset() })
</script>

<template>
  <div class="workbench unified-interface" :class="{ 'shopping-workbench': account?.buyer_id || shopVisitor, 'aftercare-workbench': isSingleMerchant, 'merchant-review-workbench': isSingleMerchant && merchantPage === 'review' }">
    <header v-if="!((!account && shopVisitor) || account?.buyer_id)" class="topbar">
      <div class="brand"><span class="brand-mark" aria-hidden="true"><i /><i /><i /><i /></span><span>ResolveFlow</span></div>
      <a v-if="!account" class="login-shop-link" href="#/shop">逛逛商城</a>
      <div v-if="account" class="session"><button class="profile-avatar-button" aria-label="编辑个人资料" @click="profileOpen = true"><UserAvatar :token="account.access_token" source="/api/v1/account/avatar" :name="account.display_name" :kind="account.role === 'MERCHANT_ADMIN' ? 'MERCHANT' : 'CUSTOMER'" /></button><span class="session-copy"><strong>{{ account.display_name || (isReviewer ? '售后专员' : '客户工作台') }}</strong><small>{{ account.role === 'PLATFORM_ADMIN' ? '平台管理员' : account.buyer_id ? '平台买家' : `${account.merchant_name || account.merchant_id} · ${account.role === 'MERCHANT_ADMIN' ? (isSingleMerchant ? '商家' : '商家管理员') : account.role === 'REVIEWER' ? '售后专员' : account.role === 'OPERATOR' ? '兼容运维账号' : '客户'}` }}</small></span>
        <NotificationCenter v-if="account.role === 'MERCHANT_ADMIN'" :token="account.access_token" :disabled="busy" @expired="logout" @open="openNotification" />
        <button type="button" class="text-button logout-button" @click="logout">退出</button></div>
    </header>
    <MarketplaceWorkspace v-if="!account && shopVisitor" :account="null" @login="shopLogin" />
    <main v-else-if="!account" class="login-stage">
      <div class="login-intro"><h1>好物与服务，<br />都在这里。</h1><div class="login-still-life" aria-hidden="true"><img class="login-room" :src="'/identity/login-shopping.webp'" alt="" /></div></div>
      <EnrollmentForm v-if="enrollmentMode" :mode="enrollmentMode" @working="enrollmentBusy = $event" @close="finishEnrollment" />
      <form v-else class="panel login-panel" @submit.prevent="login">
        <h2>欢迎回来</h2>
        <label>用户名 <input v-model="username" name="username" autocomplete="username" placeholder="请输入用户名" /></label>
        <label>密码 <input v-model="password" name="password" type="password" autocomplete="current-password" placeholder="请输入密码" /></label>
        <button data-test="login" type="submit" :disabled="busy">{{ busy ? '正在登录…' : '登录工作台' }}</button>
        <p v-if="error" class="message error" role="alert">{{ error }}</p>
        <p v-else-if="loginNotice" class="message success" role="status">{{ loginNotice }}</p>
        <div class="login-account-links"><button type="button" :disabled="busy" @click="enrollmentMode = 'register'">注册账号</button><button type="button" :disabled="busy" @click="enrollmentMode = 'recover'">忘记密码</button></div>
      </form>
    </main>
    <PlatformWorkspace v-else-if="account.role === 'PLATFORM_ADMIN'" :key="account.access_token" :account="account" @expired="logout(); error = '登录已失效，请重新登录。'" />
    <MarketplaceWorkspace v-else-if="account.buyer_id" :key="account.access_token" :account="account" @profile="updateProfile" @reauthenticate="loginNameChanged" @logout="logout" @expired="logout(); error = '登录已失效，请重新登录。'" />
    <CustomerWorkspace v-else-if="isCustomer" :key="account.access_token" :account="account" @expired="logout(); error = '登录已失效，请重新登录。'" />
    <div v-else class="app-shell" :class="{ 'support-shell': merchantPage === 'support' && account.role === 'MERCHANT_ADMIN' }">
      <nav class="sidebar" aria-label="工作台导航">
        <template v-if="!isSingleMerchant">
        <a v-if="isReviewer" href="#queue-panel" class="nav-link" :class="{ current: merchantPage === 'review' && !queryOpen && reviewScope === 'PUBLIC' && !['ATTENTION','CLOSED'].includes(reviewView) }" :aria-disabled="busy" @click.prevent="quickQueue('REVIEW','PUBLIC')"><Icon name="queue" />公共队列</a>
        <a v-if="isReviewer" href="#mine" class="nav-link" :class="{ current: merchantPage === 'review' && !queryOpen && reviewScope === 'MINE' }" :aria-disabled="busy" @click.prevent="quickQueue('ALL','MINE')"><Icon name="user" />我的工单</a>
        <a v-if="isReviewer" href="#attention" class="nav-link" :class="{ current: merchantPage === 'review' && !queryOpen && reviewScope === 'PUBLIC' && reviewView === 'ATTENTION' }" :aria-disabled="busy" @click.prevent="quickQueue('ATTENTION','PUBLIC')"><Icon name="shield" />结果待确认</a>
        <a v-if="isReviewer" href="#history" class="nav-link" :class="{ current: merchantPage === 'review' && !queryOpen && reviewScope === 'PUBLIC' && reviewView === 'CLOSED' }" :aria-disabled="busy" @click.prevent="quickQueue('CLOSED','PUBLIC')"><Icon name="clock" />历史工单</a>
        <a href="#case-panel" class="nav-link" :class="{ current: merchantPage === 'review' && queryOpen }" :aria-disabled="busy" @click.prevent="changeMerchantPage('review', true)"><Icon name="search" />工单查询</a>
        </template>
        <a v-if="account.role === 'MERCHANT_ADMIN'" href="#overview" class="nav-link" :class="{ current: merchantPage === 'overview' }" :aria-disabled="busy" @click.prevent="changeMerchantPage('overview')"><Icon name="box" />商家概览</a>
        <a v-if="account.role === 'MERCHANT_ADMIN'" href="#orders" class="nav-link" :class="{ current: merchantPage === 'orders' }" :aria-disabled="busy" @click.prevent="changeMerchantPage('orders')"><Icon name="box" />交易订单</a>
        <a v-if="account.role === 'MERCHANT_ADMIN'" href="#products" class="nav-link" :class="{ current: merchantPage === 'products' }" :aria-disabled="busy" @click.prevent="changeMerchantPage('products')"><Icon name="box" />商品管理</a>
        <a v-if="account.role === 'MERCHANT_ADMIN'" href="#product-reviews" class="nav-link" :class="{ current: merchantPage === 'reviews' }" :aria-disabled="busy" @click.prevent="changeMerchantPage('reviews')"><Icon name="file" />商品评价</a>
        <a v-if="isSingleMerchant" href="#aftercare" class="nav-link" :class="{ current: merchantPage === 'review' }" :aria-disabled="busy" @click.prevent="changeMerchantPage('review')"><Icon name="queue" />售后工单</a>
        <a v-if="account.role === 'MERCHANT_ADMIN'" href="#support" class="nav-link" :class="{ current: merchantPage === 'support' }" :aria-disabled="busy" @click.prevent="changeMerchantPage('support')"><Icon name="queue" />咨询核查</a>
        <a v-if="account.role === 'MERCHANT_ADMIN' && !isSingleMerchant" href="#people" class="nav-link" :class="{ current: merchantPage === 'people' }" :aria-disabled="busy" @click.prevent="changeMerchantPage('people')"><Icon name="user" />人员管理</a>
        <a v-if="account.role === 'MERCHANT_ADMIN'" href="#policies" class="nav-link" :class="{ current: merchantPage === 'policies' }" :aria-disabled="busy" @click.prevent="changeMerchantPage('policies')"><Icon name="file" />{{ isSingleMerchant ? '退款规则' : '政策与版本' }}</a>
      </nav>
      <MerchantReviews v-if="merchantPage === 'reviews' && account.role === 'MERCHANT_ADMIN'" :key="account.access_token" :account="account" @working="busy = $event" @expired="logout(); error = '登录已失效，请重新登录。'" />
      <SupportWorkspace v-else-if="merchantPage === 'support' && account.role === 'MERCHANT_ADMIN'" :key="account.access_token + (notificationTicket ?? '')" :initial-id="notificationTicket" :account="account" @expired="logout(); error = '登录已失效，请重新登录。'" />
      <AdminProducts v-else-if="merchantPage === 'products' && account.role === 'MERCHANT_ADMIN'" :key="account.access_token" :account="account" @working="busy = $event" @expired="logout(); error = '登录已失效，请重新登录。'" />
      <AdminTrades v-else-if="merchantPage === 'orders' && account.role === 'MERCHANT_ADMIN'" :key="account.access_token + (overviewOrderId ?? '')" :account="account" :initial-id="overviewOrderId" @working="busy = $event" @expired="logout(); error = '登录已失效，请重新登录。'" @aftercare="tradeAftercare" />
      <AdminPeople v-else-if="merchantPage === 'people' && account.role === 'MERCHANT_ADMIN' && !isSingleMerchant" :key="account.access_token" :account="account" @working="busy = $event" @expired="logout(); error = '账号状态或权限已变化，请重新登录。'" @renamed="account.display_name = $event" />
      <AdminOverview v-else-if="merchantPage === 'overview' && account.role === 'MERCHANT_ADMIN'" :key="account.access_token" :account="account" @expired="logout(); error = '登录已失效，请重新登录。'" @queue="quickQueue" @open="overviewCase" @order="overviewOrder" @support="overviewSupport" @people="changeMerchantPage('people')" @navigate="changeMerchantPage($event)" />
      <AdminPolicies v-else-if="merchantPage === 'policies' && account.role === 'MERCHANT_ADMIN'" :key="account.access_token" :account="account" @expired="logout(); error = '登录已失效，请重新登录。'" />
      <main v-else class="workspace" :class="{ 'reviewer-workspace': isReviewer }">
        <p v-if="error && !reviewDecision" class="message error workspace-message" role="alert">{{ error }}</p>
        <p v-if="notice" class="message success workspace-message" role="status"><Icon name="check" />{{ notice }}</p>
        <div class="columns" :class="{ 'customer-columns': isCustomer, 'reviewer-columns': isReviewer, 'merchant-aftercare': isSingleMerchant, 'merchant-case-view': isSingleMerchant && merchantCaseOpen }">
          <section v-if="isReviewer && (!isSingleMerchant || !merchantCaseOpen)" id="queue-panel" class="panel list-panel" aria-label="审核队列">
            <div class="panel-heading"><h2>{{ isSingleMerchant ? '售后工单' : '审核队列' }} <span v-if="reviewCounts">（{{ reviewCounts.total }}）</span></h2><span class="queue-scope">当前商家</span></div>
            <p v-if="queueUpdate" class="queue-summary" role="status">{{ queueUpdate }}</p>

            <div v-if="!isSingleMerchant" class="queue-ownership" role="group" aria-label="工单归属范围"><button v-for="scope in queueScopes" :key="scope.key" type="button" :data-scope="scope.key" :aria-pressed="reviewScope === scope.key" :disabled="busy" @click="chooseScope(scope.key)">{{ scope.label }}<span v-if="reviewCounts">{{ reviewCounts[scope.count] }}</span></button></div>
            <form class="queue-filters" @submit.prevent="filterQueue"><label>处理阶段<select v-model="reviewView" :disabled="busy" @change="filterQueue"><option value="REVIEW">待审核</option><option value="WAITING">待客户补证</option><option value="PROCESSING">调查与退款处理中</option><option value="ATTENTION">结果待确认</option><option value="CLOSED">已结束</option><option value="ALL">全部工单</option></select></label><div class="queue-search"><input v-model="reviewQuery" aria-label="搜索工单" maxlength="100" placeholder="工单号、订单号或问题描述" :disabled="busy" /><button type="submit" class="secondary-button" :disabled="busy">查询</button></div></form>
            <div v-if="reviewItems.length === 0" class="empty"><Icon name="queue" :size="30" /><strong>没有符合条件的工单</strong><p>可切换处理阶段或修改查询条件</p></div>
            <div v-if="isSingleMerchant" class="merchant-case-list" aria-label="工单列表">
              <article v-for="item in reviewItems" :key="item.case_id" class="merchant-case-card">
                <div><AftercareProduct :line="productLines[item.line_id]" :loading="productStates[item.line_id] === 'loading'" :unavailable="productStates[item.line_id] === 'unavailable'" /><p class="merchant-case-description">{{ headline(item.description) }}</p><button v-if="productStates[item.line_id] === 'unavailable'" class="text-button" type="button" @click="products.read(item.line_id, true)">重试商品资料</button></div>
                <div class="merchant-case-status"><span class="status-tag" :class="{ waiting: item.status === 'PENDING_REVIEW', success: item.status === 'CLOSED_SUCCESS' }">{{ statusLabel(item.status) }}</span><time>{{ formatTimestamp(item.updated_at) }}</time></div>
                <button type="button" class="secondary-button queue-open" :disabled="busy" @click="act(() => openCase(item.case_id))">查看工单</button>
              </article>
            </div>
            <div v-else class="scroll-list" aria-label="工单列表">
              <button v-for="item in reviewItems" :key="item.case_id" type="button" class="queue-row" :aria-pressed="snapshot?.case.case_id === item.case_id"
                :class="{ selected: snapshot?.case.case_id === item.case_id }" :disabled="busy" @click="act(() => openCase(item.case_id))">
                <span class="queue-top"><span class="queue-category"><Icon name="file" :size="14" />退款申请</span><span class="status-tag" :class="{ waiting: item.status === 'PENDING_REVIEW', success: item.status === 'CLOSED_SUCCESS' }">{{ statusLabel(item.status) }}</span></span>
                <strong class="queue-title">{{ headline(item.description) }}</strong><small><Icon name="clock" :size="13" />更新于 {{ formatTimestamp(item.updated_at) }}</small>
                <span v-if="!isSingleMerchant" class="queue-owner"><Icon name="user" :size="13" />{{ item.owner === undefined ? '归属信息待刷新' : item.owner ? `${item.owner.display_name || item.owner.username}${item.owner.enabled ? '' : '（已停用）'}` : '未领取' }}</span>
              </button>
            </div>
            <p v-if="reviewCounts && !isSingleMerchant" class="queue-summary">已显示 {{ reviewItems.length }} / {{ reviewCounts.total }} 条 · 数量按已应用的筛选统计<template v-if="reviewSearch"><br />搜索：{{ reviewSearch }}</template></p>
            <div class="list-actions"><ListPagination :page="reviewPageIndex" :has-next="!!reviewCursor" :disabled="busy" label="售后工单分页" @change="index => act(async () => { await loadReviewQueue(reviewPageCursor(index), false, index) })" /><button type="button" class="text-button" :disabled="busy" @click="act(async () => { await loadReviewQueue() })">刷新队列</button></div>
          </section>
          <MerchantCaseDetail v-if="isSingleMerchant && merchantCaseOpen && snapshot" :key="snapshot.case.case_id" :token="token()" :snapshot="snapshot" :line="selectedOrderLine" :busy="busy" :product-state="orderContextState" :trade-state="tradeReadState" :fulfillment="merchantTrade ? fulfillmentLabels[merchantTrade.fulfillment.lines.find(line => line.line_id === snapshot!.case.line_id)?.status ?? 'UNKNOWN'] : tradeReadState === 'loading' ? '正在读取…' : '暂未读取'" :context="reviewContext" :collaboration="collaboration" :context-loading="reviewContextLoading" :context-error="reviewContextError" :status-label="statusLabel(snapshot.case.status)" @back="backToList" @order="changeMerchantPage('orders')" @retry-product="loadOrderContext(snapshot, token())" @retry-trade="loadTrade(snapshot, token())" @review="beginReview" @refresh="refreshWorkspace" @working="busy = $event" @expired="logout(); error = '登录已失效，请重新登录。'">
            <template #materials>
              <section class="detail-section evidence-section"><div class="section-heading"><h3>证据与材料 <span class="section-count">（{{ snapshot.evidence.length }}）</span></h3><span class="subtle">展开查看完整内容</span></div>
                <p v-if="snapshot.evidence.length === 0" class="evidence-empty"><Icon name="file" />暂无材料。</p>
                <div v-if="snapshot.evidence.length" class="evidence-list"><article v-for="item in snapshot.evidence" :key="item.observation_id" class="evidence">
                  <div class="evidence-head"><span class="material-icon"><Icon :name="item.reviewed_evidence_id ? 'shield' : 'file'" :size="22" /></span><div class="evidence-meta"><strong>{{ evidenceLabels[item.evidence_kind] ?? item.evidence_kind }}</strong><span v-if="item.verification_result" class="verification-tag" :class="item.verification_result.toLowerCase()">{{ verificationLabels[item.verification_result] ?? item.verification_result }}</span><span v-else-if="verifiedEvidence.get(item.observation_id)" class="verification-tag" :class="verifiedEvidence.get(item.observation_id)?.toLowerCase()">已核验：{{ verificationLabels[verifiedEvidence.get(item.observation_id)!] }}</span><span v-else class="subtle">待人工核验</span></div></div>
                  <p class="evidence-excerpt">{{ item.content }}</p><details class="evidence-id"><summary>查看材料来源与编号<Icon name="chevron" :size="12" /></summary><p class="full-evidence">{{ item.content }}</p><div>材料编号：{{ item.observation_id }}</div><div>来源引用：{{ item.source_ref || '未提供' }}</div><div v-if="item.observed_at">记录时间：{{ formatTimestamp(item.observed_at) }}</div><div v-if="item.reviewed_evidence_id">核验材料：{{ item.reviewed_evidence_id }}</div></details>
                  <div v-if="canVerifyEvidence && !item.reviewed_evidence_id && !verifiedEvidence.has(item.observation_id)" class="actions verification-actions"><button type="button" class="secondary-button" :disabled="busy" @click="verifyEvidence(item.observation_id, 'CONFIRMED')">确认</button><button type="button" class="secondary-button" :disabled="busy" @click="verifyEvidence(item.observation_id, 'REFUTED')">驳回</button><button type="button" class="secondary-button" :disabled="busy" @click="verifyEvidence(item.observation_id, 'INCONCLUSIVE')">无法判定</button></div>
                </article></div>
                <label v-if="canVerifyEvidence && snapshot.evidence.some(item => !item.reviewed_evidence_id && !verifiedEvidence.has(item.observation_id))" class="verification-reason">核验理由 <input v-model="verificationReason" placeholder="提交核验前填写理由" /></label>
              </section>
            </template>
          </MerchantCaseDetail>
          <section v-if="!isSingleMerchant" id="case-panel" class="panel case-panel" aria-label="工单内容" :aria-busy="busy">
            <div class="panel-heading case-heading"><h2>{{ isReviewer ? '退款工单' : '工单详情' }}</h2><span v-if="snapshot" class="status-tag" :class="{ waiting: snapshot.case.status === 'PENDING_REVIEW', success: snapshot.case.status === 'CLOSED_SUCCESS' }">{{ statusLabel(snapshot.case.status) }}</span></div>
            <details v-if="!isSingleMerchant" class="lookup-tools" :open="queryOpen"><summary @click.prevent="queryOpen = !queryOpen"><Icon name="search" :size="13" />按工单编号查询</summary><div class="lookup"><label>工单编号 <input v-model="lookupId" name="case-id" placeholder="输入已知工单编号" /></label><button type="button" class="secondary-button" :disabled="busy || !lookupId.trim()" @click="act(() => openCase(lookupId))">查看工单</button></div></details>
            <div v-if="!snapshot" class="case-empty"><Icon name="queue" :size="42" /><strong>{{ busy ? '正在读取工单…' : '选择一条工单，开始审核' }}</strong><p>订单、证据与调查建议将在这里汇集。</p></div>
            <template v-else>
              <button v-if="narrowScreen || isSingleMerchant" :disabled="busy" type="button" class="secondary-button back-to-list" data-test="back-to-list" @click="backToList">← 返回队列</button>
              <div v-if="!isSingleMerchant" class="case-title"><h3>{{ headline(snapshot.case.description) }}</h3><span class="stream-indicator"><i :class="{ disconnected: streamStatus === '连接失败' }" />{{ streamStatus === '未连接' ? '静态快照' : streamStatus }}</span></div>
              <CaseAssignment v-if="isReviewer && !isSingleMerchant" :token="token()" :current="collaboration" :loading="reviewContextLoading" :busy="busy" @changed="refreshWorkspace" @working="busy = $event" @expired="logout" />
              <section v-if="isSingleMerchant" class="case-order" aria-label="申请商品"><AftercareProduct :line="selectedOrderLine" :loading="orderContextState === 'loading'" :unavailable="orderContextState === 'unavailable'" /><button v-if="orderContextState === 'unavailable'" type="button" class="text-button" @click="loadOrderContext(snapshot, token())">重试商品资料</button></section>
              <section v-else-if="isReviewer" class="case-order" aria-label="订单行摘要"><div class="section-heading"><h3>订单信息</h3><span v-if="snapshot.case.order_id" class="subtle-id" :title="snapshot.case.order_id">订单号：{{ snapshot.case.order_id }}</span></div>
                <div v-if="selectedOrderLine" class="case-order-content"><span class="product-placeholder"><Icon name="box" :size="32" /></span><div class="product-copy"><strong :class="{ 'name-missing': productNameMissing(selectedOrderLine) }" data-test="case-product">{{ productTitle(selectedOrderLine) }}</strong><span v-if="variantOf(selectedOrderLine)" data-test="case-variant">{{ variantOf(selectedOrderLine) }}</span><span class="product-sku">{{ productNameMissing(selectedOrderLine) ? (categoryLabels[selectedOrderLine.category] ?? selectedOrderLine.category) : `${selectedOrderLine.sku} · ${categoryLabels[selectedOrderLine.category] ?? selectedOrderLine.category}` }}</span><small>数量 × {{ selectedOrderLine.quantity }}<template v-if="paidAtOf(selectedOrderLine)"> · 支付于 {{ formatTimestamp(paidAtOf(selectedOrderLine)!) }}</template></small></div><div class="case-order-amount"><small>本行实付</small><b>{{ formatMinorUnits(selectedOrderLine.line_paid_amount, selectedOrderLine.currency) }}</b></div><div v-if="validatedRefundAmount(snapshot.proposal) !== null" class="case-order-amount refund-amount"><small>{{ snapshot.authorization?.status === 'PENDING_REVIEW' ? '待审退款额' : '方案退款额' }}</small><b>{{ formatMinorUnits(validatedRefundAmount(snapshot.proposal)!, selectedOrderLine.currency) }}</b><small>服务端已校验 · 全额退款</small></div></div>
                <p v-else-if="orderContextState === 'loading'" class="muted skeleton-line">正在读取订单信息…</p><p v-else class="muted">暂无可展示的订单明细</p></section>
              <section v-if="snapshot.case.description" class="customer-issue"><h3>客户问题描述</h3><p>{{ snapshot.case.description }}</p></section>
              <section class="detail-section evidence-section"><div class="section-heading"><h3>证据与材料 <span class="section-count">（{{ snapshot.evidence.length }}）</span></h3><span class="subtle">展开查看完整内容</span></div>
                <p v-if="snapshot.evidence.length === 0" class="evidence-empty"><Icon name="file" />暂无材料。</p>
                <div v-if="snapshot.evidence.length" class="evidence-list"><article v-for="item in snapshot.evidence" :key="item.observation_id" class="evidence">
                  <div class="evidence-head"><span class="material-icon"><Icon :name="item.reviewed_evidence_id ? 'shield' : 'file'" :size="22" /></span><div class="evidence-meta"><strong>{{ evidenceLabels[item.evidence_kind] ?? item.evidence_kind }}</strong><span v-if="item.verification_result" class="verification-tag" :class="item.verification_result.toLowerCase()">{{ verificationLabels[item.verification_result] ?? item.verification_result }}</span><span v-else-if="verifiedEvidence.get(item.observation_id)" class="verification-tag" :class="verifiedEvidence.get(item.observation_id)?.toLowerCase()">已核验：{{ verificationLabels[verifiedEvidence.get(item.observation_id)!] }}</span><span v-else class="subtle">待人工核验</span></div></div>
                  <p class="evidence-excerpt">{{ item.content }}</p><details class="evidence-id"><summary>查看材料来源与编号<Icon name="chevron" :size="12" /></summary><p class="full-evidence">{{ item.content }}</p><div>材料编号：{{ item.observation_id }}</div><div>来源引用：{{ item.source_ref || '未提供' }}</div><div v-if="item.observed_at">记录时间：{{ formatTimestamp(item.observed_at) }}</div><div v-if="item.reviewed_evidence_id">核验材料：{{ item.reviewed_evidence_id }}</div></details>
                  <div v-if="canVerifyEvidence && !item.reviewed_evidence_id && !verifiedEvidence.has(item.observation_id)" class="actions verification-actions"><button type="button" class="secondary-button" :disabled="busy" @click="verifyEvidence(item.observation_id, 'CONFIRMED')">确认</button><button type="button" class="secondary-button" :disabled="busy" @click="verifyEvidence(item.observation_id, 'REFUTED')">驳回</button><button type="button" class="secondary-button" :disabled="busy" @click="verifyEvidence(item.observation_id, 'INCONCLUSIVE')">无法判定</button></div>
                </article></div>
                <label v-if="canVerifyEvidence && snapshot.evidence.some(item => !item.reviewed_evidence_id && !verifiedEvidence.has(item.observation_id))" class="verification-reason">核验理由 <input v-model="verificationReason" placeholder="提交核验前填写理由" /></label>
              </section>
              <div class="analysis-grid" :class="{ 'without-proposal': !snapshot.proposal }">
                <section v-if="snapshot.proposal" class="detail-section proposal"><h3>{{ proposalSourceLabel(snapshot.proposal) }}<span class="advice-label">{{ proposalRevisionLabel(snapshot.proposal) || '调查结论' }}</span></h3><div class="recommendation"><span class="recommendation-icon"><Icon name="sparkle" :size="21" /></span><strong>{{ proposalAction(snapshot.proposal) }}</strong></div><p v-if="typeof snapshot.proposal.summary === 'string'" class="proposal-summary">{{ snapshot.proposal.summary }}</p>
                  <PolicyCitations v-if="proposalCitationCount" :compact="isSingleMerchant" :evidence-refs="proposalEvidenceRefs" :policy-refs="proposalPolicyRefs" :policy-rules="reviewContext?.policy_rules ?? []" :policy-status="reviewContext?.policy_status ?? null" @focus="focusPolicy" /><details class="proposal-details"><summary>查看完整方案与全部引用</summary><pre>{{ JSON.stringify(snapshot.proposal, null, 2) }}</pre></details>
                </section>
                <component :is="isSingleMerchant ? 'details' : 'section'" class="detail-section timeline-section"><summary v-if="isSingleMerchant">查看完整工单轨迹（{{ snapshot.timeline.length }}）</summary><h3>工单轨迹</h3><p v-if="snapshot.timeline.length === 0" class="empty">暂无轨迹事件</p><ol v-else class="timeline"><li v-for="event in snapshot.timeline.slice(-4)" :key="event.event_id"><time>{{ formatTimestamp(event.occurred_at) }}</time><strong>{{ timelineLabels[event.type] ?? event.type }}</strong></li></ol><details v-if="snapshot.timeline.length" class="timeline-more"><summary>查看全部 {{ snapshot.timeline.length }} 条事件</summary><ol class="timeline"><li v-for="event in snapshot.timeline" :key="event.event_id"><time>{{ formatTimestamp(event.occurred_at) }}</time><strong>{{ timelineLabels[event.type] ?? event.type }}</strong><p>{{ event.summary }}</p></li></ol></details></component>
              </div>
              <InvestigationSources v-if="isReviewer" :compact="isSingleMerchant" :token="token()" :snapshot="snapshot" />
              <section v-if="canHumanReview && snapshot.authorization?.status === 'PENDING_REVIEW'" class="detail-section review-section"><div class="section-heading"><h3>审核决策</h3><span class="subtle">批准授权后仍需等待独立的退款执行结果</span></div><div class="actions"><button data-test="approve" type="button" :disabled="busy" @click="beginReview('APPROVE')"><Icon name="check" :size="19" />批准授权</button><button type="button" class="secondary-button" :disabled="busy" @click="beginReview('REQUEST_INFO')"><Icon name="file" :size="17" />请求补证</button><button type="button" class="danger-button" :disabled="busy" @click="beginReview('REJECT')"><Icon name="close" :size="19" />拒绝</button></div></section>
              <section v-else-if="isReviewer && snapshot.case.status === 'PENDING_REVIEW'" class="detail-section review-unavailable" aria-label="审核暂不可用"><Icon name="shield" :size="22" /><div><h3>{{ snapshot.authorization?.status === 'PENDING_REVIEW' ? '审核操作暂不可用' : '暂无可审核授权' }}</h3><p v-if="snapshot.authorization?.status === 'PENDING_REVIEW'">{{ collaboration?.is_owner ? '正在核对审核上下文，请刷新后继续。' : isSingleMerchant ? '本店工单处理身份尚未就绪，请刷新后继续。' : '请先领取工单；仅当前负责人可审核待审授权。' }}</p><p v-else-if="snapshot.authorization">当前授权{{ authorizationStatusLabel(snapshot.authorization.status) }}，不能再次审核；请核对工单轨迹与当前结果。</p><p v-else>此工单正在等待人工复核，但服务端尚无待审退款授权。请核对方案与材料；当前不能批准退款。</p></div></section>
              <ReviewerWorkspace v-if="isReviewer" :compact="isSingleMerchant" :token="token()" :snapshot="snapshot" :busy="busy" :context="reviewContext" :collaboration="collaboration" :context-loading="reviewContextLoading" :context-error="reviewContextError" :focus-key="focusedPolicy" :focus-nonce="focusNonce" @changed="refreshWorkspace" @working="busy = $event" @expired="logout(); error = '登录已失效，请重新登录。'" />
            </template>
          </section>
          <component v-if="!isSingleMerchant" :is="contextFolded ? 'details' : 'aside'" class="context-column" :class="{ 'context-fold': contextFolded }" :open="contextFolded ? contextOpen : undefined" aria-label="工单上下文" @toggle="contextOpen = ($event.target as HTMLDetailsElement).open">
            <summary v-if="contextFolded" class="context-fold-summary" data-test="context-fold">订单与执行信息<Icon name="chevron" :size="14" /></summary>
            <section class="panel context-panel"><h2>{{ isReviewer ? '工单与订单信息' : '订单信息' }}</h2><template v-if="snapshot"><div class="context-status"><span>当前状态</span><strong>{{ statusLabel(snapshot.case.status) }}</strong></div><dl><dt>商品名称</dt><dd :class="{ 'name-missing': selectedOrderLine && productNameMissing(selectedOrderLine) }">{{ selectedOrderLine ? productTitle(selectedOrderLine) : '暂未提供' }}</dd><dt v-if="selectedOrderLine && variantOf(selectedOrderLine)">商品规格</dt><dd v-if="selectedOrderLine && variantOf(selectedOrderLine)">{{ variantOf(selectedOrderLine) }}</dd><dt>商品类别</dt><dd>{{ selectedOrderLine ? (categoryLabels[selectedOrderLine.category] ?? selectedOrderLine.category) : '暂未提供' }}</dd><dt>订单行</dt><dd>{{ snapshot.case.line_id }}</dd><dt>商品数量</dt><dd>{{ selectedOrderLine?.quantity ?? '暂未提供' }}</dd><dt v-if="selectedOrderLine && paidAtOf(selectedOrderLine)">支付时间</dt><dd v-if="selectedOrderLine && paidAtOf(selectedOrderLine)">{{ formatTimestamp(paidAtOf(selectedOrderLine)!) }}</dd><dt>最近事件</dt><dd>{{ snapshot.timeline.length ? formatTimestamp(snapshot.timeline.at(-1)!.occurred_at) : '暂无事件' }}</dd></dl><details class="technical-details"><summary>查看工单与订单编号</summary><dl><dt>工单编号</dt><dd>{{ snapshot.case.case_id }}</dd><dt>订单编号</dt><dd>{{ snapshot.case.order_id || '未提供' }}</dd><dt>工单版本</dt><dd>{{ snapshot.case.version }}</dd><dt>输入修订</dt><dd>{{ snapshot.case.input_revision }}</dd></dl></details></template><p v-else class="empty">打开工单后显示服务端记录。</p></section>
            <section v-if="snapshot?.authorization" class="panel context-panel authorization-panel"><h2>审核授权</h2><div class="auth-summary"><span class="feature-icon"><Icon name="shield" :size="22" /></span><div><p class="authorization-state">{{ authorizationStatusLabel(snapshot.authorization.status) }}</p><small class="subtle">由服务端管理授权与执行状态</small></div></div><p v-if="selectedOrderLine && validatedRefundAmount(snapshot.proposal) !== null" class="validated-amount">{{ snapshot.authorization.status === 'PENDING_REVIEW' ? '待审退款额' : '方案退款额' }} <strong>{{ formatMinorUnits(validatedRefundAmount(snapshot.proposal)!, selectedOrderLine.currency) }}</strong><small>服务端校验金额；到账以执行结果为准</small></p><details class="technical-details"><summary>查看授权编号与版本</summary><dl><dt>授权编号</dt><dd>{{ snapshot.authorization.authorization_id }}</dd><dt>授权版本</dt><dd>{{ snapshot.authorization.authorization_version }}</dd><dt>对应输入修订</dt><dd>{{ snapshot.authorization.input_revision }}</dd></dl></details><p v-if="snapshot.authorization.input_revision !== snapshot.case.input_revision" class="context-warning">授权对应旧输入修订，需以服务端重新校验为准。</p></section>
            <section v-else-if="isReviewer && snapshot?.case.status === 'PENDING_REVIEW'" class="panel context-panel authorization-panel"><h2>授权状态</h2><p class="context-warning">暂无待审退款授权；Agent 建议不能直接执行退款。</p></section>
            <section v-if="snapshot && selectedOrderLine" class="panel context-panel payment-panel"><h2>金额信息</h2><dl><dt>本行实付</dt><dd>{{ formatMinorUnits(selectedOrderLine.line_paid_amount, selectedOrderLine.currency) }}</dd><dt>退款范围</dt><dd>单订单行 · 全量</dd><dt>交易模式</dt><dd>模拟退款</dd></dl></section>
            <section v-if="snapshot" class="panel context-panel checks-panel"><h2>审核依据</h2><ul class="fact-checks"><li><Icon name="file" /><span>可见材料</span><strong>{{ snapshot.evidence.length }} 项</strong></li><li><Icon name="shield" /><span>具有关联核验的材料</span><strong>{{ verifiedEvidence.size }} 项</strong></li><li><Icon name="check" /><span>方案校验</span><strong>{{ snapshot.proposal?.status === 'VALIDATED' ? '服务端已校验' : '尚未确认' }}</strong></li><li><Icon name="clock" /><span>输入修订</span><strong>第 {{ snapshot.case.input_revision }} 版</strong></li></ul><p class="context-footnote">材料核验与退款授权分别判断</p></section>
          </component>
        </div>
      </main>
    </div>
    <ReviewDialog v-if="profileOpen && account" title="个人资料" :busy="profileBusy" @close="profileOpen = false"><AccountWorkspace embedded :key="account.access_token" :account="account" @saved="updateProfile" @reauthenticate="loginNameChanged" @working="profileBusy = $event" @expired="profileOpen = false; logout()" /></ReviewDialog>
    <ReviewDialog v-if="reviewDecision && reviewTarget" :title="decisionLabels[reviewDecision]" :merchant="true" :busy="busy" @close="closeReview">
      <MerchantDecisionForm v-model="decisionReason" :kind="reviewDecision" :line="reviewLine"><div v-if="reviewDecision === 'APPROVE'" class="dialog-refund-amount">退款金额 <strong>{{ reviewAmount !== null ? formatMinorUnits(reviewAmount, 'CNY') : '金额待核对' }}</strong></div></MerchantDecisionForm><p v-if="error" class="message error" role="alert">{{ error }}</p><div class="dialog-actions"><button type="button" class="secondary-button" :disabled="busy" @click="closeReview">取消</button><button type="button" data-test="confirm-review" :disabled="busy || !decisionReason.trim() || decisionReason.trim().length > 1000" @click="review(reviewDecision)">{{ busy ? '正在提交…' : reviewSubmitLabels[reviewDecision] }}</button></div>
    </ReviewDialog>
  </div>
</template>

<style scoped>
.profile-avatar-button{border:0;background:transparent;padding:0;display:inline-flex;cursor:pointer;border-radius:50%}
.profile-avatar-button:focus-visible{outline:2px solid #205e50;outline-offset:4px}
</style>

<style scoped>.login-account-links{display:flex;justify-content:space-between;gap:16px}.login-account-links button{border:0;background:none;color:#205e50;padding:5px 0;font:inherit;font-size:14px;cursor:pointer}</style>
