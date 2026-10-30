<script setup lang="ts">
import { computed } from 'vue'
import type { SupportConversation } from '../support-client'
import { buyerShipmentLabel, reportFor, shipmentEvents, shipmentIn, stamp, tail } from '../support-view'
import { formatMinorUnits } from '../money'
import ProductArt from './ProductArt.vue'
import SupportSources from './SupportSources.vue'
import BuyerSources from './BuyerSources.vue'
import Icon from './ReviewIcon.vue'

const props = defineProps<{ conversation: SupportConversation; merchant: boolean; disabled?: boolean; collapsed?: boolean }>()
defineEmits<{ changeOrder: [] }>()
const report = computed(() => reportFor(props.conversation, props.merchant))
const shipment = computed(() => shipmentIn(report.value?.citations ?? []))
const events = computed(() => shipmentEvents(shipment.value).slice(0, 3))
const policies = computed(() => report.value?.citations.filter(c => c.source_type === 'POLICY') ?? [])
</script>

<template>
  <aside v-show="!collapsed" class="support-context" aria-label="订单与调查依据">
    <section class="context-card support-product"><header><h2>{{ merchant ? '订单信息' : '当前咨询商品' }}</h2><button v-if="!merchant" class="text-action" :disabled="disabled" @click="$emit('changeOrder')">更换</button></header>
      <div class="context-product"><ProductArt :asset="conversation.product.asset_key || ''" :name="conversation.product.name" :variant="conversation.product.variant ?? ''" /><div><h3>{{ conversation.product.name }}</h3><p>{{ conversation.product.variant || '默认规格' }} · {{ conversation.product.quantity }}件</p><strong>¥{{ formatMinorUnits(conversation.product.amount_minor).replace(' CNY', '') }}</strong></div></div>
      <div class="context-product-meta"><span><Icon v-if="!merchant" name="store" :size="14" />{{ conversation.store_name }}</span><small>订单尾号 {{ tail(conversation.order_id) }}</small></div>
      <details v-if="merchant" class="support-source"><summary>订单与核查编号</summary><p>订单：{{ conversation.order_id }}</p><p>商品行：{{ conversation.line_id }}</p><p v-if="conversation.ticket">核查单：{{ conversation.ticket.ticket_id }}</p></details>
    </section>
    <section v-if="merchant" class="context-card support-report"><header><h2><Icon name="sparkle" /> 调查摘要</h2><span v-if="report" class="support-tag blue">客户已确认共享</span></header>
      <p v-if="report?.mode === 'mock'" class="source-version">脚本模型演示</p>
      <h3 class="report-label">客户共享原文</h3><blockquote v-for="m in conversation.ticket?.shared_messages" :key="m.message_id">{{ m.text }}</blockquote><p v-if="!conversation.ticket?.shared_messages.length" class="context-muted">客户未共享原文，请以已确认的摘要为核查诉求。</p>
      <h3 class="report-label">已查事实与政策</h3><SupportSources v-if="report?.citations.length" :citations="report.citations" /><p v-else class="context-muted">本次未共享助手调查依据。</p>
      <h3 class="report-label">客户确认的核查事项</h3><p>{{ conversation.ticket?.summary }}</p>
    </section>
    <template v-else>
      <section v-if="shipment" class="context-card"><h2>物流</h2><p class="buyer-shipment-status">{{ buyerShipmentLabel(shipment.data.status) }}</p><details data-logistics-details class="buyer-evidence"><summary>查看物流记录</summary><ol class="shipment-timeline"><li v-for="(event, index) in events" :key="index"><span>{{ stamp(event.occurred_at, true) }}</span><strong>{{ buyerShipmentLabel(event.code) }}</strong></li></ol></details></section>
      <section v-if="policies.length" class="context-card"><BuyerSources :citations="policies" /></section>
    </template>
  </aside>
</template>
