<script setup lang="ts">
import type { SupportCitation } from '../support-client'
defineProps<{ citations: SupportCitation[] }>()
const labels = { ORDER: '订单事实', SHIPMENT: '物流事实', POLICY: '店铺政策', CONVERSATION: '对话原文' }
const statuses: Record<string, string> = { IN_TRANSIT: '运输中', DELAYED: '运输延迟', EXCEPTION_DELAYED: '物流延迟异常', DELIVERED: '已签收', LOST: '承运方确认丢失', UNKNOWN: '状态待核实', NOT_SHIPPED: '尚未发货', ORDER_PAID: '订单已付款', SIMULATED_SHIPPED: '已模拟发货' }
const status = (value: unknown) => typeof value === 'string' ? statuses[value] || value : '待核实'
const rows = (value: unknown): Record<string, unknown>[] => Array.isArray(value) ? value.filter(v => v && typeof v === 'object') : []
const stamp = (value: unknown) => typeof value === 'string' ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : ''
const order = (c: SupportCitation): Record<string, unknown> => c.data.order_line && typeof c.data.order_line === 'object' ? c.data.order_line as Record<string, unknown> : c.data
</script>

<template>
  <details v-if="citations.length" class="support-citations">
    <summary>查看依据（{{ citations.length }}）</summary>
    <article v-for="c in citations" :key="c.source_id">
      <strong>{{ c.source_id }} · {{ labels[c.source_type] }} · 版本 {{ c.version }}</strong>
      <p v-if="c.title">{{ c.title }}</p>
      <template v-if="c.source_type === 'POLICY'"><p>{{ c.data.text }}</p><small v-if="c.data.rule_id">条款编号：{{ c.data.rule_id }}</small></template>
      <template v-else-if="c.source_type === 'SHIPMENT'"><p>物流状态：{{ status(c.data.status) }}</p><template v-for="(line, index) in rows(c.data.lines)" :key="index"><p v-if="line.carrier_conclusion">承运记录：{{ status(line.carrier_conclusion) }}</p><ol class="support-events"><li v-for="(event, n) in rows(line.events)" :key="n">{{ status(event.code) }} · {{ stamp(event.occurred_at) }}</li></ol></template><p v-if="c.data.synthetic" class="muted">本地模拟物流记录</p></template>
      <template v-else-if="c.source_type === 'CONVERSATION'"><blockquote v-for="(m, index) in rows(c.data.messages)" :key="index">{{ m.text }}</blockquote></template>
      <template v-else><p>商品：{{ order(c).product_name || order(c).productName || order(c).sku }}</p><p>数量：{{ order(c).quantity }} · 订单状态：{{ order(c).order_status || order(c).orderStatus }}</p></template>
    </article>
  </details>
</template>
