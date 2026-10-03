<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { ApiError, type LoginResponse } from '../client'
import { managementApi, type PlatformMerchant, type PlatformBuyer } from '../management-client'
import Icon from './ReviewIcon.vue'
import './foundation.css'

const props = defineProps<{ account: LoginResponse }>()
const emit = defineEmits<{ expired: [] }>()
const page = ref<'merchants' | 'buyers'>('merchants'), merchants = ref<PlatformMerchant[]>([]), buyers = ref<PlatformBuyer[]>([])
const busy = ref(false), error = ref(''), notice = ref(''), form = ref<'merchant' | 'buyer' | 'password' | null>(null)
const merchantId = ref(''), name = ref(''), description = ref(''), username = ref(''), displayName = ref(''), password = ref(''), reason = ref('')
const selectedBuyer = ref<PlatformBuyer | null>(null)
let alive = true
onBeforeUnmount(() => { alive = false })
async function load() {
  const [stores, accounts] = await Promise.all([managementApi.merchants(props.account.access_token), managementApi.buyers(props.account.access_token)])
  if (alive) { merchants.value = stores.items; buyers.value = accounts.items }
}
async function act(work: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try { await work() } catch (cause) {
    if (alive && cause instanceof ApiError && cause.status === 401) emit('expired')
    else if (alive) error.value = cause instanceof Error ? cause.message : '请求结果未确认，请刷新查看当前状态。'
  } finally { if (alive) busy.value = false }
}
function open(kind: 'merchant' | 'buyer' | 'password', buyer: PlatformBuyer | null = null) {
  form.value = kind; selectedBuyer.value = buyer; merchantId.value = ''; name.value = ''; description.value = ''; username.value = ''; displayName.value = ''; password.value = ''; reason.value = ''; error.value = ''
}
async function submit() {
  await act(async () => {
    const token = props.account.access_token
    if (form.value === 'merchant') await managementApi.createMerchant(token, { merchant_id: merchantId.value, name: name.value, description: description.value, username: username.value, display_name: displayName.value, password: password.value, reason: reason.value })
    else if (form.value === 'buyer') await managementApi.createBuyer(token, { username: username.value, display_name: displayName.value, password: password.value, reason: reason.value })
    else if (selectedBuyer.value) await managementApi.updateBuyer(token, selectedBuyer.value, password.value)
    if (!alive) return
    form.value = null; password.value = ''; await load(); notice.value = '已保存。'
  })
}
function merchantAction(row: PlatformMerchant) { void act(async () => { if (row.sync_state === 'PENDING') await managementApi.syncMerchant(props.account.access_token, row.merchant_id); else await managementApi.updateMerchant(props.account.access_token, row); await load(); notice.value = '商家状态已更新。' }) }
function buyerAction(row: PlatformBuyer) { void act(async () => { await managementApi.updateBuyer(props.account.access_token, row); await load(); notice.value = '买家状态已更新，原会话已失效。' }) }
onMounted(() => { void act(load) })
</script>
<template>
  <div class="app-shell foundation-shell">
    <nav class="sidebar" aria-label="平台管理导航">
      <button class="nav-link" :class="{ current: page === 'merchants' }" :disabled="busy" @click="page = 'merchants'; form = null"><Icon name="box" />商家管理</button>
      <button class="nav-link" :class="{ current: page === 'buyers' }" :disabled="busy" @click="page = 'buyers'; form = null"><Icon name="user" />买家账号</button>
    </nav>
    <main class="foundation-main">
      <header class="foundation-heading"><div><h1>{{ page === 'merchants' ? '商家管理' : '买家账号' }}</h1><p>{{ page === 'merchants' ? '管理店铺与商家账号' : '管理可以跨店购物的平台买家' }}</p></div><div class="foundation-actions"><button :disabled="busy" @click="act(load)">刷新</button><button class="primary-button" :disabled="busy" @click="open(page === 'merchants' ? 'merchant' : 'buyer')">{{ page === 'merchants' ? '创建商家' : '创建买家' }}</button></div></header>
      <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message success" role="status">{{ notice }}</p>
      <form v-if="form" class="foundation-editor" @submit.prevent="submit">
        <h2>{{ form === 'merchant' ? '创建店铺与商家账号' : form === 'buyer' ? '创建买家' : `重置 ${selectedBuyer?.username} 的密码` }}</h2>
        <div class="foundation-fields">
          <template v-if="form === 'merchant'"><label>商家标识<input v-model="merchantId" required maxlength="64" placeholder="例如 M-1004" /></label><label>店铺名称<input v-model="name" required maxlength="120" /></label><label class="span-two">店铺介绍<textarea v-model="description" required maxlength="500" /></label></template>
          <template v-if="form !== 'password'"><label>{{ form === 'merchant' ? '商家账号' : '买家账号' }}<input v-model="username" required minlength="3" maxlength="60" autocomplete="off" /></label><label>显示姓名<input v-model="displayName" required maxlength="120" /></label></template>
          <label>密码<input v-model="password" required type="password" minlength="6" maxlength="200" autocomplete="new-password" /></label>
          <label v-if="form !== 'password'">创建理由<input v-model="reason" required maxlength="1000" /></label>
        </div><div class="foundation-actions"><button type="submit" class="primary-button" :disabled="busy">{{ busy ? '正在保存…' : '保存' }}</button><button type="button" :disabled="busy" @click="form = null; password = ''">取消</button></div>
      </form>
      <div v-if="page === 'merchants'" class="foundation-store-grid">
        <article v-for="row in merchants" :key="row.merchant_id" class="foundation-store"><div class="foundation-store-title"><h2>{{ row.name }}</h2><span class="foundation-status">{{ row.sync_state === 'PENDING' ? '待同步' : row.enabled ? '营业中' : '已停用' }}</span></div><p>{{ row.description || '暂无店铺介绍' }}</p><p class="foundation-meta">{{ row.merchant_id }}</p><p v-if="!row.policy_ready" class="message">售后政策待准备：需受控导入政策并建立检索索引。</p><button :disabled="busy" @click="merchantAction(row)">{{ row.sync_state === 'PENDING' ? '重试同步' : row.desired_enabled ? '停用商家' : '启用商家' }}</button></article>
      </div>
      <table v-else class="foundation-table"><thead><tr><th>账号</th><th>姓名</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="row in buyers" :key="row.username"><td>{{ row.username }}</td><td>{{ row.display_name }}</td><td>{{ row.enabled ? '可登录' : '已停用' }}</td><td><div class="foundation-actions"><button :disabled="busy" @click="buyerAction(row)">{{ row.enabled ? '停用' : '启用' }}</button><button :disabled="busy" @click="open('password', row)">重置密码</button></div></td></tr></tbody></table>
      <p v-if="!busy && (page === 'merchants' ? merchants.length === 0 : buyers.length === 0)" class="empty">暂无记录，可以创建第一条。</p>
    </main>
  </div>
</template>
