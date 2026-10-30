<script setup lang="ts">
import { formatMinorUnits } from '../money'
withDefaults(defineProps<{ amount: number; quantity: number; title?: string; action?: string; actionClass?: string; disabled?: boolean; busy?: boolean; showAction?: boolean }>(), { title: '订单金额', action: '提交订单', showAction: true })
const emit = defineEmits<{ submit: [] }>()
const money = (v: number) => `¥ ${formatMinorUnits(v).replace(' CNY', '')}`
</script>
<template>
  <aside class="order-summary" :aria-label="title">
    <h2>{{ title }}</h2><slot />
    <dl><div><dt>商品数量</dt><dd>{{ quantity }} 件</dd></div><div><dt>商品金额</dt><dd>{{ money(amount) }}</dd></div></dl>
    <div class="order-summary-total"><span>合计</span><strong>{{ money(amount) }}</strong></div>
    <button v-if="showAction" type="button" class="shop-primary order-summary-submit" :class="actionClass" :disabled="disabled || busy" @click="emit('submit')">{{ busy ? '正在确认…' : action }}</button>
    <slot name="after" />
  </aside>
</template>
<style scoped>
.order-summary{position:sticky;top:104px;align-self:start;min-width:0;padding:24px;background:var(--rf-surface);border:1px solid var(--rf-line);border-radius:var(--rf-radius-surface);font-size:14px}
.order-summary h2{font-size:18px!important;margin:0 0 22px!important;font-weight:500}.order-summary dl{margin:20px 0 0}.order-summary dl>div{display:flex;justify-content:space-between;gap:16px;align-items:baseline;margin:12px 0}.order-summary dt{color:var(--rf-muted)}.order-summary dd{margin:0;font-variant-numeric:tabular-nums}.order-summary-total{display:flex;align-items:baseline;justify-content:space-between;gap:12px;padding:22px 0;border-top:1px solid var(--rf-line);margin-top:20px}.order-summary-total strong{font-size:26px;font-weight:500;letter-spacing:-.5px;font-variant-numeric:tabular-nums}.order-summary .order-summary-submit{width:100%;min-height:44px}
@media(max-width:950px){.order-summary{position:static}}
</style>
