<script setup lang="ts">
import type { SupportCitation } from '../support-client'
import { rows, shipmentLabel, sourceLabels, stamp } from '../support-view'
import Icon from './ReviewIcon.vue'
withDefaults(defineProps<{ citations: SupportCitation[]; compact?: boolean }>(), { compact: false })
const order = (c: SupportCitation): Record<string, unknown> => c.data.order_line && typeof c.data.order_line === 'object' ? c.data.order_line as Record<string, unknown> : c.data
</script>

<template>
  <div v-if="citations.length" :class="['support-citations', { 'source-chips': compact }]" aria-label="回答依据">
    <details v-for="c in citations" :key="c.source_id" class="support-citation">
      <summary><Icon :name="c.source_type === 'SHIPMENT' ? 'box' : 'file'" :size="16" /><span>{{ sourceLabels[c.source_type] }}<small v-if="!compact"> · {{ c.version }}</small></span><Icon name="chevron" :size="14" /></summary>
      <div class="source-body"><strong>{{ c.title || sourceLabels[c.source_type] }}</strong><small class="source-version">{{ c.source_id }} · 版本 {{ c.version }}</small>
      <template v-if="c.source_type === 'POLICY'"><p>{{ c.data.text }}</p><small v-if="c.data.rule_id">条款编号：{{ c.data.rule_id }}</small></template>
      <template v-else-if="c.source_type === 'SHIPMENT'"><p>物流状态：{{ shipmentLabel(c.data.status) }}</p><template v-for="(line, index) in rows(c.data.lines)" :key="index"><p v-if="line.carrier_conclusion">承运记录：{{ shipmentLabel(line.carrier_conclusion) }}</p><ol class="support-events"><li v-for="(event, n) in rows(line.events)" :key="n">{{ shipmentLabel(event.code) }}<small>{{ stamp(event.occurred_at) }}</small></li></ol></template><p v-if="c.data.synthetic" class="source-version">本地模拟物流记录</p></template>
      <template v-else-if="c.source_type === 'CONVERSATION'"><blockquote v-for="(m, index) in rows(c.data.messages)" :key="index">{{ m.text }}</blockquote></template>
      <template v-else><p>商品：{{ order(c).product_name || order(c).productName || order(c).sku }}</p><p>数量：{{ order(c).quantity }} · 订单状态：{{ order(c).order_status || order(c).orderStatus }}</p></template>
      </div>
    </details>
  </div>
</template>
