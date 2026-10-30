<script setup lang="ts">
import { computed } from 'vue'
import type { CustomerCaseDetail } from '../client'
import { formatMinorUnits } from '../money'
import { refundStatus } from '../support-refund'
import Icon from './ReviewIcon.vue'

const props = withDefaults(defineProps<{ application: CustomerCaseDetail; compact?: boolean }>(), { compact: false })
const state = computed(() => props.application.case.status)
const succeeded = computed(() => state.value === 'CLOSED_SUCCESS')
const title = computed(() => refundStatus(state.value, props.application.result.message))
const notes: Record<string, string> = {
  QUEUED: '申请已收到，核查后会在这里更新进展。',
  ANALYZING: '正在核对你的订单和申请材料，暂时不需要操作。',
  WAITING_CUSTOMER: '请补充下方说明，帮助商家继续核查。',
  AUTHORIZED: '商家已批准申请，退款完成后会在这里更新。',
  EXECUTING: '正在处理这笔退款，请耐心等待结果。',
  RECONCILING: '这笔退款的结果还在核实中，请勿重复申请。',
  CLOSED_SUCCESS: '',
  CLOSED_REJECTED: '你可以在下方查看商家的处理说明。',
  CANCELLED: '本次申请已结束，处理记录仍可查看。',
}
const note = computed(() => notes[state.value] || '')
const amount = computed(() => {
  const value = props.application.result.amount_minor
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
    ? formatMinorUnits(value, props.application.result.currency) : null
})
function stamp(value: string) {
  const date = new Date(value)
  return value && !Number.isNaN(date.getTime()) ? date.toLocaleString('zh-CN', { hour12: false }) : ''
}
const updated = computed(() => stamp(props.application.case.updated_at))
// Java's buyer projection contains distinctions such as an execution failure after approval.
const message = computed(() => !succeeded.value && props.application.result.message !== title.value ? props.application.result.message : '')
</script>

<template>
  <section class="buyer-progress" :class="{ compact, success: succeeded, attention: ['WAITING_CUSTOMER', 'RECONCILING', 'CLOSED_REJECTED'].includes(state) }" aria-label="申请当前进展">
    <header :data-refund-success="succeeded ? '' : undefined">
      <span class="buyer-progress-symbol"><Icon :name="succeeded ? 'check' : ['CLOSED_REJECTED', 'CANCELLED'].includes(state) ? 'file' : 'clock'" :size="22" /></span>
      <div><strong>{{ title }}</strong><small>{{ updated ? `模拟退款 · 更新于 ${updated}` : '模拟退款' }}</small></div>
    </header>
    <div v-if="amount" class="buyer-result-amount" data-refund-result-amount><span>{{ succeeded ? '已退金额' : '本次批准金额' }}</span><strong>{{ amount }}</strong></div>
    <p v-if="note" class="buyer-progress-note">{{ note }}</p>
    <p v-if="message && !note" class="buyer-progress-message">{{ message }}</p>
    <p v-if="application.result.public_reason" class="buyer-progress-reason">{{ application.result.public_reason }}</p>
    <p v-if="!succeeded && application.blocked_reason && application.blocked_reason !== application.result.public_reason" class="buyer-progress-blocked">{{ application.blocked_reason }}</p>
    <div v-if="$slots.product" class="buyer-receipt-product"><slot name="product" /></div>
    <details class="buyer-progress-records"><summary>处理记录</summary><ol v-if="application.timeline.length"><li v-for="(event, index) in application.timeline" :key="index"><span>{{ event.summary }}</span><time v-if="stamp(event.occurred_at)" :datetime="event.occurred_at">{{ stamp(event.occurred_at) }}</time></li></ol><p v-else>暂无处理记录。</p><small>申请编号 {{ application.case.case_id }}</small></details>
    <footer v-if="$slots.default"><slot /></footer>
  </section>
</template>

<style scoped>
.buyer-progress { color: #25322c; font-family: var(--display-font-ui, "Resolve Sans", "Microsoft YaHei", sans-serif); font-size: 14px; }
.buyer-progress header { display: flex; align-items: center; gap: 14px; padding: 0; background: none; }
.buyer-progress-symbol { width: 42px; height: 42px; display: grid; place-items: center; flex: 0 0 42px; border-radius: 50%; background: #edf2e9; color: #39715e; }
.attention .buyer-progress-symbol { background: #f8efdc; color: #8b622c; }
.buyer-progress header strong { display: block; font-size: 20px; font-weight: 500; line-height: 1.5; overflow-wrap: anywhere; }
.buyer-progress header small { display: block; margin-top: 3px; font-size: 12px; color: #737d73; }
.buyer-progress :is(p, ol) { margin: 16px 0 0; padding: 0; }
.buyer-progress :is(p, li) { line-height: 1.8; overflow-wrap: anywhere; }
.buyer-progress-note, .buyer-progress-message, .buyer-progress-reason { font: 400 15px/1.8 var(--display-font-reading, "Resolve Reading", "SimSun", serif); }
.buyer-progress-note { color: #606c62; }
.buyer-progress-blocked { padding: 10px 12px !important; background: #f8f4e9; border-radius: 6px; font-size: 13px; color: #7a6239; }
.buyer-result-amount { display: flex; flex-direction: column; gap: 5px; margin: 22px 0 0; }
.buyer-result-amount span { font-size: 12px; color: #6a756b; }
.buyer-result-amount strong { font-size: 30px; font-weight: 500; font-variant-numeric:tabular-nums; line-height: 1.3; letter-spacing: -.5px; color: #25322c; }
.success .buyer-result-amount strong { color: #176b5c; }
.buyer-receipt-product { margin-top: 22px; padding-top: 18px; border-top: 1px solid #e6eae2; }
.buyer-progress-records { margin-top: 20px; padding-top: 14px; border-top: 1px solid #e6eae2; font-size: 12px; color: #6a756b; }
.buyer-progress-records summary { display: flex; justify-content: space-between; gap: 14px; list-style: none; cursor: pointer; }
.buyer-progress-records summary::-webkit-details-marker { display: none; }
.buyer-progress-records summary::marker { content: ''; }
.buyer-progress-records summary::after { content: '展开'; }
.buyer-progress-records[open] summary::after { content: '收起'; }
.buyer-progress-records ol { list-style: none; display: grid; gap: 14px; }
.buyer-progress-records time { display: block; font-size: 12px; color: #7b847a; }
.buyer-progress-records > small { display: block; margin-top: 14px; font-size: 12px; overflow-wrap: anywhere; }
.buyer-progress footer { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; border-top: 1px solid #e6eae2; margin-top: 16px; padding-top: 14px; }
.compact header strong { font-size: 17px; }
.compact .buyer-result-amount { margin-top: 16px; }
.compact .buyer-result-amount strong { font-size: 26px; }
@media (prefers-reduced-motion: reduce) { .buyer-progress * { animation: none; } }
</style>
