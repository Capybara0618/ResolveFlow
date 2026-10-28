<script setup lang="ts">
import { computed } from 'vue'
import type { SupportCitation } from '../support-client'
import { buyerShipmentLabel } from '../support-view'
const props = defineProps<{ citations: SupportCitation[] }>()
const sources = computed(() => props.citations.filter(c => c.source_type === 'POLICY' || c.source_type === 'SHIPMENT'))
</script>

<template>
  <details v-if="sources.length" class="buyer-evidence">
    <summary>查看依据</summary>
    <div v-for="c in sources" :key="c.source_id"><strong>{{ c.source_type === 'POLICY' ? '售后政策' : '物流记录' }}</strong><p>{{ c.source_type === 'POLICY' ? c.data.text : buyerShipmentLabel(c.data.status) }}</p></div>
  </details>
</template>

<style scoped>
.buyer-evidence { margin-top: 7px; color: #727f77; font-size: 12px; }
summary { cursor: pointer; width: fit-content; }
summary:focus-visible { outline: 2px solid #176b5c; outline-offset: 3px; }
.buyer-evidence > div { border-left: 2px solid #e3e8e1; padding: 4px 12px; margin: 10px 0; }
strong { font-weight: 500; color: #52665a; }
p { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; margin: 4px 0; }
</style>
