<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { CaseCollaboration, CaseSnapshot, OrderLine, ReviewContext } from '../client'
import { formatMinorUnits } from '../money'
import AftercareProduct from './AftercareProduct.vue'
import ReviewerWorkspace from './ReviewerWorkspace.vue'
import InvestigationSources from './InvestigationSources.vue'
import PolicyCitations from './PolicyCitations.vue'
import Icon from './ReviewIcon.vue'

const props = defineProps<{
  token: string; snapshot: CaseSnapshot; line: OrderLine | null; busy: boolean
  productState: string; fulfillment: string; tradeState: string
  context: ReviewContext | null; collaboration: CaseCollaboration | null
  contextLoading: boolean; contextError: string; statusLabel: string
}>()
const emit = defineEmits<{
  back: []; order: []; retryProduct: []; retryTrade: []; refresh: []; working: [value: boolean]; expired: []
  review: [decision: 'APPROVE' | 'REQUEST_INFO' | 'REJECT']
}>()
const detailsOpen = ref(false)
const focusKey = ref<string | null>(null)
const focusNonce = ref(0)
const detailsPanel = ref<HTMLElement | null>(null)
watch(() => props.snapshot.case.case_id, () => { detailsOpen.value = false; focusKey.value = null })
watch(detailsOpen, open => { if (!open) focusKey.value = null })
const proposal = computed(() => props.snapshot.proposal)
const stale = computed(() => proposal.value?.status === 'STALE'
  || (typeof proposal.value?.input_revision === 'number' && proposal.value.input_revision !== props.snapshot.case.input_revision))
const oldAuthorization = computed(() => !!props.snapshot.authorization
  && props.snapshot.authorization.input_revision !== props.snapshot.case.input_revision)
const unknown = computed(() => props.context?.execution?.outcome === 'UNKNOWN' || props.snapshot.case.status === 'RECONCILING')
const finished = computed(() => ['CLOSED_SUCCESS', 'CLOSED_REJECTED', 'CANCELLED'].includes(props.snapshot.case.status))
const frozen = computed(() => unknown.value || finished.value || ['AUTHORIZED', 'EXECUTING'].includes(props.snapshot.case.status)
  || props.snapshot.authorization?.status === 'CONSUMED')
const contextReady = computed(() => !props.contextLoading && !props.contextError && !!props.context
  && props.context.case_version === props.snapshot.case.version && props.context.input_revision === props.snapshot.case.input_revision
  && props.collaboration?.case_id === props.snapshot.case.case_id && props.collaboration.is_owner)
const canReview = computed(() => contextReady.value && !frozen.value && !oldAuthorization.value && !stale.value
  && props.snapshot.case.status === 'PENDING_REVIEW' && props.snapshot.authorization?.status === 'PENDING_REVIEW')
const actionsAvailable = computed(() => contextReady.value && !frozen.value)
const actionLabels: Record<string, string> = { REFUND: '建议批准退款', REJECT: '建议拒绝申请', REQUEST_INFO: '建议补充说明', MANUAL_REVIEW: '建议人工复核' }
const currentFailure = computed(() => props.snapshot.case.status === 'PENDING_REVIEW'
  && [...props.snapshot.timeline].reverse().find(event => event.revision === props.snapshot.case.input_revision
    && ['AGENT_STARTED', 'AGENT_FAILED', 'PROPOSAL_READY'].includes(event.type))?.type === 'AGENT_FAILED')
const awaitingVerification = computed(() => !currentFailure.value && !stale.value && !frozen.value
  && proposal.value?.status === 'VALIDATED' && proposal.value.recommended_action === 'MANUAL_REVIEW')
const unverifiedStatement = computed(() => props.snapshot.evidence.some(item => item.evidence_kind === 'CUSTOMER_STATEMENT'
  && !props.snapshot.evidence.some(check => check.reviewed_evidence_id === item.observation_id && check.verification_result)))
const advice = computed(() => currentFailure.value ? '本次调查未完成' : stale.value ? '旧建议已失效'
  : awaitingVerification.value ? '等待商家核验' : actionLabels[String(proposal.value?.recommended_action)] || '等待调查建议')
type Finding = { kind: string; text: string }
const findings = computed(() => Array.isArray(proposal.value?.review_findings)
  ? proposal.value.review_findings.filter((value): value is Finding => !!value && typeof value === 'object'
    && ['FACT', 'INFERENCE', 'CONFLICT'].includes(value.kind) && typeof value.text === 'string') : [])
const conflicts = computed(() => findings.value.filter(value => value.kind === 'CONFLICT'))
const missing = computed(() => Array.isArray(proposal.value?.missing_evidence)
  ? proposal.value.missing_evidence.filter((value): value is string => typeof value === 'string') : [])
const reasons = computed(() => findings.value.filter(value => value.kind !== 'CONFLICT').slice(0, 3))
const refs = (key: string) => Array.isArray(proposal.value?.[key]) ? proposal.value![key] as unknown[] : []
const amount = computed(() => props.context?.execution?.amount_minor ?? props.line?.line_paid_amount ?? null)
const executionText = computed(() => {
  if (unknown.value) return '退款结果待确认，请勿重复发起。'
  if (props.context?.execution?.outcome === 'FAILED') return '模拟退款明确失败，请核对原退款记录。'
  if (props.snapshot.case.status === 'CLOSED_SUCCESS') return '模拟退款已完成'
  if (props.snapshot.case.status === 'CLOSED_REJECTED') return '申请已拒绝'
  if (props.snapshot.case.status === 'CANCELLED') return '客户已取消申请'
  if (frozen.value) return '退款已进入处理，请等待原退款结果。'
  if (props.snapshot.case.status === 'WAITING_CUSTOMER') return '等待客户补充说明，收到后会重新调查。'
  if (props.snapshot.case.status === 'QUEUED') return '调查已排队，可先核对客户申请。'
  if (props.snapshot.case.status === 'ANALYZING') return 'Agent正在调查，生成建议后再决定。'
  if (currentFailure.value) return '本次调查未完成，请商家核对原始材料并继续处理。'
  if (awaitingVerification.value) return '请核验客户陈述并记录结论，之后会重新调查。'
  return ''
})
async function openDetails() {
  detailsOpen.value = true
  await nextTick()
  detailsPanel.value?.scrollIntoView?.({ block: 'start', behavior: 'smooth' })
}
async function focusPolicy(key: string) {
  detailsOpen.value = true
  await nextTick()
  focusKey.value = key; focusNonce.value++
}
</script>

<template>
  <section id="case-panel" class="merchant-detail-v4" aria-label="工单内容" :aria-busy="busy">
    <header class="merchant-detail-heading">
      <button type="button" class="text-button" data-test="back-to-list" :disabled="busy" @click="emit('back')">返回工单列表</button>
      <h2>退款申请</h2><span class="status-tag" :class="{ waiting: snapshot.case.status === 'PENDING_REVIEW', success: snapshot.case.status === 'CLOSED_SUCCESS' }">{{ statusLabel }}</span>
    </header>
    <section class="merchant-detail-card merchant-product" aria-label="商品与订单">
      <div class="merchant-product-row">
        <AftercareProduct :line="line" :loading="productState === 'loading'" :unavailable="productState === 'unavailable'" />
        <div class="merchant-product-links"><span class="status-tag">{{ fulfillment }}</span><button class="text-button" type="button" :disabled="busy" @click="emit('order')">查看订单</button></div>
      </div>
      <button v-if="productState === 'unavailable'" type="button" class="text-button" @click="emit('retryProduct')">重试商品资料</button>
      <button v-if="tradeState === 'unavailable'" type="button" class="text-button" @click="emit('retryTrade')">重试履约资料</button>
    </section>
    <div class="merchant-detail-grid">
      <div class="merchant-detail-main">
        <section class="merchant-detail-card merchant-request" aria-label="客户申请">
          <div class="merchant-section-heading"><h3>客户申请</h3><span class="muted">{{ snapshot.evidence.length ? `${snapshot.evidence.length} 项材料` : '无额外材料' }}</span></div>
          <p>{{ snapshot.case.description || '原申请未记录情况说明' }}</p>
        </section>
        <section class="merchant-detail-card merchant-advice" aria-label="调查建议">
          <div class="merchant-section-heading"><h3>{{ proposal?.origin === 'HUMAN' ? '人工方案' : '调查建议' }}</h3>
            <div class="merchant-advice-title" :class="{ 'needs-attention': stale || currentFailure || awaitingVerification }"><strong>{{ advice }}</strong></div></div>
          <template v-if="!stale && !currentFailure">
            <details v-if="typeof proposal?.summary === 'string' || reasons.length" :key="`${snapshot.case.case_id}:${snapshot.case.input_revision}`" class="merchant-full-advice">
              <summary>完整{{ proposal?.origin === 'HUMAN' ? '方案理由' : '调查建议' }}</summary>
              <p v-if="typeof proposal?.summary === 'string'" class="merchant-advice-summary">{{ proposal.summary }}</p>
              <ul v-else class="merchant-advice-reasons"><li v-for="(finding, index) in reasons" :key="index">{{ finding.kind === 'INFERENCE' ? '模型判断：' : 'Agent整理：' }}{{ finding.text }}</li></ul>
            </details>
          </template>
          <p v-if="currentFailure" class="merchant-warning" role="status">本次未形成有效调查建议，需商家结合材料继续核查。</p>
          <p v-if="stale" class="merchant-warning" role="status">材料已更新，旧建议仅供追溯，请等待新调查或形成人工方案。</p>
          <p v-if="proposal?.refusal_reason" class="merchant-warning">服务端复核未通过：{{ proposal.refusal_reason }}</p>
          <p v-for="(finding, index) in conflicts" :key="index" class="merchant-warning">信息冲突：{{ finding.text }}</p>
          <p v-for="(item, index) in missing" :key="index" class="merchant-warning">待确认：{{ item }}</p>
          <p v-if="proposal?.origin === 'AGENT' && !stale && !refs('policy_refs').length" class="merchant-warning">此建议未引用政策，请先核对适用条款。</p>
          <InvestigationSources summary-only :token="token" :snapshot="snapshot" />
          <button class="merchant-source-entry text-button" type="button" @click="openDetails"><Icon name="file" :size="18" /><span>订单、物流与材料记录</span></button>
          <PolicyCitations compact :evidence-refs="[]" :policy-refs="refs('policy_refs')" :policy-rules="context?.policy_rules ?? []" :policy-status="context?.policy_status ?? null" @focus="focusPolicy" />
        </section>
      </div>
      <aside class="merchant-detail-card merchant-treatment" aria-label="退款处理">
        <h3>退款处理</h3><p>{{ context?.execution?.amount_minor != null ? '退款金额' : '申请退款' }}</p>
        <strong class="merchant-treatment-amount">{{ amount !== null ? formatMinorUnits(amount, line?.currency || 'CNY') : '金额待核对' }}</strong>
        <p v-if="executionText" class="merchant-result" :class="{ 'merchant-warning': unknown || context?.execution?.outcome === 'FAILED' }" role="status">{{ executionText }}</p>
        <p v-if="oldAuthorization" class="merchant-warning">退款授权已失效，请等待重新核对。</p>
        <p v-if="contextLoading" class="muted">正在核对可用操作…</p>
        <p v-if="contextError" class="merchant-warning" role="alert">{{ contextError }}</p>
        <button v-if="(awaitingVerification || currentFailure) && unverifiedStatement && !frozen" data-test="verify-application" type="button" :disabled="busy" @click="openDetails">核验申请陈述</button>
        <section v-if="canReview" class="review-section" aria-label="审核操作">
          <div class="actions">
            <button data-test="approve" type="button" :disabled="busy" @click="emit('review', 'APPROVE')">批准退款</button>
            <button type="button" class="secondary-button" :disabled="busy" @click="emit('review', 'REQUEST_INFO')">请客户补充说明</button>
            <button type="button" class="danger-button" :disabled="busy" @click="emit('review', 'REJECT')">拒绝申请</button>
          </div><p class="muted">批准后执行模拟退款</p>
        </section>
        <p v-else-if="!executionText && !contextLoading && !contextError" class="review-unavailable muted">{{ snapshot.authorization?.status === 'CONSUMED' ? '退款已处理，不能再次审批。' : '当前不能直接批准退款，请核对材料与政策。' }}</p>
        <ReviewerWorkspace mode="actions" :line="line" :token="token" :snapshot="snapshot" :context="context" :collaboration="collaboration" :busy="busy || !actionsAvailable" @changed="emit('refresh')" @working="emit('working', $event)" @expired="emit('expired')" />
      </aside>
    </div>
    <button class="merchant-details-link text-button" type="button" :aria-expanded="detailsOpen" aria-controls="merchant-detail-evidence" @click="detailsOpen = !detailsOpen"><Icon name="file" :size="18" /><span>详细材料与处理记录</span><small>{{ detailsOpen ? '收起' : '展开' }}</small></button>
    <section v-if="detailsOpen" id="merchant-detail-evidence" ref="detailsPanel" class="merchant-detail-card merchant-detail-evidence" aria-label="详细依据">
      <div class="merchant-evidence-heading"><h3>详细依据</h3><button class="text-button" type="button" @click="detailsOpen = false">收起</button></div>
      <slot name="materials" />
      <PolicyCitations :evidence-refs="refs('evidence_refs')" :policy-refs="refs('policy_refs')" :policy-rules="context?.policy_rules ?? []" :policy-status="context?.policy_status ?? null" @focus="focusPolicy" />
      <InvestigationSources :token="token" :snapshot="snapshot" />
      <ReviewerWorkspace mode="details" :token="token" :snapshot="snapshot" :busy="busy" :context="context" :collaboration="collaboration" :context-loading="contextLoading" :context-error="contextError" :focus-key="focusKey" :focus-nonce="focusNonce" />
      <details><summary>完整方案与技术编号</summary><pre>{{ JSON.stringify({ case: snapshot.case, authorization: snapshot.authorization, proposal: snapshot.proposal }, null, 2) }}</pre></details>
      <details><summary>完整工单轨迹</summary><ol class="merchant-full-timeline"><li v-for="event in snapshot.timeline" :key="event.event_id"><time>{{ new Date(event.occurred_at).toLocaleString('zh-CN') }}</time><p>{{ event.summary || event.type }}</p></li></ol></details>
    </section>
  </section>
</template>
