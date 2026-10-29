<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiError, coreApi, type LoginResponse, type MerchantOverview, type ReviewScope } from '../client'
import Icon from './ReviewIcon.vue'

const props = defineProps<{ account: LoginResponse }>()
const emit = defineEmits<{ expired: []; queue: [view: string, scope: ReviewScope]; open: [id: string]; people: []; navigate: [page: 'products' | 'orders' | 'policies'] }>()
const data = ref<MerchantOverview | null>(null), loading = ref(false), error = ref('')
let alive = true, generation = 0, timer: ReturnType<typeof setInterval> | undefined
const reasons: Record<string, string> = { UNCLAIMED: '待领取', RESULT_UNKNOWN: '退款结果待确认', OWNER_UNAVAILABLE: '负责人不可用', INVESTIGATION_FAILED: '调查失败待人工处理' }
const status: Record<string, string> = { QUEUED: '等待调查', ANALYZING: '调查中', WAITING_CUSTOMER: '待客户补证', PENDING_REVIEW: '待人工审核', AUTHORIZED: '已批准待执行', EXECUTING: '退款执行中', RECONCILING: '退款结果待确认' }
const date = (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false })
async function load() {
  if (loading.value) return
  const g = ++generation, token = props.account.access_token
  loading.value = true
  try {
    const result = await coreApi.merchantOverview(token)
    if (!alive || g !== generation || token !== props.account.access_token) return
    data.value = result; error.value = ''
  } catch (cause) {
    if (!alive || g !== generation || token !== props.account.access_token) return
    if (cause instanceof ApiError && cause.status === 401) emit('expired')
    else error.value = '概览暂时未能更新，请重试。' + (data.value ? ' 下方保留上次读取的数据。' : '')
  } finally { if (alive && g === generation) loading.value = false }
}
function focusCoordination() { document.getElementById('coordination-list')?.scrollIntoView?.({ block: 'start' }) }
onMounted(() => { void load(); timer = setInterval(() => { if (!document.hidden) void load() }, 30000) })
onBeforeUnmount(() => { alive = false; ++generation; clearInterval(timer) })
</script>

<template>
  <main v-if="account.single_operator" class="admin-workspace single-merchant-workspace" aria-label="商家工作台">
    <header class="admin-heading"><div><span class="admin-eyebrow">{{ account.merchant_name }}</span><h1>商家工作台</h1></div><button type="button" class="secondary-button" :disabled="loading" @click="load">刷新概览</button></header>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <p v-if="loading && !data" role="status">正在读取本店售后…</p>
    <div class="overview-metrics">
      <button class="overview-metric" :disabled="!data" @click="emit('queue','ALL','PUBLIC')"><span class="metric-icon"><Icon name="queue" :size="22" /></span><span><small>未结束售后</small><strong>{{ data?.mine ?? '—' }}</strong></span></button>
      <button class="overview-metric attention-metric" :disabled="!data" @click="focusCoordination"><span class="metric-icon"><Icon name="shield" :size="22" /></span><span><small>需要关注</small><strong>{{ data?.attention ?? '—' }}</strong></span></button>
    </div>
    <section class="panel admin-card"><h2>日常经营</h2><div class="foundation-actions"><button class="secondary-button" @click="emit('navigate','products')">管理商品</button><button class="secondary-button" @click="emit('navigate','orders')">处理订单</button><button class="secondary-button" @click="emit('queue','ALL','PUBLIC')">处理售后</button><button class="secondary-button" @click="emit('navigate','policies')">查看售后政策</button></div></section>
    <section id="coordination-list" class="panel admin-card"><h2>售后关注事项</h2><article v-for="item in data?.items ?? []" :key="item.case_id" class="merchant-attention"><strong>{{ item.description || '售后申请' }}</strong><p>{{ item.reasons.map(r => r === 'OWNER_UNAVAILABLE' || r === 'UNCLAIMED' ? '商家处理身份需核对' : reasons[r]).join(' · ') }}</p><button class="secondary-button" @click="emit('open',item.case_id)">查看售后</button></article><p v-if="data && data.items.length === 0">暂无异常，进入售后工单查看申请进展。</p></section>
  </main>
  <main v-else class="admin-workspace" aria-label="商家工单概览">
    <header class="admin-heading"><div><span class="admin-eyebrow">{{ account.merchant_name ?? account.merchant_id }} · 商家管理</span><h1>商家工单概览</h1><p>先关注未领取和异常工单，再进入详情核对与协调。</p></div><button type="button" class="secondary-button" :disabled="loading" @click="load"><Icon name="clock" />{{ loading ? '更新中…' : '刷新概览' }}</button></header>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <p v-if="loading && !data" class="admin-loading" role="status">正在读取本商家工单…</p>
    <div class="overview-metrics">
      <button type="button" class="overview-metric" :disabled="!data" @click="emit('queue', 'ALL', 'UNCLAIMED')"><span class="metric-icon"><Icon name="queue" :size="22" /></span><span><small>未领取工单</small><strong>{{ data?.unclaimed ?? '—' }}</strong><span>尚未归属、未消费的可处理工单</span></span></button>
      <button type="button" class="overview-metric" :disabled="!data" @click="emit('queue', 'ALL', 'MINE')"><span class="metric-icon"><Icon name="user" :size="22" /></span><span><small>我的待办</small><strong>{{ data?.mine ?? '—' }}</strong><span>由我负责的未结束工单</span></span></button>
      <button type="button" class="overview-metric attention-metric" :disabled="!data" @click="focusCoordination"><span class="metric-icon"><Icon name="shield" :size="22" /></span><span><small>需关注工单</small><strong>{{ data?.attention ?? '—' }}</strong><span>结果待确认、人员或调查异常</span></span></button>
    </div>
    <div class="overview-body">
      <section id="coordination-list" class="panel admin-card" aria-label="待协调工单"><div class="admin-card-heading"><div><h2>待协调工单 <span v-if="data">（{{ data.coordination_total }}）</span></h2><p>异常优先，同类按更新时间从旧到新排列。</p></div><span class="admin-chip">当前商家</span></div>
        <div v-if="data?.items.length" class="admin-table-wrap"><table class="admin-table"><thead><tr><th>工单 / 情况说明</th><th>协调原因</th><th>负责人</th><th>操作</th></tr></thead><tbody><tr v-for="item in data.items" :key="item.case_id"><td><strong>{{ item.description || '退款申请' }}</strong><small class="admin-id">{{ item.case_id }}</small><small>{{ status[item.status] ?? item.status }} · {{ date(item.updated_at) }}</small></td><td><span v-for="reason in item.reasons" :key="reason" class="admin-reason" :class="{ warning: reason !== 'UNCLAIMED' }">{{ reasons[reason] }}</span></td><td>{{ item.owner_name ?? item.owner_username ?? '未领取' }}</td><td><button type="button" class="text-button" :aria-label="`查看工单 ${item.case_id}`" @click="emit('open', item.case_id)">查看与协调<Icon name="chevron" :size="13" /></button></td></tr></tbody></table></div>
        <div v-else-if="data" class="admin-empty"><Icon name="check" :size="32" /><h3>暂时没有待协调工单</h3><p>可以进入公共队列查看本商家的全部进展。</p><button type="button" class="secondary-button" @click="emit('queue', 'ALL', 'PUBLIC')">查看公共队列</button></div>
        <footer v-if="data" class="admin-card-footer"><span>已显示 {{ data.items.length }} / {{ data.coordination_total }} 条；完整工单可在队列查询。</span><button type="button" class="text-button" @click="emit('queue', 'ALL', 'PUBLIC')">进入工作队列<Icon name="arrow" :size="14" /></button></footer>
      </section>
      <aside class="overview-aside"><section class="panel admin-card"><span class="metric-icon"><Icon name="user" :size="24" /></span><h2>本商家工作人员</h2><div class="staff-total">{{ data?.enabled_staff ?? '—' }}<small>位已启用</small></div><p>包含售后专员、商家管理员及兼容运维账号。</p><button type="button" class="secondary-button" @click="emit('people')">管理人员</button></section><section class="admin-coordination-note"><Icon name="shield" :size="22" /><h3>协调后，由负责人处理</h3><p>管理员进入工单后可领取或显式接管。审核权限仍由当前归属和工单状态决定。</p><p>退款结果待确认时，只跟踪原退款操作，不能重复付款。</p></section></aside>
    </div>
    <p v-if="data" class="admin-update-time">读取时间 {{ date(data.observed_at) }} · 可见页面每30秒更新 · 合成演示数据</p>
  </main>
</template>
