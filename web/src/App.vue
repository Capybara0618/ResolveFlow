<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { ApiError, coreApi, type CaseSnapshot, type LoginResponse, type OrderLine, type ReviewItem } from './client'
import { watchCaseEvents } from './events'
import { formatMinorUnits } from './money'
import Icon from './ui/ReviewIcon.vue'
import ReviewDialog from './ui/ReviewDialog.vue'
import ReviewerWorkspace from './ui/ReviewerWorkspace.vue'
import InvestigationSources from './ui/InvestigationSources.vue'
import './ui/workbench.css'

const username = ref('')
const password = ref('')
const account = ref<LoginResponse | null>(null)
const error = ref('')
const notice = ref('')
const busy = ref(false)
const orders = ref<OrderLine[]>([])
const ordersCursor = ref<string | undefined>()
const reviewItems = ref<ReviewItem[]>([])
const reviewCursor = ref<string | undefined>()
const reviewView = ref('REVIEW')
const reviewQuery = ref('')
const selectedLine = ref('')
const description = ref('')
const lookupId = ref('')
const snapshot = ref<CaseSnapshot | null>(null)
const selectedOrderLine = ref<OrderLine | null>(null)
const orderContextState = ref<'idle' | 'loading' | 'unavailable'>('idle')
const evidenceText = ref('')
const questionId = ref('')
const decisionReason = ref('')
type ReviewDecision = 'APPROVE' | 'REJECT' | 'REQUEST_INFO'
const reviewDecision = ref<ReviewDecision | null>(null)
const reviewTarget = ref<CaseSnapshot | null>(null)
const queryOpen = ref(false)
const decisionLabels = { APPROVE: '批准退款授权', REJECT: '拒绝退款申请', REQUEST_INFO: '要求补充信息' }
function beginReview(decision: ReviewDecision) {
  if (!snapshot.value || snapshot.value.authorization?.status !== 'PENDING_REVIEW') return
  reviewTarget.value = snapshot.value
  reviewDecision.value = decision
  decisionReason.value = ''
  error.value = ''
}
function closeReview() { reviewDecision.value = null; reviewTarget.value = null; decisionReason.value = '' }

const verificationReason = ref('')
const streamStatus = ref('未连接')
let streamController: AbortController | null = null
let pendingCreateKey: string | null = null

const isCustomer = computed(() => account.value?.role === 'CUSTOMER')
const isReviewer = computed(() => account.value?.role === 'REVIEWER' || account.value?.role === 'OPERATOR')
const canVerifyEvidence = computed(() => isReviewer.value && !!snapshot.value
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
  EVIDENCE_APPENDED: '客户补充材料', EVIDENCE_REVIEWED: '材料已核验', REVIEW_APPROVED: '审核已批准',
  REVIEW_REJECTED: '审核已拒绝', REVIEW_REQUESTED_INFO: '等待客户补证',
  APPROVAL_REQUIRED: '等待人工审批', AUTHORIZATION_DECIDED: '人工审核决定',
  EXECUTION_UPDATED: '退款执行更新', CASE_CLOSED: '工单已结束',
}
const actionLabels: Record<string, string> = {
  REFUND: '建议全额退款', REQUEST_INFO: '建议补充信息', REJECT: '建议拒绝', MANUAL_REVIEW: '建议人工复核',
}
const proposalAction = (proposal: Record<string, unknown>) =>
  actionLabels[String(proposal.recommended_action ?? '')] ?? '请人工核对方案'
const proposalSourceLabel = (proposal: Record<string, unknown>) =>
  proposal.origin === 'HUMAN' ? '人工方案' : proposal.origin === 'AGENT' ? 'Agent 建议' : '调查建议'
function validatedRefundAmount(proposal?: Record<string, unknown>) {
  const amount = proposal?.recomputed_amount_minor
  return proposal?.status === 'VALIDATED' && typeof amount === 'number' && Number.isSafeInteger(amount) && amount > 0
    ? amount : null
}
function proposalCitations(proposal: Record<string, unknown>) {
  const evidence = Array.isArray(proposal.evidence_refs) ? proposal.evidence_refs : []
  const policies = Array.isArray(proposal.policy_refs) ? proposal.policy_refs : []
  return [
    ...evidence.filter((ref): ref is Record<string, unknown> => !!ref && typeof ref === 'object')
      .map(ref => ({ kind: '证据', detail: String(ref.source_ref ?? ref.observation_id ?? '未提供引用') })),
    ...policies.filter((ref): ref is Record<string, unknown> => !!ref && typeof ref === 'object')
      .map(ref => ({ kind: '政策', detail: `${String(ref.bundle_id ?? '未知政策')} · ${String(ref.rule_id ?? '未知条款')} · v${String(ref.version ?? '?')}` })),
  ]
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
const fail = (cause: unknown) => { error.value = cause instanceof Error ? cause.message : String(cause) }

async function act(work: () => Promise<void>) {
  busy.value = true
  error.value = ''
  notice.value = ''
  try { await work() } catch (cause) { fail(cause) } finally { busy.value = false }
}
async function loadOrders(cursor?: string) {
  const page = await coreApi.orders(token(), cursor)
  orders.value = cursor ? [...orders.value, ...page.items] : page.items
  ordersCursor.value = page.page.next_cursor
}
async function loadReviewQueue(cursor?: string) {
  const page = await coreApi.reviewQueue(token(), cursor, reviewView.value, reviewQuery.value.trim())
  reviewItems.value = cursor ? [...reviewItems.value, ...page.items] : page.items
  reviewCursor.value = page.page.next_cursor
}
function filterQueue() {
  void act(async () => {
    await loadReviewQueue()
    if (reviewItems.value.length) await openCase(reviewItems.value[0].case_id)
    else { closeReview(); stopStream(); snapshot.value = null; selectedOrderLine.value = null }
  })
}
function stopStream() {
  streamController?.abort()
  streamController = null
  streamStatus.value = '未连接'
}
async function refreshCase(caseId: string) {
  const sessionToken = token()
  const next = await coreApi.case(sessionToken, caseId)
  if (lookupId.value === caseId && token() === sessionToken) {
    snapshot.value = next
    if (['CLOSED_SUCCESS', 'CLOSED_REJECTED', 'CANCELLED'].includes(next.case.status)) stopStream()
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
async function openCase(caseId: string) {
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
function login() {
  void act(async () => {
    stopStream()
    const session = await coreApi.login(username.value, password.value)
    account.value = session
    password.value = ''
    orders.value = []; reviewItems.value = []; snapshot.value = null; selectedOrderLine.value = null
    if (session.role === 'CUSTOMER') await loadOrders()
    else {
      await loadReviewQueue()
      if (reviewItems.value.length) await openCase(reviewItems.value[0].case_id)
    }
  })
}
function logout() {
  closeReview(); stopStream(); account.value = null; snapshot.value = null; selectedOrderLine.value = null
  orders.value = []; reviewItems.value = []; error.value = ''
}
function createCase() {
  void act(async () => {
    if (!selectedLine.value || !description.value.trim()) throw new Error('请选择订单行并填写说明')
    pendingCreateKey ??= crypto.randomUUID()
    const created = await coreApi.createCase(token(), selectedLine.value, description.value.trim(), pendingCreateKey)
    pendingCreateKey = null
    description.value = ''
    await openCase(created.case_id)
    notice.value = '工单已创建'
  })
}
function appendEvidence() {
  void act(async () => {
    if (!snapshot.value || !evidenceText.value.trim()) throw new Error('请输入补充材料')
    const caseId = snapshot.value.case.case_id
    await coreApi.appendEvidence(token(), caseId, evidenceText.value.trim(), questionId.value.trim() || undefined)
    evidenceText.value = ''; questionId.value = ''
    await refreshCase(caseId)
    notice.value = '材料已提交，旧版本的决定不可继续使用'
  })
}
function verifyEvidence(evidenceId: string, result: 'CONFIRMED' | 'REFUTED' | 'INCONCLUSIVE') {
  void act(async () => {
    if (!snapshot.value || !verificationReason.value.trim()) throw new Error('请填写核验理由')
    const caseId = snapshot.value.case.case_id
    await coreApi.reviewEvidence(token(), caseId, evidenceId, result, verificationReason.value.trim())
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
      await coreApi.review(token(), current, decision, decisionReason.value.trim())
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        await refreshCase(current.case.case_id)
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
  await act(async () => { await refreshCase(snapshot.value!.case.case_id); await loadReviewQueue() })
}
onUnmounted(stopStream)
</script>

<template>
  <div class="workbench">
    <header class="topbar">
      <div class="brand"><span class="brand-mark" aria-hidden="true"><i /><i /><i /><i /></span><span>ResolveFlow</span></div>
      <span class="demo-tag">本地演示 · 模拟退款</span>
      <div v-if="account" class="session"><span class="avatar">{{ isReviewer ? '审' : '客' }}</span><span class="session-copy"><strong>{{ isReviewer ? '售后审核员' : '客户工作台' }}</strong><small>{{ account.merchant_id }}</small></span>
        <button type="button" class="text-button logout-button" @click="logout">退出<Icon name="arrow" :size="15" /></button></div>
    </header>
    <main v-if="!account" class="login-stage">
      <div class="login-intro"><span class="login-symbol"><Icon name="shield" :size="38" /></span><p class="eyebrow">RESOLVE WITH CONFIDENCE</p><h1>每一次售后，<br />都有据可循。</h1><p>从客户诉求到调查建议，<br />让证据、判断与处理进展清晰可见。</p><div class="login-features"><span><Icon name="file" />证据可追溯</span><span><Icon name="shield" />人工审核</span><span><Icon name="clock" />进展可查看</span></div></div>
      <form class="panel login-panel" @submit.prevent="login">
        <p class="eyebrow">欢迎使用 ResolveFlow</p><h2>登录工作台</h2>
        <p class="muted">使用本地演示账户，继续处理售后事务。</p>
        <label>用户名 <input v-model="username" name="username" autocomplete="username" placeholder="请输入用户名" /></label>
        <label>密码 <input v-model="password" name="password" type="password" autocomplete="current-password" placeholder="请输入密码" /></label>
        <button data-test="login" type="submit" :disabled="busy">{{ busy ? '正在登录…' : '登录工作台' }}<Icon name="arrow" :size="17" /></button>
        <p v-if="error" class="message error" role="alert">{{ error }}</p>
        <small class="login-note"><Icon name="shield" :size="14" />数据与操作范围由账户身份决定</small>
      </form>
    </main>
    <div v-else class="app-shell">
      <nav class="sidebar" aria-label="工作台导航">
        <a v-if="isCustomer" href="#order-panel" class="nav-link current"><Icon name="box" />我的订单行</a>
        <a v-if="isReviewer" href="#queue-panel" class="nav-link" :class="{ current: !queryOpen }" @click="queryOpen = false"><Icon name="queue" />审核队列<span class="nav-count">{{ reviewItems.length }}</span></a>
        <a href="#case-panel" class="nav-link" :class="{ current: queryOpen }" @click="queryOpen = true"><Icon name="search" />工单查询</a>
        <div class="sidebar-note"><p>让售后更简单<br />让每一次服务都有结果</p><small>单订单行 · 全量模拟退款</small><span>© 2026 ResolveFlow</span></div>
      </nav>
      <main class="workspace" :class="{ 'reviewer-workspace': isReviewer }">
        <div v-if="isCustomer" class="page-heading"><div><p class="eyebrow">客户视图</p><h1>发起与跟踪售后工单</h1></div><span class="scope-note">只查看本人订单</span></div>
        <p v-if="error && !reviewDecision" class="message error workspace-message" role="alert">{{ error }}</p>
        <p v-if="notice" class="message success workspace-message" role="status"><Icon name="check" />{{ notice }}</p>
        <div class="columns" :class="{ 'customer-columns': isCustomer, 'reviewer-columns': isReviewer }">
          <section v-if="isCustomer" id="order-panel" class="panel list-panel" aria-label="我的订单行">
            <div class="panel-heading"><h2>我的订单行</h2><span class="count">{{ orders.length }}</span></div>
            <p class="muted">选择一条订单行，提交全额模拟退款诉求。</p>
            <div v-if="orders.length === 0" class="empty"><Icon name="box" :size="30" /><p>暂无可见订单行</p></div>
            <div class="scroll-list" aria-label="可选订单行"><label v-for="line in orders" :key="line.line_id" class="order-row">
              <input v-model="selectedLine" type="radio" name="line" :value="line.line_id" /><span class="order-copy"><strong>{{ line.sku }}</strong><small>{{ line.line_id }} · {{ line.status }}</small><b>{{ formatMinorUnits(line.line_paid_amount, line.currency) }}</b></span>
            </label></div>
            <button v-if="ordersCursor" type="button" class="secondary-button" :disabled="busy" @click="act(() => loadOrders(ordersCursor))">加载更多订单</button>
          </section>
          <section v-if="isReviewer" id="queue-panel" class="panel list-panel" aria-label="审核队列">
            <div class="panel-heading"><h2>审核队列 <span>（{{ reviewItems.length }}）</span></h2><span class="queue-scope">当前商家</span></div>
            <form class="queue-filters" @submit.prevent="filterQueue"><label>处理阶段<select v-model="reviewView" :disabled="busy" @change="filterQueue"><option value="REVIEW">待审核</option><option value="WAITING">待客户补证</option><option value="PROCESSING">调查与退款处理中</option><option value="ATTENTION">结果待确认</option><option value="CLOSED">已结束</option><option value="ALL">全部工单</option></select></label><div class="queue-search"><input v-model="reviewQuery" aria-label="搜索工单" maxlength="100" placeholder="工单号、订单号或问题描述" :disabled="busy" /><button type="submit" class="secondary-button" :disabled="busy">查询</button></div></form>
            <div v-if="reviewItems.length === 0" class="empty"><Icon name="queue" :size="30" /><strong>没有符合条件的工单</strong><p>可切换处理阶段或修改查询条件</p></div>
            <div class="scroll-list" aria-label="工单列表">
              <button v-for="item in reviewItems" :key="item.case_id" type="button" class="queue-row" :aria-pressed="snapshot?.case.case_id === item.case_id"
                :class="{ selected: snapshot?.case.case_id === item.case_id }" :disabled="busy" @click="act(() => openCase(item.case_id))">
                <span class="queue-top"><span class="queue-category"><Icon name="file" :size="14" />退款申请</span><span class="status-tag" :class="{ waiting: item.status === 'PENDING_REVIEW', success: item.status === 'CLOSED_SUCCESS' }">{{ statusLabel(item.status) }}</span></span>
                <strong class="queue-title">{{ headline(item.description) }}</strong><small><Icon name="clock" :size="13" />更新于 {{ formatTimestamp(item.updated_at) }}</small>
              </button>
            </div>
            <div class="list-actions"><button v-if="reviewCursor" type="button" class="secondary-button" :disabled="busy" @click="act(() => loadReviewQueue(reviewCursor))">加载更多</button><button type="button" class="text-button" :disabled="busy" @click="act(() => loadReviewQueue())">刷新队列</button></div>
          </section>
          <section id="case-panel" class="panel case-panel" aria-label="工单内容" :aria-busy="busy">
            <div class="panel-heading case-heading"><h2>{{ isReviewer ? '退款工单' : '工单详情' }}</h2><span v-if="snapshot" class="status-tag" :class="{ waiting: snapshot.case.status === 'PENDING_REVIEW', success: snapshot.case.status === 'CLOSED_SUCCESS' }">{{ statusLabel(snapshot.case.status) }}</span></div>
            <details class="lookup-tools" :open="queryOpen"><summary @click.prevent="queryOpen = !queryOpen"><Icon name="search" :size="13" />按工单编号查询</summary><div class="lookup"><label>工单编号 <input v-model="lookupId" name="case-id" placeholder="输入已知工单编号" /></label><button type="button" class="secondary-button" :disabled="busy || !lookupId.trim()" @click="act(() => openCase(lookupId))">查看工单</button></div></details>
            <div v-if="isCustomer && !snapshot" class="create-panel"><span class="feature-icon"><Icon name="file" :size="26" /></span><p class="eyebrow">新建售后工单</p><h3>发起全额模拟退款</h3><p class="muted">{{ selectedLine ? `已选择订单行 ${selectedLine}` : '先在左侧选择一条订单行' }}</p><label>情况说明 <textarea v-model="description" rows="5" placeholder="描述物流异常或商品损坏情况" /></label><button data-test="create-case" type="button" :disabled="busy" @click="createCase">创建工单<Icon name="arrow" :size="16" /></button></div>
            <div v-else-if="!snapshot" class="case-empty"><Icon name="queue" :size="42" /><strong>{{ busy ? '正在读取工单…' : '选择一条工单，开始审核' }}</strong><p>订单、证据与调查建议将在这里汇集。</p></div>
            <template v-else>
              <div class="case-title"><h3>{{ headline(snapshot.case.description) }}</h3><span class="stream-indicator"><i :class="{ disconnected: streamStatus === '连接失败' }" />{{ streamStatus === '未连接' ? '静态快照' : streamStatus }}</span></div>
              <section v-if="isReviewer" class="case-order" aria-label="订单行摘要"><div class="section-heading"><h3>订单信息</h3><span v-if="snapshot.case.order_id" class="subtle-id" :title="snapshot.case.order_id">订单号：{{ snapshot.case.order_id }}</span></div>
                <div v-if="selectedOrderLine" class="case-order-content"><span class="product-placeholder"><Icon name="box" :size="32" /></span><div class="product-copy"><strong>{{ categoryLabels[selectedOrderLine.category] ?? '订单商品' }}</strong><span>{{ selectedOrderLine.sku }}</span><small>数量 × {{ selectedOrderLine.quantity }}</small></div><div class="case-order-amount"><small>订单已付金额</small><b>{{ formatMinorUnits(selectedOrderLine.line_paid_amount, selectedOrderLine.currency) }}</b></div><div v-if="validatedRefundAmount(snapshot.proposal) !== null" class="case-order-amount refund-amount"><small>{{ snapshot.authorization?.status === 'PENDING_REVIEW' ? '待审退款额' : '方案退款额' }}</small><b>{{ formatMinorUnits(validatedRefundAmount(snapshot.proposal)!, selectedOrderLine.currency) }}</b><small>服务端已校验 · 全额退款</small></div></div>
                <p v-else-if="orderContextState === 'loading'" class="muted skeleton-line">正在读取订单信息…</p><p v-else class="muted">暂无可展示的订单明细</p></section>
              <section v-if="snapshot.case.description" class="customer-issue"><h3>客户问题描述</h3><p>{{ snapshot.case.description }}</p></section>
              <section class="detail-section evidence-section"><div class="section-heading"><h3>证据与材料 <span class="section-count">（{{ snapshot.evidence.length }}）</span></h3><span class="subtle">展开查看完整内容</span></div>
                <p v-if="snapshot.evidence.length === 0" class="evidence-empty"><Icon name="file" />暂无可见材料；不能据此认定证据已核验。</p>
                <div v-if="snapshot.evidence.length" class="evidence-list"><article v-for="item in snapshot.evidence" :key="item.observation_id" class="evidence">
                  <div class="evidence-head"><span class="material-icon"><Icon :name="item.reviewed_evidence_id ? 'shield' : 'file'" :size="22" /></span><div class="evidence-meta"><strong>{{ evidenceLabels[item.evidence_kind] ?? item.evidence_kind }}</strong><span v-if="item.verification_result" class="verification-tag" :class="item.verification_result.toLowerCase()">{{ verificationLabels[item.verification_result] ?? item.verification_result }}</span><span v-else-if="verifiedEvidence.get(item.observation_id)" class="verification-tag" :class="verifiedEvidence.get(item.observation_id)?.toLowerCase()">已核验：{{ verificationLabels[verifiedEvidence.get(item.observation_id)!] }}</span><span v-else class="subtle">待人工核验</span></div></div>
                  <p class="evidence-excerpt">{{ item.content }}</p><details class="evidence-id"><summary>查看材料来源与编号<Icon name="chevron" :size="12" /></summary><p class="full-evidence">{{ item.content }}</p><div>材料编号：{{ item.observation_id }}</div><div>来源引用：{{ item.source_ref || '未提供' }}</div><div v-if="item.observed_at">记录时间：{{ formatTimestamp(item.observed_at) }}</div><div v-if="item.reviewed_evidence_id">核验材料：{{ item.reviewed_evidence_id }}</div></details>
                  <div v-if="canVerifyEvidence && !item.reviewed_evidence_id && !verifiedEvidence.has(item.observation_id)" class="actions verification-actions"><button type="button" class="secondary-button" :disabled="busy" @click="verifyEvidence(item.observation_id, 'CONFIRMED')">确认</button><button type="button" class="secondary-button" :disabled="busy" @click="verifyEvidence(item.observation_id, 'REFUTED')">驳回</button><button type="button" class="secondary-button" :disabled="busy" @click="verifyEvidence(item.observation_id, 'INCONCLUSIVE')">无法判定</button></div>
                </article></div>
                <label v-if="canVerifyEvidence && snapshot.evidence.some(item => !item.reviewed_evidence_id && !verifiedEvidence.has(item.observation_id))" class="verification-reason">核验理由 <input v-model="verificationReason" placeholder="提交核验前填写理由" /></label>
              </section>
              <div class="analysis-grid" :class="{ 'without-proposal': !snapshot.proposal }">
                <section v-if="snapshot.proposal" class="detail-section proposal"><h3>{{ proposalSourceLabel(snapshot.proposal) }}<span class="advice-label">调查结论</span></h3><div class="recommendation"><span class="recommendation-icon"><Icon name="sparkle" :size="21" /></span><strong>{{ proposalAction(snapshot.proposal) }}</strong></div><p v-if="typeof snapshot.proposal.summary === 'string'" class="proposal-summary">{{ snapshot.proposal.summary }}</p>
                  <div v-if="proposalCitations(snapshot.proposal).length" class="citation-list"><strong>引用的政策与证据</strong><div v-for="(citation, index) in proposalCitations(snapshot.proposal).slice(0, 3)" :key="index"><Icon :name="citation.kind === '政策' ? 'file' : 'shield'" :size="15" /><span>{{ citation.kind }}</span><span class="citation-text" :title="citation.detail">{{ citation.detail }}</span></div></div><details class="proposal-details"><summary>查看完整方案与全部引用</summary><pre>{{ JSON.stringify(snapshot.proposal, null, 2) }}</pre></details><small>建议供审核参考，批准授权后进入模拟退款执行。</small>
                </section>
                <section class="detail-section timeline-section"><h3>工单轨迹</h3><p v-if="snapshot.timeline.length === 0" class="empty">暂无轨迹事件</p><ol v-else class="timeline"><li v-for="event in snapshot.timeline.slice(-4)" :key="event.event_id"><time>{{ formatTimestamp(event.occurred_at) }}</time><strong>{{ timelineLabels[event.type] ?? event.type }}</strong></li></ol><details v-if="snapshot.timeline.length" class="timeline-more"><summary>查看全部 {{ snapshot.timeline.length }} 条事件</summary><ol class="timeline"><li v-for="event in snapshot.timeline" :key="event.event_id"><time>{{ formatTimestamp(event.occurred_at) }}</time><strong>{{ timelineLabels[event.type] ?? event.type }}</strong><p>{{ event.summary }}</p></li></ol></details></section>
              </div>
              <InvestigationSources v-if="isReviewer" :token="token()" :snapshot="snapshot" />
              <section v-if="isCustomer && !['EXECUTING', 'RECONCILING', 'CLOSED_SUCCESS', 'CLOSED_REJECTED', 'CANCELLED'].includes(snapshot.case.status)" class="detail-section"><h3>补充材料</h3><label>问题 ID（若在回答追问） <input v-model="questionId" /></label><label>材料文本 <textarea v-model="evidenceText" rows="3" /></label><button data-test="append-evidence" type="button" :disabled="busy" @click="appendEvidence">提交材料</button></section>
              <section v-if="isReviewer && snapshot.authorization?.status === 'PENDING_REVIEW'" class="detail-section review-section"><div class="section-heading"><h3>审核决策</h3><span class="subtle">批准授权后仍需等待独立的退款执行结果</span></div><div class="actions"><button data-test="approve" type="button" :disabled="busy" @click="beginReview('APPROVE')"><Icon name="check" :size="19" />批准授权</button><button type="button" class="secondary-button" :disabled="busy" @click="beginReview('REQUEST_INFO')"><Icon name="file" :size="17" />请求补证</button><button type="button" class="danger-button" :disabled="busy" @click="beginReview('REJECT')"><Icon name="close" :size="19" />拒绝</button></div></section>
              <section v-else-if="isReviewer && snapshot.case.status === 'PENDING_REVIEW'" class="detail-section review-unavailable" aria-label="审核暂不可用"><Icon name="shield" :size="22" /><div><h3>暂无可审核授权</h3><p v-if="snapshot.authorization">当前授权{{ authorizationStatusLabel(snapshot.authorization.status) }}，不能再次审核；请核对工单轨迹与当前结果。</p><p v-else>此工单正在等待人工复核，但服务端尚无待审退款授权。请核对方案与材料；当前不能批准退款。</p></div></section>
              <ReviewerWorkspace v-if="isReviewer" :token="token()" :snapshot="snapshot" :busy="busy" @changed="refreshWorkspace" @working="busy = $event" />
            </template>
          </section>
          <aside class="context-column" aria-label="工单上下文">
            <section class="panel context-panel"><h2>{{ isReviewer ? '工单与订单信息' : '订单信息' }}</h2><template v-if="snapshot"><div class="context-status"><span>当前状态</span><strong>{{ statusLabel(snapshot.case.status) }}</strong></div><dl><dt>商品类别</dt><dd>{{ selectedOrderLine ? (categoryLabels[selectedOrderLine.category] ?? selectedOrderLine.category) : '暂未提供' }}</dd><dt>订单行</dt><dd>{{ snapshot.case.line_id }}</dd><dt>商品数量</dt><dd>{{ selectedOrderLine?.quantity ?? '暂未提供' }}</dd><dt>最近事件</dt><dd>{{ snapshot.timeline.length ? formatTimestamp(snapshot.timeline.at(-1)!.occurred_at) : '暂无事件' }}</dd></dl><details class="technical-details"><summary>查看工单与订单编号</summary><dl><dt>工单编号</dt><dd>{{ snapshot.case.case_id }}</dd><dt>订单编号</dt><dd>{{ snapshot.case.order_id || '未提供' }}</dd><dt>工单版本</dt><dd>{{ snapshot.case.version }}</dd><dt>输入修订</dt><dd>{{ snapshot.case.input_revision }}</dd></dl></details></template><p v-else class="empty">打开工单后显示服务端记录。</p></section>
            <section v-if="snapshot?.authorization" class="panel context-panel authorization-panel"><h2>审核授权</h2><div class="auth-summary"><span class="feature-icon"><Icon name="shield" :size="22" /></span><div><p class="authorization-state">{{ authorizationStatusLabel(snapshot.authorization.status) }}</p><small class="subtle">由服务端管理授权与执行状态</small></div></div><p v-if="selectedOrderLine && validatedRefundAmount(snapshot.proposal) !== null" class="validated-amount">{{ snapshot.authorization.status === 'PENDING_REVIEW' ? '待审退款额' : '方案退款额' }} <strong>{{ formatMinorUnits(validatedRefundAmount(snapshot.proposal)!, selectedOrderLine.currency) }}</strong><small>服务端校验金额；到账以执行结果为准</small></p><details class="technical-details"><summary>查看授权编号与版本</summary><dl><dt>授权编号</dt><dd>{{ snapshot.authorization.authorization_id }}</dd><dt>授权版本</dt><dd>{{ snapshot.authorization.authorization_version }}</dd><dt>对应输入修订</dt><dd>{{ snapshot.authorization.input_revision }}</dd></dl></details><p v-if="snapshot.authorization.input_revision !== snapshot.case.input_revision" class="context-warning">授权对应旧输入修订，需以服务端重新校验为准。</p></section>
            <section v-else-if="isReviewer && snapshot?.case.status === 'PENDING_REVIEW'" class="panel context-panel authorization-panel"><h2>授权状态</h2><p class="context-warning">暂无待审退款授权；Agent 建议不能直接执行退款。</p></section>
            <section v-if="snapshot && selectedOrderLine" class="panel context-panel payment-panel"><h2>金额信息</h2><dl><dt>订单已付金额</dt><dd>{{ formatMinorUnits(selectedOrderLine.line_paid_amount, selectedOrderLine.currency) }}</dd><dt>退款范围</dt><dd>单订单行 · 全量</dd><dt>交易模式</dt><dd>模拟退款</dd></dl><p class="context-footnote">支付渠道与交易流水暂未提供</p></section>
            <section v-if="snapshot" class="panel context-panel checks-panel"><h2>审核依据</h2><ul class="fact-checks"><li><Icon name="file" /><span>可见材料</span><strong>{{ snapshot.evidence.length }} 项</strong></li><li><Icon name="shield" /><span>具有关联核验的材料</span><strong>{{ verifiedEvidence.size }} 项</strong></li><li><Icon name="check" /><span>方案校验</span><strong>{{ snapshot.proposal?.status === 'VALIDATED' ? '服务端已校验' : '尚未确认' }}</strong></li><li><Icon name="clock" /><span>输入修订</span><strong>第 {{ snapshot.case.input_revision }} 版</strong></li></ul><p class="context-footnote">材料核验与退款授权分别判断</p></section>
          </aside>
        </div>
      </main>
    </div>
    <ReviewDialog v-if="reviewDecision && reviewTarget" :title="decisionLabels[reviewDecision]" :busy="busy" @close="closeReview">
      <p class="dialog-case">{{ headline(reviewTarget.case.description) }}</p><p class="subtle">工单 {{ reviewTarget.case.case_id }}</p><label>{{ reviewDecision === 'REQUEST_INFO' ? '需要补充的内容与理由' : '审核理由' }} <textarea v-model="decisionReason" rows="4" placeholder="请写明审核依据或需要补充的材料…" /></label><p class="dialog-notice"><Icon name="shield" :size="16" />本操作提交人工审核决定。批准授权不等于退款到账。</p><p v-if="error" class="message error" role="alert">{{ error }}</p><div class="dialog-actions"><button type="button" class="secondary-button" :disabled="busy" @click="closeReview">取消</button><button type="button" data-test="confirm-review" :disabled="busy || !decisionReason.trim()" @click="review(reviewDecision)">{{ busy ? '正在提交…' : '确认提交' }}</button></div>
    </ReviewDialog>
  </div>
</template>
