<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, reactive, computed, useId } from 'vue'
import { ApiError, type LoginResponse } from '../client'
import { managementApi, type PlatformMerchant, type PlatformBuyer } from '../management-client'
import ReviewDialog from './ReviewDialog.vue'
import ListPagination from './ListPagination.vue'
import { useCursorPages } from '../cursor-pages'
import Icon from './ReviewIcon.vue'
import SupportOperations from './SupportOperations.vue'
import './foundation.css'
import { usePageEntrance } from './usePageEntrance'
import PageLoading from './PageLoading.vue'

type Listing = 'merchants' | 'buyers'
const merchantPages = useCursorPages<string>(), buyerPages = useCursorPages<string>()
const pages = (target: Listing) => target === 'merchants' ? merchantPages : buyerPages
const cursors = reactive<Record<Listing, string | null>>({ merchants:null, buyers:null })
const searchDraft = reactive<Record<Listing,string>>({merchants:'',buyers:''}), applied: Record<Listing,string> = {merchants:'',buyers:''}
const formId = useId()
const props = defineProps<{ account: LoginResponse }>()
const emit = defineEmits<{ expired: [] }>()
const page = ref<'merchants' | 'buyers' | 'agent'>('merchants'), merchants = ref<PlatformMerchant[]>([]), buyers = ref<PlatformBuyer[]>([])
const writing = ref(false), surface = ref<HTMLElement>()
const busy = ref(false), error = ref(''), notice = ref(''), form = ref<'merchant' | 'buyer' | 'password' | null>(null)
const merchantId = ref(''), name = ref(''), description = ref(''), username = ref(''), displayName = ref(''), password = ref(''), reason = ref('')
const selectedBuyer = ref<PlatformBuyer | null>(null)
const changing = ref<{kind:'merchant';row:PlatformMerchant}|{kind:'buyer';row:PlatformBuyer}|null>(null)
const currentPage = computed(() => page.value === 'buyers' ? buyerPages.pageIndex.value : merchantPages.pageIndex.value)
function closeForm() { if (!writing.value) { form.value = null; password.value = ''; error.value = '' } }
function switchPage(target: typeof page.value) {
  if (writing.value || target === page.value) return
  ++loadGeneration; ++operation; busy.value = false
  closeForm(); changing.value = null; notice.value = ''; page.value = target
  if (target !== 'agent') void act(() => load(pages(target).pageIndex.value), false)
}
let alive = true, operation = 0, loadGeneration = 0
onBeforeUnmount(() => { alive = false; password.value = '' })
async function load(index = currentPage.value, query?: string) {
  if (page.value === 'agent') return
  const request = ++loadGeneration
  const target = page.value, state = pages(target), search = query ?? applied[target]
  const options = { after: state.pageCursor(index), query: search }
  const result = target === 'merchants' ? await managementApi.merchants(props.account.access_token, options) : await managementApi.buyers(props.account.access_token, options)
  if (!alive || request !== loadGeneration || page.value !== target) return
  if (target === 'merchants') merchants.value = result.items as PlatformMerchant[]
  else buyers.value = result.items as PlatformBuyer[]
  cursors[target] = result.next_after ?? null; state.acceptPage(index, cursors[target]); applied[target] = search
}
function search() { if (page.value !== 'agent') void act(() => load(0, searchDraft[page.value as Listing].trim()), false) }
async function act(work: () => Promise<void>, blocking = true) {
  if (writing.value || blocking && busy.value) return
  const request = ++operation
  writing.value = blocking; busy.value = true; error.value = ''; notice.value = ''
  try { await work() } catch (cause) {
    if (request !== operation) return
    if (alive && cause instanceof ApiError && cause.status === 401) emit('expired')
    else if (alive) error.value = cause instanceof Error ? cause.message : '请求结果未确认，请刷新查看当前状态。'
  } finally { if (alive && request === operation) { busy.value = false; writing.value = false } }
}
function open(kind: 'merchant' | 'buyer' | 'password', buyer: PlatformBuyer | null = null) {
  form.value = kind; selectedBuyer.value = buyer; merchantId.value = ''; name.value = ''; description.value = ''; username.value = ''; displayName.value = ''; password.value = ''; reason.value = ''; error.value = ''
}
async function submit() {
  await act(async () => {
    const token = props.account.access_token, secret = password.value; password.value = ''
    if (form.value === 'merchant') await managementApi.createMerchant(token, { merchant_id: merchantId.value, name: name.value, description: description.value, username: username.value, display_name: displayName.value, password: secret, reason: reason.value })
    else if (form.value === 'buyer') await managementApi.createBuyer(token, { username: username.value, display_name: displayName.value, password: secret, reason: reason.value })
    else if (selectedBuyer.value) await managementApi.updateBuyer(token, selectedBuyer.value, secret)
    if (!alive) return
    form.value = null; password.value = ''; await load(); notice.value = '已保存。'
  })
}
function merchantAction(row: PlatformMerchant) { if (row.sync_state !== 'PENDING') { changing.value = {kind:'merchant',row};error.value='';return }; void act(async () => { await managementApi.syncMerchant(props.account.access_token,row.merchant_id);await load();notice.value='同步已完成' }) }
function buyerAction(row: PlatformBuyer) { changing.value = {kind:'buyer',row};error.value='' }
async function confirmState() { const action=changing.value;if (!action) return;await act(async () => { if (action.kind==='merchant') await managementApi.updateMerchant(props.account.access_token,action.row); else await managementApi.updateBuyer(props.account.access_token,action.row);if(!alive)return;changing.value=null;await load();notice.value='状态已更新' }) }
onMounted(() => { void act(() => load(), false) })
usePageEntrance(() => surface.value, () => `${page.value}:${currentPage.value}`)
</script>
<template>
  <div class="app-shell foundation-shell">
    <nav class="sidebar" aria-label="平台管理导航">
      <button class="nav-link" :class="{ current: page === 'merchants' }" :disabled="writing" @click="switchPage('merchants')"><Icon name="box" />商家管理</button>
      <button class="nav-link" :class="{ current: page === 'buyers' }" :disabled="writing" @click="switchPage('buyers')"><Icon name="user" />买家账号</button>
      <button class="nav-link" :class="{ current: page === 'agent' }" :disabled="writing" @click="switchPage('agent')"><Icon name="sparkle" />客服运行记录</button>
    </nav>
    <main v-if="page === 'agent'" ref="surface" class="foundation-main"><SupportOperations :token="account.access_token" @expired="emit('expired')" /></main>
    <main v-else ref="surface" class="foundation-main" :data-page-loading="busy">
      <header class="foundation-heading" data-page-reveal><div><h1>{{ page === 'merchants' ? '商家管理' : '买家账号' }}</h1></div><div class="foundation-actions"><button :disabled="busy" @click="act(() => load(), false)">刷新</button><button class="primary-button" :disabled="busy" @click="open(page === 'merchants' ? 'merchant' : 'buyer')">{{ page === 'merchants' ? '创建商家' : '创建买家' }}</button></div></header>
      <p v-if="error && !form && !changing" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message success" role="status">{{ notice }}</p>
      <form class="platform-search foundation-actions" @submit.prevent="search"><input v-model="searchDraft[page]" :disabled="busy" aria-label="搜索商家或买家" :placeholder="page === 'merchants' ? '搜索店铺名称或标识' : '搜索账号或姓名'" maxlength="100" /><button :disabled="busy">搜索</button></form>
      <ReviewDialog v-if="form" :title="form === 'merchant' ? '创建店铺与商家账号' : form === 'buyer' ? '创建买家' : `重置 ${selectedBuyer?.username} 的密码`" :busy="busy" merchant @close="closeForm"><form :id="formId" class="foundation-editor platform-editor" @submit.prevent="submit"><p v-if="error" role="alert" class="message error">{{ error }}</p><fieldset :disabled="busy">
        <div class="foundation-fields">
          <template v-if="form === 'merchant'"><label>商家标识<input v-model="merchantId" required maxlength="64" placeholder="例如 M-1004" /></label><label>店铺名称<input v-model="name" required maxlength="120" /></label><label class="span-two">店铺介绍<textarea v-model="description" required maxlength="500" /></label></template>
          <template v-if="form !== 'password'"><label>{{ form === 'merchant' ? '商家账号' : '买家账号' }}<input v-model="username" required minlength="3" maxlength="60" autocomplete="off" /></label><label>显示姓名<input v-model="displayName" required maxlength="120" /></label></template>
          <label>密码<input v-model="password" required type="password" minlength="6" maxlength="200" autocomplete="new-password" /></label>
          <label v-if="form !== 'password'">创建理由<input v-model="reason" required maxlength="1000" /></label>
        </div></fieldset></form><template #footer><button type="button" :disabled="busy" @click="closeForm">取消</button><button type="submit" :form="formId" class="primary-button" :disabled="busy">{{ busy ? '正在保存…' : '保存' }}</button></template></ReviewDialog>
      <PageLoading :loading="busy" :empty="page === 'merchants' ? !merchants.length : !buyers.length" :layout="page === 'merchants' ? 'cards' : 'table'" />
      <div v-if="page === 'merchants'" v-show="merchants.length || !busy" class="foundation-store-grid" data-page-reveal data-page-content>
        <article v-for="row in merchants" :key="row.merchant_id" class="foundation-store"><div class="foundation-store-title"><h2>{{ row.name }}</h2><span class="foundation-status">{{ row.sync_state === 'PENDING' ? '待同步' : row.enabled ? '营业中' : '已停用' }}</span></div><p>{{ row.description || '暂无店铺介绍' }}</p><p class="foundation-meta">{{ row.merchant_id }}</p><p v-if="!row.policy_ready" class="message">售后政策待准备：需受控导入政策并建立检索索引。</p><button :disabled="busy" @click="merchantAction(row)">{{ row.sync_state === 'PENDING' ? '重试同步' : row.desired_enabled ? '停用商家' : '启用商家' }}</button></article>
      </div>
      <div v-else v-show="buyers.length || !busy" class="foundation-table-wrap" data-page-reveal data-page-content><table class="foundation-table"><thead><tr><th>账号</th><th>姓名</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="row in buyers" :key="row.username"><td>{{ row.username }}</td><td>{{ row.display_name }}</td><td>{{ row.enabled ? '可登录' : '已停用' }}</td><td><div class="foundation-actions"><button :disabled="busy" @click="buyerAction(row)">{{ row.enabled ? '停用' : '启用' }}</button><button :disabled="busy" @click="open('password', row)">重置密码</button></div></td></tr></tbody></table></div>
      <ListPagination :page="currentPage" :has-next="!!cursors[page]" :disabled="busy" :label="page === 'merchants' ? '商家管理分页' : '买家账号分页'" @change="index => act(() => load(index), false)" />
      <ReviewDialog v-if="changing" :title="`${(changing.kind === 'merchant' ? changing.row.desired_enabled : changing.row.enabled) ? '停用' : '启用'}${changing.kind === 'merchant' ? '商家' : '买家账号'}？`" :busy="busy" compact @close="changing = null"><p>{{ changing.kind === 'merchant' ? changing.row.name : changing.row.display_name }}</p><p v-if="changing.kind === 'buyer' && changing.row.enabled">停用后，该账号将退出登录。</p><p v-if="error" role="alert" class="message error">{{ error }}</p><template #footer><button :disabled="busy" @click="changing = null">取消</button><button class="primary-button" :disabled="busy" @click="confirmState">{{ busy ? '正在保存…' : '确认更改' }}</button></template></ReviewDialog>
      <p v-if="!busy && !error && (page === 'merchants' ? merchants.length === 0 : buyers.length === 0)" class="empty">暂无记录，可以创建第一条。</p>
    </main>
  </div>
</template>

<style scoped>.platform-search{margin-bottom:24px}.platform-search input{width:min(360px,100%)}.platform-editor{margin:0;padding:8px 0 0;border:0}.foundation-store{margin-bottom:0}.foundation-store-title h2{margin:0}.foundation-store>button{margin-top:8px}</style>
