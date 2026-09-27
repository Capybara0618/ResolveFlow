<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { coreApi, type CaseSnapshot, type LoginResponse, type OrderLine, type ReviewItem } from './client'
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
const evidenceText = ref('')
const questionId = ref('')
const decisionReason = ref('')
const verificationReason = ref('')
const streamStatus = ref('未连接')
let streamController: AbortController | null = null
let pendingCreateKey: string | null = null

const isCustomer = computed(() => account.value?.role === 'CUSTOMER')
const isReviewer = computed(() => account.value?.role === 'REVIEWER' || account.value?.role === 'OPERATOR')
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
async function openCase(caseId: string) {
  stopStream()
  lookupId.value = caseId.trim()
  snapshot.value = null
  const sessionToken = token()
  const current = await coreApi.case(sessionToken, lookupId.value)
  if (token() !== sessionToken) return
  snapshot.value = current
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
    orders.value = []; reviewItems.value = []; snapshot.value = null
    if (session.role === 'CUSTOMER') await loadOrders()
    else await loadReviewQueue()
  })
}
function logout() {
  stopStream(); account.value = null; snapshot.value = null
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
    await coreApi.review(token(), current, decision, decisionReason.value.trim())
    decisionReason.value = ''
    await refreshCase(current.case.case_id)
    await loadReviewQueue()
    notice.value = '审核决定已提交；批准不等于退款已执行'
  })
}
onUnmounted(stopStream)
</script>

<template>
  <main class="workbench">
    <header>
      <div><p class="eyebrow">ResolveFlow · 核心演示</p><h1>售后工单工作台</h1></div>
      <div v-if="account" class="session"><span>{{ account.role }} · {{ account.merchant_id }}</span>
        <button type="button" @click="logout">退出</button></div>
    </header>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <p v-if="notice" class="message success">{{ notice }}</p>
    <section v-if="!account" class="panel login-panel">
      <h2>登录</h2><p>使用本地演示账户。权限由服务端身份决定。</p>
      <label>用户名 <input v-model="username" name="username" autocomplete="username" /></label>
      <label>密码 <input v-model="password" name="password" type="password" autocomplete="current-password" /></label>
      <button data-test="login" type="button" :disabled="busy" @click="login">登录</button>
    </section>
    <div v-else class="columns">
      <section v-if="isCustomer" class="panel">
        <h2>我的订单行</h2><p>仅显示当前账户可访问的订单行；退款为单行全量。</p>
        <div v-if="orders.length === 0" class="empty">暂无可见订单行</div>
        <label v-for="line in orders" :key="line.line_id" class="order-row">
          <input v-model="selectedLine" type="radio" name="line" :value="line.line_id" />
          <span><strong>{{ line.line_id }}</strong> · {{ line.sku }}<br />
            {{ formatMinorUnits(line.line_paid_amount, line.currency) }} · {{ line.status }}</span>
        </label>
        <button v-if="ordersCursor" type="button" :disabled="busy" @click="act(() => loadOrders(ordersCursor))">更多订单</button>
        <h3>发起退款工单</h3><label>情况说明 <textarea v-model="description" rows="3" /></label>
        <button data-test="create-case" type="button" :disabled="busy" @click="createCase">创建工单</button>
      </section>
      <section v-if="isReviewer" class="panel">
        <h2>待审核工单</h2><p>列表仅来自当前商家的审核队列。</p>
        <div v-if="reviewItems.length === 0" class="empty">暂无待审核项</div>
        <button v-for="item in reviewItems" :key="item.case_id" type="button" class="queue-row"
          @click="act(() => openCase(item.case_id))">{{ item.case_id }} · {{ item.status }} · 行 {{ item.line_id }}</button>
        <button v-if="reviewCursor" type="button" :disabled="busy" @click="act(() => loadReviewQueue(reviewCursor))">更多审核项</button>
        <button type="button" :disabled="busy" @click="act(() => loadReviewQueue())">刷新队列</button>
      </section>
      <section class="panel case-panel">
        <h2>工单与轨迹</h2>
        <label>工单 ID <input v-model="lookupId" name="case-id" placeholder="已知工单 ID" /></label>
        <button type="button" :disabled="busy || !lookupId.trim()" @click="act(() => openCase(lookupId))">查看工单</button>
        <template v-if="snapshot">
          <p><strong>{{ snapshot.case.case_id }}</strong> · {{ snapshot.case.status }} · 修订 {{ snapshot.case.input_revision }}</p>
          <p class="muted">事件流：{{ streamStatus }}。断线按 Last-Event-ID 续读。</p>
          <h3>轨迹</h3><ol class="timeline"><li v-for="event in snapshot.timeline" :key="event.event_id">
            <time>{{ event.occurred_at }}</time> <strong>{{ event.type }}</strong> — {{ event.summary }}
          </li></ol>
          <h3>材料</h3><div v-for="item in snapshot.evidence" :key="item.observation_id" class="evidence">
            <strong>{{ item.evidence_kind }}</strong> · {{ item.observation_id }}<p>{{ item.content }}</p>
            <div v-if="isReviewer" class="actions">
              <button type="button" :disabled="busy" @click="verifyEvidence(item.observation_id, 'CONFIRMED')">确认</button>
              <button type="button" :disabled="busy" @click="verifyEvidence(item.observation_id, 'REFUTED')">驳回</button>
              <button type="button" :disabled="busy" @click="verifyEvidence(item.observation_id, 'INCONCLUSIVE')">无法判定</button>
            </div>
          </div>
          <label v-if="isReviewer">核验理由 <input v-model="verificationReason" /></label>
          <template v-if="snapshot.proposal"><h3>Agent 建议</h3><pre>{{ JSON.stringify(snapshot.proposal, null, 2) }}</pre></template>
          <template v-if="isCustomer && !['EXECUTING', 'RECONCILING', 'CLOSED_SUCCESS', 'CLOSED_REJECTED', 'CANCELLED'].includes(snapshot.case.status)">
            <h3>补充材料</h3><label>问题 ID（若在回答追问） <input v-model="questionId" /></label>
            <label>材料文本 <textarea v-model="evidenceText" rows="3" /></label>
            <button data-test="append-evidence" type="button" :disabled="busy" @click="appendEvidence">提交材料</button>
          </template>
          <template v-if="isReviewer && snapshot.authorization?.status === 'PENDING_REVIEW'">
            <h3>人工审批</h3><p>授权 {{ snapshot.authorization.authorization_id }} · 版本 {{ snapshot.authorization.authorization_version }}</p>
            <label>审核理由 <textarea v-model="decisionReason" rows="2" /></label>
            <div class="actions"><button data-test="approve" type="button" :disabled="busy" @click="review('APPROVE')">批准</button>
              <button type="button" :disabled="busy" @click="review('REJECT')">拒绝</button>
              <button type="button" :disabled="busy" @click="review('REQUEST_INFO')">请求补证</button></div>
          </template>
        </template>
      </section>
    </div>
  </main>
</template>

<style scoped>
.workbench { max-width: 1160px; margin: 0 auto; padding: 28px; color: #192a35; font-family: system-ui, sans-serif; }
header, .session, .actions { display: flex; align-items: center; gap: 12px; justify-content: space-between; }
header { border-bottom: 2px solid #163e53; margin-bottom: 22px; }
h1 { margin: 4px 0 18px; font-size: 2rem; } h2 { margin-top: 0; } h3 { margin-bottom: 10px; }
.eyebrow, .muted { color: #506778; } .eyebrow { font-size: .82rem; letter-spacing: .09em; text-transform: uppercase; }
.columns { display: grid; grid-template-columns: minmax(260px, 1fr) minmax(400px, 1.6fr); gap: 20px; }
.panel { padding: 22px; border: 1px solid #c8d7de; border-radius: 12px; background: #fff; box-shadow: 0 2px 10px #173a4a0b; }
.login-panel { max-width: 390px; } label { display: block; margin: 13px 0; font-weight: 600; }
input:not([type='radio']), textarea { box-sizing: border-box; display: block; width: 100%; margin-top: 6px; padding: 9px; border: 1px solid #9fb4bf; border-radius: 6px; font: inherit; }
button { margin: 5px 5px 5px 0; padding: 9px 14px; background: #15516b; color: white; border: 0; border-radius: 6px; cursor: pointer; }
button:disabled { opacity: .5; cursor: wait; } .order-row { display: flex; align-items: center; gap: 10px; border-top: 1px solid #e5ecef; padding: 10px 0; }
.queue-row { display: block; width: 100%; text-align: left; } .timeline { padding-left: 22px; max-height: 330px; overflow: auto; }
.timeline li { margin-bottom: 10px; } .timeline time { color: #506778; font-size: .83rem; }
.evidence { border-top: 1px solid #dfe8ec; padding: 12px 0; } .evidence p { white-space: pre-wrap; }
.message { padding: 12px; border-radius: 6px; } .error { color: #7c1c1c; background: #fce9e7; }
.success { color: #15523a; background: #e2f3e9; } .empty { color: #61717a; padding: 12px 0; }
pre { white-space: pre-wrap; word-break: break-word; background: #f2f6f8; padding: 12px; border-radius: 6px; }
@media (max-width: 800px) { .columns { grid-template-columns: 1fr; } .workbench { padding: 16px; } }
</style>
