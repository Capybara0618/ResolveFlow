<script setup lang="ts">
import type { OrderLine } from '../client'
import AftercareProduct from './AftercareProduct.vue'
const props = defineProps<{ kind: 'MANUAL_PROPOSAL' | 'APPROVE' | 'REQUEST_INFO' | 'REJECT'; line?: OrderLine | null; modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const labels = { MANUAL_PROPOSAL: '退款理由', APPROVE: '批准理由', REQUEST_INFO: '需要客户说明什么？', REJECT: '拒绝理由' }
const placeholders = { MANUAL_PROPOSAL: '例如：客户买错尺寸，订单尚未发货，同意整行退款。', APPROVE: '请写明同意本次退款的原因。', REQUEST_INFO: '例如：请说明商品出现了什么问题，以及何时发现。', REJECT: '请说明本次申请无法通过的具体原因。' }
</script>
<template>
  <div class="merchant-decision-form">
    <AftercareProduct :line="line" :unavailable="!line" />
    <slot />
    <label class="decision-reason">{{ labels[kind] }}<textarea :value="modelValue" maxlength="1000" rows="3" :placeholder="placeholders[kind]" @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)" /></label>
    <p v-if="kind === 'REQUEST_INFO'" class="decision-note">客户会收到这条问题，回答后系统继续调查。</p>
    <p v-else-if="kind === 'REJECT'" class="decision-warning">确认后，本次申请将结束，客户可看到拒绝理由。</p>
    <p v-else-if="kind === 'MANUAL_PROPOSAL'" class="decision-note">生成方案后还需确认批准，当前不会执行退款。</p>
    <p v-else class="decision-note">确认后系统执行模拟退款，最终结果以退款记录为准。</p>
    <div v-if="(kind === 'REQUEST_INFO' || kind === 'REJECT') && modelValue.trim()" class="decision-preview"><strong>客户将看到</strong><p>{{ modelValue.trim() }}</p></div>
  </div>
</template>
<style scoped>
.merchant-decision-form { display: grid; gap: 22px; font-size: 18px; line-height: 1.6; }
.decision-reason { display: grid; gap: 10px; font-size: 18px; font-weight: 600; }
.decision-reason textarea { width: 100%; box-sizing: border-box; padding: 14px 16px; font: inherit; font-weight: 400; min-height: 120px; resize: vertical; }
.decision-note, .decision-warning { margin: 0; font-size: 18px; }
.decision-note { color: #526681; }
.decision-warning { color: #a74632; background: #fff4f1; padding: 14px 16px; border-radius: 10px; }
.decision-preview { background: #f5f7fa; border-radius: 10px; padding: 16px; }
.decision-preview p { margin: 6px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.merchant-decision-form :deep(.aftercare-product-store), .merchant-decision-form :deep(.aftercare-product-variant), .merchant-decision-form :deep(.aftercare-product-amount) { font-size: 18px; }
.merchant-decision-form :deep(.aftercare-product-copy strong) { font-size: 22px; }
</style>
