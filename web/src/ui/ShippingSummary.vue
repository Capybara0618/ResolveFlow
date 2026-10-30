<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import { apiRequest, ApiError } from '../client'
import type { ShippingSnapshot } from '../account-client'
const props = defineProps<{ token: string; purchase: string; merchant?: boolean }>()
const emit = defineEmits<{ expired: [] }>()
const shipping = ref<ShippingSnapshot | null>(null), loading = ref(true), error = ref('')
let generation = 0
async function load() { const g = ++generation; loading.value = true; error.value = ''; shipping.value = null
  const path = props.merchant ? `/api/v1/merchant/orders/${encodeURIComponent(props.purchase)}/shipping` : `/api/v1/shop/purchases/${encodeURIComponent(props.purchase)}/shipping`
  try { const result = await apiRequest<{ shipping: ShippingSnapshot | null }>(path, props.token); if (g === generation) shipping.value = result.shipping }
  catch (e) { if (g === generation) { if (e instanceof ApiError && e.status === 401) emit('expired'); error.value = '收货信息暂时无法读取' } }
  finally { if (g === generation) loading.value = false }
}
watch(() => [props.token, props.purchase, props.merchant], () => { void load() }, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>
<template><section class="shipping-summary" aria-label="订单收货信息"><h2>收货信息</h2><p v-if="loading">正在读取…</p><p v-else-if="error" role="status">{{ error }} <button @click="load">重试</button></p><template v-else-if="shipping"><p><strong>{{ shipping.recipient }}</strong>　{{ shipping.phone }}</p><p>{{ shipping.province }} {{ shipping.city }} {{ shipping.district }} {{ shipping.detail }}</p></template><p v-else>该订单未记录收货信息</p></section></template>
<style scoped>.shipping-summary{padding:22px 24px;margin:20px 0;border:1px solid var(--rf-line);border-radius:var(--rf-radius-surface);background:var(--rf-surface);min-height:132px}.shipping-summary h2{font-size:18px;margin:0 0 15px}.shipping-summary p{font-size:14px;line-height:1.7;color:var(--rf-muted);margin:8px 0}.shipping-summary button{border:0;background:transparent;color:#205e50;cursor:pointer;font:inherit}</style>
