<script setup lang="ts">
import { fulfillmentLabels, type OrderFulfillment } from '../fulfillment-client'
import type { PurchaseLine } from '../shop-client'
const props = defineProps<{ fact: OrderFulfillment | null; lines: PurchaseLine[]; loading?: boolean; error?: string }>()
const emit = defineEmits<{ retry: [] }>()
const events: Record<string, string> = { ORDER_PAID: '付款完成，等待发货', SIMULATED_SHIPPED: '已模拟发货', DELIVERED: '承运商记录签收', LOST: '承运商记录丢失' }
const date = (s: string) => new Date(s).toLocaleString('zh-CN', { hour12: false })
const title = (id: string) => props.lines.find(l => l.line_id === id)?.product_name || props.lines.find(l => l.line_id === id)?.sku || '订单商品'
</script>
<template>
  <section class="fulfillment-panel" aria-label="订单履约">
    <header><h2>订单履约</h2><span v-if="fact" class="fulfillment-chip" :class="fact.status.toLowerCase()">{{ fulfillmentLabels[fact.status] }}</span></header>
    <p v-if="loading" role="status">正在读取物流…</p>
    <div v-else-if="error" role="alert"><p>{{ error }}</p><button type="button" class="secondary-button shop-secondary" @click="emit('retry')">重新读取物流</button></div>
    <template v-else-if="fact">
      <p v-if="fact.status === 'NOT_SHIPPED'">付款已完成，商家尚未发货。</p>
      <p v-else-if="fact.status === 'IN_TRANSIT'">商品已发出。本项目记录的是本地模拟物流。</p>
      <p v-else-if="fact.status === 'UNKNOWN'">暂无可确认的物流状态；缺失记录不表示未发货。</p>
      <div v-for="line in fact.lines" :key="line.line_id" class="fulfillment-line"><h3>{{ title(line.line_id) }}</h3><p>{{ fulfillmentLabels[line.status] }}</p>
        <ol v-if="line.events.length" class="fulfillment-events"><li v-for="event in line.events" :key="event.source_version"><strong>{{ events[event.code] || event.code }}</strong><time>{{ date(event.occurred_at) }}</time></li></ol>
        <p v-else>尚无物流轨迹记录。</p>
      </div>
    </template>
    <p v-else>尚未读取物流。</p>
  </section>
</template>
<style>
.fulfillment-panel { border: 1px solid #e2e9f3; border-radius: 14px; background: white; padding: 26px; margin-bottom: 22px; font-size: 16px; }
.fulfillment-panel header { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.fulfillment-panel h2 { font-size: 22px !important; margin: 0 !important; }.fulfillment-panel h3 { font-size: 18px !important; margin: 0 0 12px !important; }
.fulfillment-panel p { font-size: 16px !important; color: #5c708b; margin: 16px 0; line-height: 1.65; }
.fulfillment-chip { font-size: 16px; padding: 8px 14px; border-radius: 8px; background: #edf3ff; color: #1c60d3; white-space: nowrap; }
.fulfillment-chip.delivered { color: #168458; background: #e9f7ef; }.fulfillment-chip.unknown,.fulfillment-chip.lost { color: #95600a; background: #fff4dd; }
.fulfillment-line { border-top: 1px solid #edf0f5; padding-top: 22px; margin-top: 22px; }
.fulfillment-events { list-style: none; padding: 0 0 0 14px; margin: 18px 0 0 6px; border-left: 2px solid #c8dafb; display: grid; gap: 22px; }
.fulfillment-events li { position: relative; display: flex; flex-wrap: wrap; gap: 10px 24px; justify-content: space-between; font-size: 16px; }
.fulfillment-events li::before { content: ''; position: absolute; background: #165dff; border: 3px solid white; width: 12px; height: 12px; border-radius: 50%; left: -22px; top: 2px; }
.fulfillment-events time { color: #6c7e98; }
</style>
