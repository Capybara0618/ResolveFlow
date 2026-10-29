<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import { ApiError, type LoginResponse } from '../client'
import { accountApi, type Address, type ShippingSelection } from '../account-client'
import AccountWorkspace from './AccountWorkspace.vue'
const props = defineProps<{ account: LoginResponse; modelValue: ShippingSelection | null; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: ShippingSelection | null]; expired: []; working: [value: boolean] }>()
const rows = ref<Address[]>([]), error = ref(''), loading = ref(false), managing = ref(false), saving = ref(false)
let generation = 0
async function load() { const g = ++generation; loading.value = true; error.value = ''
  try { const result = await accountApi.addresses(props.account.access_token); if (g !== generation) return; rows.value = result.items
    const current = rows.value.find(a => a.address_id === props.modelValue?.address_id) ?? rows.value.find(a => a.is_default) ?? rows.value[0]
    emit('update:modelValue', current ? { address_id: current.address_id, expected_version: current.version } : null)
  } catch (e) { if (g === generation) { emit('update:modelValue', null); if (e instanceof ApiError && e.status === 401) emit('expired'); error.value = e instanceof Error ? e.message : '地址暂时无法读取' } }
  finally { if (g === generation) loading.value = false }
}
function choose(id: string) { const row = rows.value.find(a => a.address_id === id); if (row) emit('update:modelValue', { address_id: id, expected_version: row.version }) }
watch(() => props.account.access_token, () => { void load() }, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>
<template><section class="shipping-picker" aria-label="选择收货地址"><div class="shipping-picker-head"><h2>收货信息</h2><button type="button" :disabled="disabled || saving || loading" @click="managing = !managing">{{ managing ? '收起地址管理' : rows.length ? '管理地址' : '添加收货地址' }}</button></div>
  <p v-if="loading">正在读取地址…</p><p v-if="error" role="alert">{{ error }} <button type="button" :disabled="disabled || saving || loading" @click="load">重试</button></p><p v-if="!loading && !error && !rows.length">请添加收货地址后提交订单。</p>
  <label v-for="row in rows" :key="row.address_id" class="shipping-choice"><input type="radio" name="checkout-address" :value="row.address_id" :checked="modelValue?.address_id === row.address_id" :disabled="disabled || saving || loading" @change="choose(row.address_id)" /><span><strong>{{ row.recipient }}</strong>　{{ row.phone }}<small v-if="row.is_default">默认</small><span class="shipping-location">{{ row.province }} {{ row.city }} {{ row.district }} {{ row.detail }}</span></span></label>
  <AccountWorkspace :key="account.access_token" v-if="managing" :account="account" mode="addresses" @changed="load" @working="saving = $event; emit('working', $event)" @expired="emit('expired')" />
</section></template>
<style scoped>.shipping-picker{border:1px solid #dfe5da;border-radius:12px;background:#fff;padding:24px;margin:20px 0}.shipping-picker-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.shipping-picker h2{font-size:18px;margin:0}.shipping-picker button{font:inherit;font-size:14px;background:white;color:#205e50;border:1px solid #cedacd;border-radius:7px;padding:8px 12px;cursor:pointer}.shipping-choice{display:flex;gap:14px;align-items:flex-start;padding:17px 0;cursor:pointer}.shipping-choice input{accent-color:#205e50;margin-top:5px}.shipping-location{display:block;line-height:1.7;color:#5c6b60;margin-top:5px}.shipping-choice small{display:inline-block;font-size:12px;background:#edf4e9;color:#205e50;padding:2px 6px;margin-left:10px;border-radius:4px}</style>
