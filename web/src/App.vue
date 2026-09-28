<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { ApiError, coreApi, type CaseSnapshot, type LoginResponse, type OrderLine, type ReviewItem } from './client'
import { watchCaseEvents } from './events'
import { formatMinorUnits } from './money'

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
const selectedLine = ref('')
const description = ref('')
const lookupId = ref('')
const snapshot = ref<CaseSnapshot | null>(null)
const selectedOrderLine = ref<OrderLine | null>(null)
const orderContextState = ref<'idle' | 'loading' | 'unavailable'>('idle')
const evidenceText = ref('')
const questionId = ref('')
const decisionReason = ref('')
const verificationReason = ref('')
const streamStatus = ref('未连接')
let streamController: AbortController | null = null
let pendingCreateKey: string | null = null

const isCustomer = computed(() => account.value?.role === 'CUSTOMER')
const isReviewer = computed(() => account.value?.role === 'REVIEWER' || account.value?.role === 'OPERATOR')
const caseStatusLabels: Record<string, string> = {
  QUEUED: '等待调查', ANALYZING: '调查中', WAITING_CUSTOMER: '待客户补证',
  PENDING_REVIEW: '待人工审核', AUTHORIZED: '已批准待执行', EXECUTING: '退款执行中',
  RECONCILING: '退款对账中', CLOSED_SUCCESS: '退款已完成',
  CLOSED_REJECTED: '已拒绝', CANCELLED: '已取消',
}
const statusLabel = (status: string) => caseStatusLabels[status] ?? status
const categoryLabels: Record<string, string> = { apparel: '服饰商品', electronics: '电子产品', home: '家居商品', beauty: '美妆商品' }
const timelineLabels: Record<string, string> = {
  CASE_CREATED: '工单已创建', AGENT_STARTED: 'Agent 开始调查', PROPOSAL_READY: '调查建议已生成',
  EVIDENCE_APPENDED: '客户补充材料', EVIDENCE_REVIEWED: '材料已核验', REVIEW_APPROVED: '审核已批准',
  REVIEW_REJECTED: '审核已拒绝', REVIEW_REQUESTED_INFO: '等待客户补证',
}
const actionLabels: Record<string, string> = {
  REFUND: '建议全额退款', REQUEST_INFO: '建议补充信息', REJECT: '建议拒绝', MANUAL_REVIEW: '建议人工复核',
}
const proposalAction = (proposal: Record<string, unknown>) =>
  actionLabels[String(proposal.recommended_action ?? '')] ?? '请人工核对方案'
function headline(value?: string) {
  const text = value?.trim().replace(/\s+/g, ' ') || '退款申请'
  return text.length > 44 ? `${text.slice(0, 44)}…` : text
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
  const page = await coreApi.reviewQueue(token(), cursor)
  reviewItems.value = cursor ? [...reviewItems.value, ...page.items] : page.items
  reviewCursor.value = page.page.next_cursor
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
  stopStream()
  lookupId.value = caseId.trim()
  snapshot.value = null
  selectedOrderLine.value = null
  orderContextState.value = 'idle'
  const sessionToken = token()
  const current = await coreApi.case(sessionToken, lookupId.value)
  if (token() !== sessionToken) return
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
    else await loadReviewQueue()
  })
}
function logout() {
  stopStream(); account.value = null; snapshot.value = null; selectedOrderLine.value = null
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
    notice.value = '核验结果已记录'
  })
}
function review(decision: 'APPROVE' | 'REJECT' | 'REQUEST_INFO') {
  void act(async () => {
    if (!snapshot.value || !decisionReason.value.trim()) throw new Error('请填写审核理由')
    const current = snapshot.value
    try {
      await coreApi.review(token(), current, decision, decisionReason.value.trim())
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        await refreshCase(current.case.case_id)
        throw new Error('工单或授权已变化，页面已重新加载，请核对后再决定')
      }
      throw cause
    }
    decisionReason.value = ''
    await refreshCase(current.case.case_id)
    await loadReviewQueue()
    notice.value = '审核决定已提交；批准不等于退款已执行'
  })
}
onUnmounted(stopStream)
</script>

<template>
  <div class="workbench">
    <header class="topbar">
      <div class="brand"><span class="brand-mark" aria-hidden="true">R</span><span>ResolveFlow</span><span class="demo-tag">核心演示</span></div>
      <div v-if="account" class="session"><span class="role-pill">{{ account.role }}</span><span class="merchant">{{ account.merchant_id }}</span>
        <button type="button" class="text-button" @click="logout">退出登录</button></div>
    </header>
    <main v-if="!account" class="login-stage">
      <section class="panel login-panel">
        <p class="eyebrow">售后调查与退款 Agent</p><h1>登录工作台</h1>
        <p class="muted">使用本地演示账户。可见数据与操作由服务端身份决定。</p>
        <label>用户名 <input v-model="username" name="username" autocomplete="username" /></label>
        <label>密码 <input v-model="password" name="password" type="password" autocomplete="current-password" /></label>
        <button data-test="login" type="button" :disabled="busy" @click="login">登录</button>
      </section>
    </main>
    <div v-else class="app-shell">
      <nav class="sidebar" aria-label="工作台导航">
        <p class="sidebar-caption">工作空间</p>
        <a v-if="isCustomer" href="#order-panel" class="nav-link">我的订单行</a>
        <a v-if="isReviewer" href="#queue-panel" class="nav-link">审核队列</a>
        <a href="#case-panel" class="nav-link">工单查询</a>
        <div class="sidebar-note">单订单行 · 全量模拟退款</div>
      </nav>
      <main class="workspace">
        <div class="page-heading"><div><p class="eyebrow">{{ isCustomer ? '客户视图' : '商家审核视图' }}</p>
          <h1>{{ isCustomer ? '发起与跟踪售后工单' : '审核工作台' }}</h1></div>
          <span class="scope-note">{{ isCustomer ? '只查看本人订单' : '只查看当前商家待审工单' }}</span></div>
        <p v-if="error" class="message error" role="alert">{{ error }}</p>
        <p v-if="notice" class="message success" role="status">{{ notice }}</p>
        <div class="columns" :class="{ 'customer-columns': isCustomer }">
          <section v-if="isCustomer" id="order-panel" class="panel list-panel" aria-label="我的订单行">
            <div class="panel-heading"><h2>我的订单行</h2><span class="count">{{ orders.length }}</span></div>
            <p class="muted">选择一条订单行，提交全额模拟退款诉求。</p>
            <div v-if="orders.length === 0" class="empty">暂无可见订单行</div>
            <div class="scroll-list" aria-label="可选订单行">
              <label v-for="line in orders" :key="line.line_id" class="order-row">
                <input v-model="selectedLine" type="radio" name="line" :value="line.line_id" />
                <span class="order-copy"><strong>{{ line.sku }}</strong><small>{{ line.line_id }} · {{ line.status }}</small>
                  <b>{{ formatMinorUnits(line.line_paid_amount, line.currency) }}</b></span>
              </label>
            </div>
            <button v-if="ordersCursor" type="button" class="secondary-button" :disabled="busy" @click="act(() => loadOrders(ordersCursor))">加载更多订单</button>
          </section>
          <section v-if="isReviewer" id="queue-panel" class="panel list-panel" aria-label="审核队列">
            <div class="panel-heading"><h2>审核队列</h2><span class="count">{{ reviewItems.length }}</span></div>
            <p class="muted">当前商家的待审授权</p>
            <div v-if="reviewItems.length === 0" class="empty">暂无待审核项</div>
            <div class="scroll-list" aria-label="待审工单列表">
              <button v-for="item in reviewItems" :key="item.case_id" type="button" class="queue-row"
                :class="{ selected: snapshot?.case.case_id === item.case_id }" @click="act(() => openCase(item.case_id))">
                <span class="queue-top"><strong class="queue-title">{{ headline(item.description) }}</strong><span class="status-tag waiting">待审核</span></span>
                <small>退款申请 · {{ formatTimestamp(item.updated_at) }}</small>
              </button>
            </div>
            <div class="list-actions"><button v-if="reviewCursor" type="button" class="secondary-button" :disabled="busy" @click="act(() => loadReviewQueue(reviewCursor))">加载更多</button>
              <button type="button" class="text-button" :disabled="busy" @click="act(() => loadReviewQueue())">刷新队列</button></div>
          </section>
          <section id="case-panel" class="panel case-panel" aria-label="工单内容">
            <div class="panel-heading"><div><p class="eyebrow">CASE FILE</p><h2>工单详情</h2></div>
              <span v-if="snapshot" class="status-tag">{{ statusLabel(snapshot.case.status) }}</span></div>
            <details class="lookup-tools"><summary>按工单编号查询</summary><div class="lookup"><label>工单编号 <input v-model="lookupId" name="case-id" placeholder="输入已知工单编号" /></label>
              <button type="button" class="secondary-button" :disabled="busy || !lookupId.trim()" @click="act(() => openCase(lookupId))">查看工单</button></div></details>
            <div v-if="isCustomer && !snapshot" class="create-panel"><p class="eyebrow">新建售后工单</p><h3>发起全额模拟退款</h3>
              <p class="muted">{{ selectedLine ? `已选择订单行 ${selectedLine}` : '先在左侧选择一条订单行' }}</p>
              <label>情况说明 <textarea v-model="description" rows="5" placeholder="描述物流异常或商品损坏情况" /></label>
              <button data-test="create-case" type="button" :disabled="busy" @click="createCase">创建工单</button></div>
            <div v-else-if="!snapshot" class="case-empty"><strong>选择或查询工单</strong><p>工单状态、证据与调查轨迹将在这里显示。</p></div>
            <template v-else>
              <div class="case-title"><div><p class="eyebrow">客户诉求</p><h3>{{ headline(snapshot.case.description) }}</h3><p>退款申请 · {{ statusLabel(snapshot.case.status) }}</p></div>
                <span class="stream-indicator">事件流：{{ streamStatus }}</span></div>
              <section v-if="snapshot.case.description" class="customer-issue"><h3>问题描述</h3><p>{{ snapshot.case.description }}</p></section>
              <section class="detail-section"><div class="section-heading"><h3>证据与材料</h3><span class="count">{{ snapshot.evidence.length }}</span></div>
                <p v-if="snapshot.evidence.length === 0" class="empty">暂无可见证据</p>
                <article v-for="item in snapshot.evidence" :key="item.observation_id" class="evidence">
                  <div class="evidence-meta"><strong>{{ item.evidence_kind }}</strong><small>{{ item.observation_id }}</small></div><p>{{ item.content }}</p>
                  <div v-if="isReviewer" class="actions">
                    <button type="button" class="secondary-button" :disabled="busy" @click="verifyEvidence(item.observation_id, 'CONFIRMED')">确认</button>
                    <button type="button" class="secondary-button" :disabled="busy" @click="verifyEvidence(item.observation_id, 'REFUTED')">驳回</button>
                    <button type="button" class="secondary-button" :disabled="busy" @click="verifyEvidence(item.observation_id, 'INCONCLUSIVE')">无法判定</button>
                  </div>
                </article>
                <label v-if="isReviewer && snapshot.evidence.length">核验理由 <input v-model="verificationReason" placeholder="提交核验前填写理由" /></label>
              </section>
              <section v-if="snapshot.proposal" class="detail-section proposal"><p class="eyebrow">调查结论</p><h3>Agent 建议：{{ proposalAction(snapshot.proposal) }}</h3>
                <p v-if="typeof snapshot.proposal.summary === 'string'">{{ snapshot.proposal.summary }}</p>
                <details><summary>查看完整方案与引用</summary><pre>{{ JSON.stringify(snapshot.proposal, null, 2) }}</pre></details>
                <small>建议仅供参考，退款权限与金额以 Java 服务端校验为准。</small>
              </section>
              <section class="detail-section"><h3>工单轨迹</h3><p v-if="snapshot.timeline.length === 0" class="empty">暂无轨迹事件</p>
                <ol v-else class="timeline"><li v-for="event in snapshot.timeline" :key="event.event_id">
                  <time>{{ formatTimestamp(event.occurred_at) }}</time><strong>{{ timelineLabels[event.type] ?? event.type }}</strong><p>{{ event.summary }}</p>
                </li></ol>
              </section>
              <section v-if="isCustomer && !['EXECUTING', 'RECONCILING', 'CLOSED_SUCCESS', 'CLOSED_REJECTED', 'CANCELLED'].includes(snapshot.case.status)" class="detail-section">
                <h3>补充材料</h3><label>问题 ID（若在回答追问） <input v-model="questionId" /></label>
                <label>材料文本 <textarea v-model="evidenceText" rows="3" /></label>
                <button data-test="append-evidence" type="button" :disabled="busy" @click="appendEvidence">提交材料</button>
              </section>
              <section v-if="isReviewer && snapshot.authorization?.status === 'PENDING_REVIEW'" class="detail-section review-section">
                <p class="eyebrow">人工决策</p><h3>审核授权</h3><p class="muted">批准授权后仍需等待独立的退款执行结果。</p>
                <label>审核理由 <textarea v-model="decisionReason" rows="2" /></label>
                <div class="actions"><button data-test="approve" type="button" :disabled="busy" @click="review('APPROVE')">批准授权</button>
                  <button type="button" class="secondary-button" :disabled="busy" @click="review('REQUEST_INFO')">请求补证</button>
                  <button type="button" class="danger-button" :disabled="busy" @click="review('REJECT')">拒绝</button></div>
              </section>
            </template>
          </section>
          <aside class="context-column" aria-label="工单上下文">
            <section class="panel context-panel"><h2>订单信息</h2>
              <template v-if="snapshot"><div v-if="selectedOrderLine" class="order-summary">
                <strong>{{ categoryLabels[selectedOrderLine.category] ?? '订单商品' }}</strong><span>数量 {{ selectedOrderLine.quantity }} · SKU {{ selectedOrderLine.sku }}</span>
                <b>{{ formatMinorUnits(selectedOrderLine.line_paid_amount, selectedOrderLine.currency) }}</b>
                <small>订单已付金额；退款金额由服务端决定</small></div>
                <p v-else-if="orderContextState === 'loading'" class="muted">正在读取订单信息…</p>
                <p v-else class="muted">暂无可展示的订单明细</p>
                <details class="technical-details"><summary>查看工单与订单编号</summary><dl><dt>工单编号</dt><dd>{{ snapshot.case.case_id }}</dd><dt>订单编号</dt><dd>{{ snapshot.case.order_id || '未提供' }}</dd>
                  <dt>订单行编号</dt><dd>{{ snapshot.case.line_id }}</dd><dt>工单版本</dt><dd>{{ snapshot.case.version }}</dd>
                  <dt>输入修订</dt><dd>{{ snapshot.case.input_revision }}</dd></dl></details></template>
              <p v-else class="empty">打开工单后显示服务端记录。</p>
            </section>
            <section v-if="snapshot?.authorization" class="panel context-panel"><h2>审核授权</h2><p class="authorization-state">{{ statusLabel(snapshot.authorization.status) }}</p>
              <details class="technical-details"><summary>查看授权编号与版本</summary><dl><dt>授权编号</dt><dd>{{ snapshot.authorization.authorization_id }}</dd>
              <dt>授权版本</dt><dd>{{ snapshot.authorization.authorization_version }}</dd>
              <dt>对应输入修订</dt><dd>{{ snapshot.authorization.input_revision }}</dd></dl></details>
              <p v-if="snapshot.authorization.input_revision !== snapshot.case.input_revision" class="context-warning">授权对应旧输入修订，需以服务端重新校验为准。</p>
            </section>
          </aside>
        </div>
      </main>
    </div>
    <p v-if="!account && error" class="message error login-error" role="alert">{{ error }}</p>
  </div>
</template>

<style scoped>
.workbench { --surface: #fff; --canvas: #f8fafc; --ink: #0f172a; --muted: #64748b; --line: #e2e8f0; --blue: #2563eb; min-height: 100vh; background: var(--canvas); color: var(--ink); font-family: Inter, "Microsoft YaHei", "PingFang SC", system-ui, sans-serif; font-size: 14px; }
.workbench * { box-sizing: border-box; }
.topbar { height: 68px; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 0 28px; background: var(--surface); border-bottom: 1px solid var(--line); }
.brand, .session, .panel-heading, .queue-top, .actions, .list-actions, .case-title, .section-heading { display: flex; align-items: center; gap: 10px; }
.brand { color: #102a56; font-size: 18px; font-weight: 750; letter-spacing: -.025em; white-space: nowrap; }
.brand-mark { width: 30px; height: 30px; display: grid; place-items: center; border-radius: 9px; background: var(--blue); color: #fff; font-size: 17px; }
.demo-tag, .role-pill, .scope-note, .status-tag, .count { display: inline-flex; align-items: center; border-radius: 999px; font-size: 12px; font-weight: 650; white-space: nowrap; }
.demo-tag { padding: 4px 8px; background: #eff6ff; color: #1d4ed8; letter-spacing: 0; }
.session { color: var(--muted); }
.role-pill { padding: 5px 9px; background: #f1f5f9; color: #475569; }
.app-shell { display: grid; grid-template-columns: 192px minmax(0, 1fr); min-height: calc(100vh - 68px); }
.sidebar { display: flex; flex-direction: column; gap: 6px; padding: 30px 12px 20px; background: var(--surface); border-right: 1px solid var(--line); }
.sidebar-caption, .eyebrow { margin: 0; color: #8291a5; font-size: 11px; font-weight: 750; letter-spacing: .12em; text-transform: uppercase; }
.sidebar-caption { padding: 0 12px 8px; }
.nav-link { display: block; padding: 11px 13px; border-radius: 9px; color: #475569; font-weight: 650; text-decoration: none; }
.nav-link:hover, .nav-link:focus-visible { background: #eff6ff; color: #1d4ed8; }
.sidebar-note { margin: auto 8px 0; padding-top: 18px; border-top: 1px solid var(--line); color: var(--muted); font-size: 12px; line-height: 1.6; }
.workspace { min-width: 0; padding: 30px clamp(18px, 2.5vw, 42px) 48px; }
.page-heading { display: flex; justify-content: space-between; align-items: end; gap: 16px; margin-bottom: 24px; }
h1, h2, h3, p { margin-top: 0; }
h1 { margin: 7px 0 0; font-size: clamp(24px, 2vw, 30px); letter-spacing: -.035em; }
h2 { margin-bottom: 0; font-size: 17px; letter-spacing: -.02em; }
h3 { margin-bottom: 13px; font-size: 15px; }
.scope-note { padding: 8px 11px; background: #eaf1ff; color: #2454a6; }
.columns { display: grid; grid-template-columns: minmax(240px, 290px) minmax(350px, 1fr) minmax(230px, 280px); align-items: start; gap: 16px; }
.panel { min-width: 0; padding: 20px; background: var(--surface); border: 1px solid var(--line); border-radius: 14px; box-shadow: 0 6px 24px #0f172a06; }
.panel-heading { justify-content: space-between; margin-bottom: 12px; }
.count { min-width: 24px; justify-content: center; padding: 4px 8px; background: #f1f5f9; color: #475569; }
.muted, .empty { color: var(--muted); line-height: 1.6; }
.empty { padding: 22px 8px; text-align: center; background: #f8fafc; border-radius: 9px; }
.list-panel > .muted { margin-bottom: 16px; font-size: 12px; }
.scroll-list { max-height: 380px; padding-right: 4px; overflow-y: auto; scrollbar-color: #cbd5e1 transparent; }
.queue-row { display: block; width: 100%; margin: 0 0 8px; padding: 13px; border: 1px solid var(--line); border-radius: 10px; background: #fff; color: var(--ink); text-align: left; }
.queue-row:hover, .queue-row.selected { border-color: #93b4ff; background: #f4f8ff; }
.queue-row small, .order-copy small { display: block; margin-top: 8px; color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.queue-top { justify-content: space-between; gap: 6px; }
.queue-top strong { min-width: 0; overflow-wrap: anywhere; }
.queue-title { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-height: 1.45; }
.status-tag { padding: 5px 9px; background: #f1f5f9; color: #475569; }
.status-tag.waiting { background: #fff7ed; color: #b45309; }
.list-actions { flex-wrap: wrap; justify-content: space-between; margin-top: 14px; }
.order-row { display: flex; gap: 10px; align-items: start; padding: 13px 2px; border-bottom: 1px solid var(--line); font-weight: 400; cursor: pointer; }
.order-row input { margin-top: 4px; accent-color: var(--blue); }
.order-copy { min-width: 0; }
.order-copy b { display: block; margin-top: 7px; color: #1d4ed8; }
.case-panel { padding: 24px; }
.lookup { display: flex; align-items: end; gap: 9px; padding-bottom: 22px; border-bottom: 1px solid var(--line); }
.lookup-tools { padding: 5px 0 12px; border-bottom: 1px solid var(--line); }
.lookup-tools > summary, .technical-details > summary { color: #41618f; font-size: 12px; font-weight: 650; cursor: pointer; }
.lookup-tools .lookup { padding: 10px 0 0; border: 0; }
.lookup label { flex: 1; min-width: 0; margin: 0; }
.create-panel { padding-top: 28px; }
.create-panel h3 { margin: 8px 0 10px; font-size: 19px; }
.create-panel .muted { margin-bottom: 24px; }
.case-empty { padding: 80px 12px; text-align: center; color: var(--muted); }
.case-empty strong { display: block; margin-bottom: 10px; color: #334155; font-size: 17px; }
.case-title { justify-content: space-between; align-items: start; flex-wrap: wrap; gap: 10px; padding: 21px 0; }
.case-title h3 { margin-bottom: 7px; font-size: 20px; overflow-wrap: anywhere; }
.case-title .eyebrow { margin-bottom: 8px; }
.case-title p { margin-bottom: 0; color: var(--muted); }
.customer-issue { padding: 17px 18px; margin-bottom: 20px; border-radius: 10px; background: #f4f7fb; }
.customer-issue h3 { margin-bottom: 8px; }
.customer-issue p { margin-bottom: 0; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.stream-indicator { color: #2563eb; font-size: 12px; }
.detail-section { padding: 22px 0; border-top: 1px solid var(--line); }
.detail-section:last-child { padding-bottom: 0; }
.section-heading { justify-content: space-between; }
.evidence { padding: 14px; margin-bottom: 10px; border: 1px solid var(--line); border-radius: 10px; }
.evidence-meta { display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.evidence-meta small { color: var(--muted); overflow-wrap: anywhere; }
.evidence p { margin: 12px 0 0; white-space: pre-wrap; line-height: 1.65; }
.evidence .actions { margin-top: 13px; }
.proposal { padding: 20px; margin: 0 -4px 12px; border: 1px solid #c9dcff; border-radius: 12px; background: #f4f8ff; }
.proposal h3 { margin: 6px 0 10px; color: #1e40af; font-size: 18px; }
.proposal p { line-height: 1.7; }
.proposal small { display: block; margin-top: 13px; color: #52647f; }
.proposal summary { color: #1d4ed8; cursor: pointer; font-weight: 650; }
pre { max-height: 360px; overflow: auto; padding: 13px; background: #fff; border: 1px solid var(--line); border-radius: 8px; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; }
.timeline { margin: 0; padding: 0 0 0 21px; border-left: 1px solid #cbd5e1; list-style: none; }
.timeline li { position: relative; margin-bottom: 20px; }
.timeline li::before { position: absolute; left: -26px; top: 4px; width: 9px; height: 9px; background: var(--blue); border: 2px solid #fff; border-radius: 50%; box-shadow: 0 0 0 1px #93c5fd; content: ''; }
.timeline time { display: block; margin-bottom: 5px; color: var(--muted); font-size: 12px; }
.timeline p { margin: 5px 0 0; color: #475569; line-height: 1.55; }
.review-section { padding: 20px; border: 1px solid #bfdbfe; border-radius: 11px; background: #f8fbff; }
.context-column { display: grid; gap: 14px; }
.context-panel h2 { padding-bottom: 14px; border-bottom: 1px solid var(--line); }
.order-summary { display: grid; gap: 7px; padding: 7px 0 12px; }
.order-summary strong { font-size: 15px; overflow-wrap: anywhere; }
.order-summary span, .order-summary small { color: var(--muted); font-size: 12px; }
.order-summary b { color: #1d4ed8; font-size: 20px; }
.technical-details { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--line); }
.technical-details dl { margin-top: 14px; }
.authorization-state { margin: 14px 0 4px; color: #1d4ed8; font-weight: 700; }
dl { display: grid; grid-template-columns: minmax(85px, auto) minmax(0, 1fr); gap: 14px 6px; margin-bottom: 0; font-size: 12px; }
dt { color: var(--muted); } dd { margin: 0; text-align: right; overflow-wrap: anywhere; font-weight: 650; }
.context-warning { margin: 16px 0 0; padding: 10px; border-radius: 8px; background: #fff7ed; color: #9a3412; line-height: 1.5; font-size: 12px; }
label { display: block; margin: 14px 0; font-weight: 650; }
input:not([type='radio']), textarea { display: block; width: 100%; margin-top: 7px; padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 8px; background: #fff; color: var(--ink); font: inherit; }
textarea { resize: vertical; }
input:focus-visible, textarea:focus-visible, button:focus-visible, a:focus-visible, summary:focus-visible { outline: 2px solid #60a5fa; outline-offset: 2px; }
button { padding: 10px 14px; border: 1px solid var(--blue); border-radius: 8px; background: var(--blue); color: #fff; font: inherit; font-weight: 650; cursor: pointer; }
button:disabled { opacity: .55; cursor: wait; }
.secondary-button { border-color: #cbd5e1; background: #fff; color: #334155; }
.text-button { border-color: transparent; background: transparent; color: #1d4ed8; }
.danger-button { border-color: #fecaca; background: #fff; color: #b91c1c; }
.actions { flex-wrap: wrap; }
.message { margin: 0 0 16px; padding: 12px 14px; border-radius: 9px; }
.error { background: #fef2f2; color: #991b1b; } .success { background: #ecfdf5; color: #166534; }
.login-stage { display: grid; place-items: center; min-height: calc(100vh - 68px); padding: 24px; }
.login-panel { width: min(100%, 430px); padding: 36px; }
.login-panel h1 { margin-bottom: 9px; } .login-panel .muted { margin-bottom: 25px; }
.login-panel button { width: 100%; margin-top: 12px; }
.login-error { position: fixed; left: 50%; bottom: 24px; width: min(90vw, 430px); transform: translateX(-50%); box-shadow: 0 10px 30px #0f172a20; }
@media (max-width: 1220px) { .columns { grid-template-columns: minmax(230px, 290px) minmax(360px, 1fr); } .context-column { grid-column: 2; } }
@media (max-width: 850px) { .app-shell { display: block; } .sidebar { flex-direction: row; align-items: center; gap: 8px; padding: 8px 16px; border-right: 0; border-bottom: 1px solid var(--line); } .sidebar-caption, .sidebar-note { display: none; } .workspace { padding: 24px 16px; } .columns { grid-template-columns: 1fr; } .context-column { grid-column: auto; } .page-heading { align-items: start; } }
@media (max-width: 600px) { .topbar { padding: 0 16px; } .brand { font-size: 16px; } .demo-tag, .merchant, .scope-note { display: none; } .page-heading { margin-bottom: 18px; } .case-panel { padding: 18px; } .lookup { flex-wrap: wrap; } .lookup label { flex-basis: 100%; } .lookup button { width: 100%; } .review-section { padding: 16px; } }
</style>
