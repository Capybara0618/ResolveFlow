<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiError, coreApi, type AdminAccount, type AccountAudit, type AccountFilter, type LoginResponse } from '../client'
import Icon from './ReviewIcon.vue'
import ReviewDialog from './ReviewDialog.vue'

const props = defineProps<{ account: LoginResponse }>()
const emit = defineEmits<{ expired: []; working: [value: boolean]; renamed: [name: string] }>()
const rows = ref<AdminAccount[]>([]), total = ref<number | null>(null), enabledAdmins = ref(0), currentUsername = ref('')
const cursor = ref<string>(), loading = ref(false), busy = ref(false), error = ref(''), notice = ref('')
const query = ref(''), role = ref('ALL'), status = ref('ALL')
let applied: AccountFilter = { query: '', role: 'ALL', status: 'ALL' }
let listGeneration = 0, historyGeneration = 0, alive = true
const selected = ref<AdminAccount | null>(null), name = ref(''), selectedRole = ref<LoginResponse['role']>('REVIEWER')
const enabled = ref(true), reason = ref(''), stale = ref(false)
const history = ref<AccountAudit[]>([]), historyCursor = ref<string>(), historyTotal = ref(0), historyLoading = ref(false), historyError = ref('')
const dialog = ref<'create' | 'password' | null>(null), newUsername = ref(''), newName = ref('')
const newRole = ref<'REVIEWER' | 'MERCHANT_ADMIN'>('REVIEWER'), secret = ref(''), dialogReason = ref('')
const labels: Record<LoginResponse['role'], string> = { CUSTOMER: '客户', REVIEWER: '售后专员', MERCHANT_ADMIN: '商家管理员', OPERATOR: '兼容运维账号', PLATFORM_ADMIN: '平台管理员' }
const fixedRole = computed(() => !!selected.value && ['CUSTOMER', 'OPERATOR'].includes(selected.value.role))
const lastAdmin = computed(() => selected.value?.role === 'MERCHANT_ADMIN' && selected.value.enabled && enabledAdmins.value <= 1)
const validPassword = computed(() => secret.value.length >= 6 && secret.value.length <= 200 && !!secret.value.trim())
const canSave = computed(() => !!selected.value && !busy.value && !loading.value && !stale.value && !!name.value.trim() && !!reason.value.trim())
const date = (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false })

function failed(cause: unknown) {
  if (cause instanceof ApiError && cause.status === 401) { emit('expired'); return }
  error.value = cause instanceof Error ? cause.message : '请求失败，请刷新后查看现状。'
  if (!(cause instanceof ApiError)) error.value = '请求结果尚未确认，请刷新查看账号与操作记录；不要直接重复提交。'
}
async function load(more = false) {
  const generation = ++listGeneration, token = props.account.access_token
  loading.value = true
  try {
    const page = await coreApi.adminAccounts(token, { ...applied }, more ? cursor.value : undefined)
    if (!alive || generation !== listGeneration || token !== props.account.access_token) return
    rows.value = more ? [...rows.value, ...page.items.filter(row => !rows.value.some(old => old.username === row.username))] : page.items
    total.value = page.total; cursor.value = page.page.next_cursor ?? undefined; enabledAdmins.value = page.enabled_admins; currentUsername.value = page.current_username
  } catch (cause) { if (alive && generation === listGeneration) failed(cause) }
  finally { if (alive && generation === listGeneration) loading.value = false }
}
function filter() {
  if (busy.value || loading.value) return
  applied = { query: query.value.trim(), role: role.value, status: status.value }
  closeDetails(); error.value = ''; notice.value = ''; void load()
}
function closeDetails() { selected.value = null; ++historyGeneration; history.value = []; historyError.value = ''; stale.value = false }
function select(row: AdminAccount) {
  if (busy.value || loading.value) return
  selected.value = { ...row }; name.value = row.display_name; selectedRole.value = row.role; enabled.value = row.enabled; reason.value = ''
  stale.value = false; error.value = ''; history.value = []; historyCursor.value = undefined; historyTotal.value = 0; void loadHistory()
}
async function loadHistory(more = false) {
  if (!selected.value) return
  const username = selected.value.username, generation = ++historyGeneration
  historyLoading.value = true; historyError.value = ''
  try {
    const page = await coreApi.accountHistory(props.account.access_token, username, more ? historyCursor.value : undefined)
    if (!alive || generation !== historyGeneration || selected.value?.username !== username) return
    history.value = more ? [...history.value, ...page.items] : page.items; historyCursor.value = page.page.next_cursor ?? undefined; historyTotal.value = page.total
  } catch (cause) {
    if (!alive || generation !== historyGeneration) return
    if (cause instanceof ApiError && cause.status === 401) emit('expired')
    else historyError.value = '操作记录暂不可用，请重试读取。'
  } finally { if (alive && generation === historyGeneration) historyLoading.value = false }
}
function openDialog(kind: 'create' | 'password') {
  if (busy.value || loading.value || (kind === 'password' && (!selected.value || stale.value))) return
  newUsername.value = ''; newName.value = ''; newRole.value = 'REVIEWER'; secret.value = ''; dialogReason.value = ''; error.value = ''; notice.value = ''; dialog.value = kind
}
function closeDialog() { if (busy.value) return; dialog.value = null; secret.value = ''; dialogReason.value = '' }
async function mutate(kind: 'save' | 'create' | 'password') {
  if (busy.value || loading.value || (kind === 'save' && !canSave.value) || (kind !== 'create' && (!selected.value || stale.value))) return
  if (kind !== 'save' && (!validPassword.value || !dialogReason.value.trim())) return
  if (kind === 'create' && (!newUsername.value.trim() || !newName.value.trim())) return
  const original = selected.value ? { ...selected.value } : null, token = props.account.access_token
  const password = secret.value; secret.value = ''; busy.value = true; emit('working', true); error.value = ''; notice.value = ''
  try {
    const result = kind === 'create'
      ? await coreApi.createStaff(token, { username: newUsername.value.trim(), display_name: newName.value.trim(), role: newRole.value, password, reason: dialogReason.value.trim() })
      : kind === 'password'
        ? await coreApi.resetAccountPassword(token, original!, password, dialogReason.value.trim())
        : await coreApi.updateAccount(token, original!, { display_name: name.value.trim(), role: selectedRole.value, enabled: enabled.value, reason: reason.value.trim() })
    if (!alive || token !== props.account.access_token) return
    if (result.session_invalidated) { emit('expired'); return }
    dialog.value = null; dialogReason.value = ''; reason.value = ''
    selected.value = result.account; name.value = result.account.display_name; selectedRole.value = result.account.role; enabled.value = result.account.enabled; stale.value = false
    if (result.account.username === currentUsername.value) emit('renamed', result.account.display_name)
    notice.value = kind === 'create' ? '工作人员已创建，可使用初始密码登录本商家工作台。' : kind === 'password' ? '密码已重置，该账号的旧会话已失效。' : '账号信息已保存。角色或启停变化后，该账号需重新登录。'
    await load(); await loadHistory()
  } catch (cause) {
    if (!alive || token !== props.account.access_token) return
    failed(cause)
    if (cause instanceof ApiError && cause.status === 409 && kind !== 'create') {
      stale.value = true; error.value = '账号已发生变化或操作受保护。草稿已保留，请在刷新后的列表重新打开并核对；不会自动重发。'; await load()
    }
  } finally { if (alive) { busy.value = false; emit('working', false) } }
}
onMounted(() => void load())
onBeforeUnmount(() => { alive = false; ++listGeneration; ++historyGeneration; secret.value = ''; emit('working', false) })
</script>

<template>
  <main class="people-workspace" aria-label="人员管理">
    <header class="people-heading"><div><p class="eyebrow">商家管理 · {{ account.merchant_name ?? account.merchant_id }}</p><h1>人员管理</h1><p class="muted">维护本商家账号与权限，让每一位工作人员各司其职。</p></div><button type="button" :disabled="busy || loading" @click="openDialog('create')"><Icon name="user" :size="17" />新增工作人员</button></header>
    <p v-if="error" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message success" role="status">{{ notice }}</p>
    <div class="people-columns" :class="{ 'with-details': selected }">
      <section class="panel people-list" aria-label="商家账号列表">
        <form class="people-filters" @submit.prevent="filter"><label class="people-search">搜索账号<input v-model="query" maxlength="100" placeholder="用户名或显示姓名" :disabled="busy || loading" /></label><label>角色<select v-model="role" aria-label="角色" :disabled="busy || loading"><option value="ALL">全部角色</option><option v-for="(label, value) in labels" :key="value" :value="value">{{ label }}</option></select></label><label>状态<select v-model="status" aria-label="状态" :disabled="busy || loading"><option value="ALL">全部状态</option><option value="ENABLED">已启用</option><option value="DISABLED">已停用</option></select></label><button class="secondary-button" type="submit" :disabled="busy || loading">查询</button></form>
        <div class="people-list-heading"><h2>账号列表 <span v-if="total !== null">（{{ total }}）</span></h2><span>已启用管理员 {{ total === null ? '—' : enabledAdmins }} 位 <button class="text-button" type="button" :disabled="busy || loading" @click="load()">刷新</button></span></div>
        <p v-if="loading" class="muted" role="status">正在读取账号…</p>
        <div class="people-table-wrap"><table><thead><tr><th>姓名 / 用户名</th><th>角色</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead><tbody><tr v-for="row in rows" :key="row.username" :class="{ selected: selected?.username === row.username }"><td><strong>{{ row.display_name }}</strong><small>{{ row.username }}<span v-if="row.username === currentUsername"> · 当前账号</span></small></td><td>{{ labels[row.role] }}</td><td><span class="status-tag" :class="{ enabled: row.enabled }">{{ row.enabled ? '已启用' : '已停用' }}</span></td><td class="people-time">{{ date(row.updated_at) }}</td><td><button class="text-button" type="button" :aria-label="`维护 ${row.username}`" :disabled="busy || loading" @click="select(row)">维护账号</button></td></tr></tbody></table></div>
        <div v-if="!loading && !rows.length" class="empty"><Icon name="user" :size="30" /><strong>没有符合条件的账号</strong><p>可调整角色、状态或查询条件。</p></div>
        <footer class="people-footer"><span>已显示 {{ rows.length }}<template v-if="total !== null"> / {{ total }}</template> 个账号</span><button v-if="cursor" class="secondary-button" type="button" :disabled="busy || loading" @click="load(true)">加载更多</button></footer>
        <p class="people-note"><Icon name="shield" :size="16" />账号归属保持固定。人员维护不会改变工单负责人，转交或接管需在工单中明确操作。</p>
      </section>
      <aside v-if="selected" class="panel people-details" aria-label="维护账号">
        <div class="people-list-heading"><h2>维护账号</h2><button class="text-button" type="button" aria-label="关闭维护栏" :disabled="busy" @click="closeDetails"><Icon name="close" :size="18" /></button></div>
        <div class="people-identity"><span class="avatar">{{ selected.display_name.slice(0, 1) }}</span><div><strong>{{ selected.display_name }}</strong><small>{{ selected.username }} · 版本 {{ selected.version }}</small></div></div>
        <p v-if="stale" class="message error">当前草稿不可提交，请从列表重新打开。</p>
        <form class="people-maintenance" @submit.prevent="mutate('save')">
          <label>显示姓名<input v-model="name" maxlength="120" :disabled="busy || stale" /></label>
          <label v-if="!fixedRole">账号角色<select v-model="selectedRole" :disabled="busy || stale || lastAdmin"><option value="REVIEWER">售后专员</option><option value="MERCHANT_ADMIN">商家管理员</option></select></label><p v-else class="muted">账号角色：{{ labels[selected.role] }}（固定）</p>
          <label class="people-toggle"><input v-model="enabled" type="checkbox" :disabled="busy || stale || lastAdmin" />启用此账号</label>
          <p v-if="lastAdmin" class="people-note">这是本商家最后一个启用管理员，不能停用或降级。</p>
          <p v-if="selected.username === currentUsername" class="people-note">修改自己的角色、启用状态或密码后，将退出当前工作台。</p>
          <label>操作理由<textarea v-model="reason" rows="3" maxlength="1000" placeholder="说明本次维护的原因" :disabled="busy || stale" /></label>
          <div class="people-actions"><button type="submit" :disabled="!canSave">{{ busy ? '正在保存…' : '保存修改' }}</button><button type="button" class="secondary-button" :disabled="busy || stale || loading" @click="openDialog('password')">重置密码</button></div>
        </form>
        <section class="people-history" aria-label="账号操作记录"><div class="people-list-heading"><h3>操作记录（{{ historyTotal }}）</h3><button class="text-button" type="button" :disabled="historyLoading || busy" @click="loadHistory()">刷新</button></div>
          <p v-if="historyLoading" class="muted">正在读取记录…</p><p v-else-if="historyError" class="message error">{{ historyError }}</p><p v-else-if="!history.length" class="muted">暂无维护记录。种子账号创建前的历史未记录。</p>
          <ol><li v-for="event in history" :key="event.id"><strong>{{ { CREATED: '新增账号', UPDATED: '维护账号', PASSWORD_RESET: '重置密码' }[event.action] }}</strong><small>{{ date(event.occurred_at) }} · {{ event.actor_username }} · v{{ event.account_version }}</small><p>{{ event.reason }}</p><details v-if="event.action !== 'PASSWORD_RESET'"><summary>查看状态变化</summary><p v-if="event.before">之前：{{ event.before.display_name }} / {{ labels[event.before.role] }} / {{ event.before.enabled ? '启用' : '停用' }}</p><p>之后：{{ event.after.display_name }} / {{ labels[event.after.role] }} / {{ event.after.enabled ? '启用' : '停用' }}</p></details></li></ol>
          <button v-if="historyCursor" class="secondary-button" type="button" :disabled="historyLoading || busy" @click="loadHistory(true)">更多操作记录</button>
        </section>
      </aside>
    </div>
    <ReviewDialog v-if="dialog" :title="dialog === 'create' ? '新增工作人员' : '重置账号密码'" workspace="人员管理" :busy="busy" @close="closeDialog">
      <form class="people-maintenance" @submit.prevent="mutate(dialog === 'create' ? 'create' : 'password')">
        <p class="people-note">所属商家：{{ account.merchant_name ?? account.merchant_id }}。{{ dialog === 'create' ? '仅新增本商家工作人员，用户名创建后固定。' : `目标账号：${selected?.username}。成功后该账号的旧会话立即失效。` }}</p>
        <template v-if="dialog === 'create'"><label>用户名<input v-model="newUsername" autocomplete="off" maxlength="120" pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,119}" required :disabled="busy" /></label><label>工作人员姓名<input v-model="newName" maxlength="120" required :disabled="busy" /></label><label>工作人员角色<select v-model="newRole" :disabled="busy"><option value="REVIEWER">售后专员</option><option value="MERCHANT_ADMIN">商家管理员</option></select></label></template>
        <label>{{ dialog === 'create' ? '初始密码' : '新密码' }}<input v-model="secret" type="password" autocomplete="new-password" minlength="6" maxlength="200" required :disabled="busy" /></label><small class="muted">6–200位；提交后清空，不会回显或保存在浏览器。</small>
        <label>操作理由<textarea v-model="dialogReason" rows="3" maxlength="1000" required :disabled="busy || stale && dialog === 'password'" /></label>
        <p v-if="error" class="message error" role="alert">{{ error }}</p>
        <div class="people-actions"><button type="button" class="secondary-button" :disabled="busy" @click="closeDialog">取消</button><button type="submit" :disabled="busy || !validPassword || !dialogReason.trim() || dialog === 'password' && stale || dialog === 'create' && (!newUsername.trim() || !newName.trim())">{{ busy ? '正在提交…' : dialog === 'create' ? '创建账号' : '确认重置' }}</button></div>
      </form>
    </ReviewDialog>
  </main>
</template>

<style scoped>
.people-workspace { min-width: 0; padding: 28px; background: var(--rf-subtle); }
.people-heading { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 24px; }
h1 { font-size: 24px; margin: 6px 0 10px; } h2 { font-size: 17px; margin: 0; } h3 { font-size: 14px; margin: 0; }
.people-heading > button { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
.people-columns { display: grid; gap: 20px; align-items: start; } .with-details { grid-template-columns: minmax(0, 1fr) 336px; }
.people-list { padding: 0; overflow: hidden; } .people-filters { display: flex; align-items: end; gap: 12px; padding: 20px; border-bottom: 1px solid var(--rf-line); }
.people-workspace label, .people-maintenance label { display: grid; gap: 8px; margin: 0; font-size: 12px; color: #506584; } input, select, textarea { min-width: 0; width: 100%; border: 1px solid #dce5f2; border-radius: 7px; padding: 10px 11px; background: white; color: #223654; font: inherit; font-size: 13px; }
.people-workspace input:not([type=checkbox]), .people-maintenance input:not([type=checkbox]), .people-maintenance textarea { margin: 0; }
select { min-width: 112px; } input:disabled, select:disabled, textarea:disabled { background: #f5f7fb; color: #8190a6; } textarea { resize: vertical; }
.people-search { flex: 1; min-width: 135px; } .people-filters > button { flex-shrink: 0; }
.people-list-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 20px; } .people-list-heading > span { font-size: 12px; color: var(--rf-muted); } h2 span { color: var(--rf-muted); font-size: 14px; }
.people-table-wrap { overflow-x: auto; } table { border-collapse: collapse; width: 100%; text-align: left; font-size: 12px; } th { padding: 13px 16px; background: var(--rf-subtle); color: #7a8da9; font-weight: 500; white-space: nowrap; } td { padding: 19px 16px; border-bottom: 1px solid #eef2f8; } td strong { display: block; font-size: 13px; } td small { display: block; margin-top: 6px; color: var(--rf-muted); overflow-wrap: anywhere; } tr.selected { background: #f0f6ff; } .people-time { color: #8394ad; font-size: 12px; white-space: nowrap; } .enabled { background: #edf9f2; color: #169651; border-color: #d4efdf; }
.people-footer { display: flex; align-items: center; justify-content: space-between; padding: 18px 20px; color: #8394ad; font-size: 12px; } .people-note { display: flex; gap: 8px; color: var(--rf-muted); font-size: 12px; line-height: 1.7; margin: 0; } .people-list > .people-note { padding: 16px 20px; background: #fbfcff; border-top: 1px solid var(--rf-line); }
.people-details { padding: 0 20px 20px; } .people-details > .people-list-heading { padding: 20px 0; } .people-identity { display: flex; align-items: center; gap: 12px; padding: 12px 0 24px; } .people-identity strong { display: block; font-size: 15px; } .people-identity small { display: block; color: var(--rf-muted); margin-top: 6px; font-size: 12px; overflow-wrap: anywhere; }
.people-maintenance { display: grid; gap: 17px; } .people-maintenance .people-toggle { display: flex; align-items: center; gap: 10px; } .people-maintenance .people-toggle input[type=checkbox] { flex: 0 0 16px; width: 16px; height: 16px; margin: 0; padding: 0; accent-color: var(--rf-accent); } .people-actions { display: flex; gap: 10px; justify-content: flex-end; } .people-actions > button { flex: 1; }
.people-history { margin-top: 24px; border-top: 1px solid var(--rf-line); } .people-history .people-list-heading { padding: 18px 0; } .people-history ol { max-height: 310px; overflow: auto; margin: 0; padding: 0; list-style: none; } .people-history li { border-left: 2px solid var(--rf-line); padding: 0 0 14px 13px; margin: 0 0 14px; font-size: 12px; overflow-wrap: anywhere; } .people-history small { display: block; color: var(--rf-muted); margin-top: 8px; font-size: 12px; } .people-history p { color: var(--rf-muted); line-height: 1.6; margin: 8px 0; } details { color: var(--rf-muted); font-size: 12px; }
@media (max-width: 1350px) { .people-workspace { padding: 22px; } .with-details { grid-template-columns: minmax(0, 1fr) 310px; gap: 14px; } .people-filters { flex-wrap: wrap; } .people-time { white-space: normal; min-width: 75px; } th, td { padding-left: 12px; padding-right: 12px; } }
@media (max-width: 1100px) { .with-details { grid-template-columns: 1fr; } }
@media(max-width: 1100px) { .with-details { grid-template-columns: minmax(0,1fr); }.people-heading { flex-wrap: wrap; }.people-filters { flex-wrap: wrap; } }
</style>
