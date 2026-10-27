<script setup lang="ts">
import { computed } from 'vue'
import type { SupportConversation } from '../support-client'
import { lastAssistant, reportFor, shipmentEvents, shipmentIn, shipmentLabel, stamp, tail } from '../support-view'
import { formatMinorUnits } from '../money'
import ProductArt from './ProductArt.vue'
import SupportSources from './SupportSources.vue'
import Icon from './ReviewIcon.vue'

const props = defineProps<{ conversation: SupportConversation; merchant: boolean; disabled?: boolean }>()
defineEmits<{ changeOrder: [] }>()
const report = computed(() => reportFor(props.conversation, props.merchant))
const shipment = computed(() => shipmentIn(report.value?.citations ?? []))
const events = computed(() => shipmentEvents(shipment.value).slice(0, 3))
const policies = computed(() => report.value?.citations.filter(c => c.source_type === 'POLICY') ?? [])
const guides = computed(() => report.value?.citations.filter(c => c.source_type === 'KNOWLEDGE') ?? [])
</script>

<template>
  <aside class="support-context" aria-label="订单与调查依据">
    <section class="context-card support-product"><header><h2>{{ merchant ? '订单信息' : '当前咨询商品' }}</h2><button v-if="!merchant" class="text-action" :disabled="disabled" @click="$emit('changeOrder')">更换</button></header>
      <div class="context-product"><ProductArt :asset="conversation.product.asset_key || ''" :name="conversation.product.name" :variant="conversation.product.variant ?? ''" /><div><h3>{{ conversation.product.name }}</h3><p>{{ conversation.product.variant || '默认规格' }} · {{ conversation.product.quantity }}件</p><strong>¥{{ formatMinorUnits(conversation.product.amount_minor).replace(' CNY', '') }}</strong></div></div>
      <div class="context-product-meta"><span>{{ conversation.store_name }}</span><small>订单尾号 {{ tail(conversation.order_id) }}</small></div>
      <details class="support-source"><summary>订单与核查编号</summary><p>订单：{{ conversation.order_id }}</p><p>商品行：{{ conversation.line_id }}</p><p v-if="conversation.ticket">核查单：{{ conversation.ticket.ticket_id }}</p></details>
    </section>
    <section v-if="merchant" class="context-card support-report"><header><h2><Icon name="sparkle" /> 调查摘要</h2><span v-if="report" class="support-tag blue">客户已确认共享</span></header>
      <p v-if="report?.mode === 'mock'" class="source-version">脚本模型演示</p>
      <h3 class="report-label">客户共享原文</h3><blockquote v-for="m in conversation.ticket?.shared_messages" :key="m.message_id">{{ m.text }}</blockquote><p v-if="!conversation.ticket?.shared_messages.length" class="context-muted">客户未共享原文，请以已确认的摘要为核查诉求。</p>
      <h3 class="report-label">已查事实与政策</h3><SupportSources v-if="report?.citations.length" :citations="report.citations" /><p v-else class="context-muted">本次未共享助手调查依据。</p>
      <h3 class="report-label">客户确认的核查事项</h3><p>{{ conversation.ticket?.summary }}</p>
      <h3 class="report-label">后续操作</h3><p class="context-muted">结合共享材料核查后，回复客户或请求补充信息。</p>
    </section>
    <template v-else>
      <section class="context-card"><h2>物流概览</h2><template v-if="shipment"><span class="support-tag amber">{{ shipmentLabel(shipment.data.status) }}</span><ol class="shipment-timeline"><li v-for="(event, index) in events" :key="index"><span>{{ stamp(event.occurred_at, true) }}</span><strong>{{ shipmentLabel(event.code) }}</strong></li></ol><p class="source-version">回答引用 · {{ stamp(lastAssistant(conversation)?.created_at, true) }}</p><SupportSources :citations="[shipment]" /></template><p v-else class="context-muted">助手查阅物流后，相关记录会显示在这里。</p></section>
      <section class="context-card"><h2>相关政策</h2><template v-if="policies.length"><p class="context-muted">本次回答引用的适用政策</p><SupportSources :citations="policies" /></template><p v-else class="context-muted">需要解释政策时，助手会查阅本店适用版本。</p></section>
      <section v-if="guides.length" class="context-card"><h2>使用指南</h2><SupportSources :citations="guides" /></section>
    </template>
  </aside>
</template>
