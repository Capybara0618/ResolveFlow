<script setup lang="ts">
import { computed, ref, watch, onBeforeUnmount, useId } from 'vue'
import { ApiError, type LoginResponse } from '../client'
import { accountApi, type AccountProfile, type Address, type AddressInput } from '../account-client'
import { enrollmentApi } from '../enrollment-client'
import ReviewDialog from './ReviewDialog.vue'
import type { AccountEditMemory } from './account-edit-memory'
import UserAvatar from './UserAvatar.vue'
import './account-workspace.css'
const props = withDefaults(defineProps<{ account: LoginResponse; mode?: 'profile' | 'addresses'; memory?: AccountEditMemory; embedded?: boolean }>(), { mode: 'profile' })
const localMemory: AccountEditMemory = {}
const memory = () => props.memory ?? localMemory
const latestProfile = ref<AccountProfile | null>(null)
const addressFormId = useId(), loginFormId = useId()
const emit = defineEmits<{ expired: []; reauthenticate: [loginName: string]; saved: [profile: AccountProfile]; changed: []; working: [value: boolean] }>()
const profile = ref<AccountProfile | null>(null), nickname = ref(''), rows = ref<Address[]>([])
const loading = ref(false), busy = ref(false), error = ref(''), notice = ref(''), editing = ref(false), editingId = ref<string | null>(null), deleting = ref<Address | null>(null)
const empty = (): AddressInput => ({ recipient: '', phone: '', province: '', city: '', district: '', detail: '', is_default: false })
const form = ref<AddressInput>(empty())
const contactPhone = ref(''), gender = ref('UNDISCLOSED'), birthday = ref(''), loginName = ref(''), password = ref(''), changingLogin = ref(false)
const today = new Date().toLocaleDateString('en-CA')
const age = computed(() => { if (!birthday.value) return null; const date = new Date(`${birthday.value}T00:00:00`), now = new Date(); return now.getFullYear()-date.getFullYear() - (now.getMonth()<date.getMonth() || now.getMonth()===date.getMonth() && now.getDate()<date.getDate() ? 1 : 0) })
function fillProfile(p: AccountProfile) { profile.value = p; nickname.value = p.display_name; contactPhone.value = p.phone ?? ''; gender.value = p.gender ?? 'UNDISCLOSED'; birthday.value = p.birth_date ?? ''; loginName.value = p.login_name ?? p.username }
function rememberProfile() { if (profile.value) memory().profile = { version: profile.value.version, nickname: nickname.value, phone: contactPhone.value, gender: gender.value, birthday: birthday.value } }
function restoreProfile(p: AccountProfile) {
  fillProfile(p); const draft = memory().profile; latestProfile.value = null
  if (draft) { nickname.value = draft.nickname; contactPhone.value = draft.phone; gender.value = draft.gender; birthday.value = draft.birthday; profile.value = { ...p, version: draft.version }; if (p.version !== draft.version) latestProfile.value = p }
}
function resolveProfile(keep: boolean) { const p = latestProfile.value; if (!p) return; latestProfile.value = null; error.value = ''; if (keep) { profile.value = p; rememberProfile() } else { delete memory().profile; fillProfile(p) } }
function rememberAddress() { memory().address = { id: editingId.value, form: { ...form.value } } }
function dismissAddress(discard = false) { if (busy.value) return; if (discard) delete memory().address; else rememberAddress(); editing.value = false; error.value = '' }
function resumeAddress() { const draft = memory().address; if (!draft) return; editingId.value = draft.id; form.value = { ...draft.form }; editing.value = true; error.value = '' }
function closeLogin() { if (!busy.value) { changingLogin.value = false; password.value = ''; error.value = '' } }
function changeLogin() { void act(async () => { await enrollmentApi.changeLogin(props.account.access_token, loginName.value, password.value, profile.value!.version); password.value = ''; changingLogin.value = false; emit('reauthenticate', loginName.value) }) }
let alive = true, generation = 0
function fail(e: unknown) { if (e instanceof ApiError && e.status === 401) emit('expired'); error.value = e instanceof Error ? e.message : '暂时无法保存，请重试' }
async function load() {
  const g = ++generation; loading.value = true; error.value = ''; notice.value = ''
  try { if (props.mode === 'profile') { const p = await accountApi.profile(props.account.access_token); if (alive && g === generation) restoreProfile(p) }
    else { const result = await accountApi.addresses(props.account.access_token); if (alive && g === generation) rows.value = result.items }
  } catch (e) { if (alive && g === generation) fail(e) } finally { if (alive && g === generation) loading.value = false }
}
async function act(job: () => Promise<void>) { if (busy.value) return; busy.value = true; emit('working', true); error.value = ''; notice.value = ''; try { await job() } catch (e) { if (alive) fail(e) } finally { if (alive) { busy.value = false; emit('working', false) } } }
function updated(p: AccountProfile, replaceFields = true) { if (!alive) return; if (replaceFields) { delete memory().profile; latestProfile.value = null; fillProfile(p) } else { profile.value = p; if (memory().profile) rememberProfile() } emit('saved', p); window.dispatchEvent(new Event('resolveflow-profile-updated')); notice.value = '已保存' }
function saveProfile() { if (latestProfile.value) return; void act(async () => { updated(await accountApi.save(props.account.access_token, nickname.value, profile.value!.version, { phone: contactPhone.value, gender: gender.value, birth_date: birthday.value || null })) }) }
function upload(event: Event) { const input = event.target as HTMLInputElement, file = input.files?.[0]; input.value = ''; if (!file || !profile.value) return
  if (file.size > 2 * 1024 * 1024 || !['image/png', 'image/jpeg'].includes(file.type)) { error.value = '请选择2MB以内的PNG或JPEG图片'; return }
  void act(async () => { updated(await accountApi.upload(props.account.access_token, file, profile.value!.version), false) }) }
function edit(row?: Address) { editingId.value = row?.address_id ?? null; form.value = row ? { recipient: row.recipient, phone: row.phone, province: row.province, city: row.city, district: row.district, detail: row.detail, is_default: row.is_default, expected_version: row.version } : empty(); editing.value = true; error.value = ''; rememberAddress() }
async function reloadAddress() { if (busy.value || !editingId.value) return; await act(async () => { const result = await accountApi.addresses(props.account.access_token); if (!alive) return; rows.value = result.items; const row = result.items.find(a => a.address_id === editingId.value); if (row) edit(row); else error.value = '这条地址已删除，请关闭后添加新地址' }) }
function saveAddress() { void act(async () => { await accountApi.saveAddress(props.account.access_token, editingId.value, form.value); if (!alive) return; editing.value = false; delete memory().address; await load(); emit('changed'); notice.value = '地址已保存' }) }
function makeDefault(row: Address) { void act(async () => { const { address_id, version, ...fields } = row; await accountApi.saveAddress(props.account.access_token, address_id, { ...fields, is_default: true, expected_version: version }); await load(); emit('changed') }) }
function remove() { if (!deleting.value) return; const row = deleting.value; void act(async () => { await accountApi.deleteAddress(props.account.access_token, row); deleting.value = null; await load(); emit('changed'); notice.value = '地址已删除' }) }
watch(() => [props.account.access_token, props.mode], () => { editing.value = false; deleting.value = null; changingLogin.value = false; password.value = ''; profile.value = null; rows.value = []; void load() }, { immediate: true })
onBeforeUnmount(() => { alive = false; generation++ })
</script>
<template>
  <component :is="embedded ? 'section' : 'main'" class="account-workspace" :class="{ embedded }" :aria-label="mode === 'profile' ? '个人资料' : '收货地址'">
    <header v-if="!embedded" class="account-page-header"><h1>{{ mode === 'profile' ? '个人资料' : '收货地址' }}</h1><button :disabled="busy || loading" @click="load">刷新</button></header>
    <p v-if="error && !editing && !deleting && !changingLogin" role="alert" class="account-error">{{ error }}</p>
    <p v-if="loading && !profile && !rows.length" role="status">正在读取…</p>
    <form v-if="mode === 'profile' && profile" class="account-card profile-form" @submit.prevent="saveProfile" @input="rememberProfile" @change="rememberProfile">
      <div class="account-avatar-edit"><label class="avatar-upload-circle" title="PNG或JPEG，2MB以内"><UserAvatar :token="account.access_token" :source="profile.avatar_id ? '/api/v1/account/avatar' : undefined" :name="profile.display_name" :kind="account.role === 'MERCHANT_ADMIN' ? 'MERCHANT' : 'CUSTOMER'" :size="72" /><input type="file" accept="image/png,image/jpeg" :disabled="busy" aria-label="上传头像" @change.stop="upload" /><span>更换头像</span></label><div><h2>{{ profile.display_name }}</h2><button v-if="profile.avatar_id" type="button" :disabled="busy" @click="act(async () => updated(await accountApi.reset(account.access_token, profile!.version), false))">恢复默认头像</button></div></div>
      <div class="account-login-row"><span>登录账号</span><strong>{{ profile.login_name || profile.username }}</strong><button v-if="account.buyer_id" type="button" :disabled="busy" @click="changingLogin = true; loginName = profile.login_name || profile.username; password = ''; error = ''">修改账号</button></div>
      <div class="profile-fields"><label>昵称<input v-model="nickname" required maxlength="120" :disabled="busy" autocomplete="nickname" /></label><label>联系电话<input v-model="contactPhone" type="tel" maxlength="32" autocomplete="tel" :disabled="busy" placeholder="选填" /></label><label>性别<select v-model="gender" :disabled="busy"><option value="UNDISCLOSED">不透露</option><option value="FEMALE">女</option><option value="MALE">男</option><option value="OTHER">其他</option></select></label><label>生日<span v-if="age !== null && age >= 0" class="profile-age">{{ age }}岁</span><input v-model="birthday" type="date" min="1900-01-01" :max="today" :disabled="busy" /></label></div>
      <div v-if="latestProfile" class="account-conflict" role="alert"><p>资料有新版本。你的修改已保留。</p><button type="button" @click="resolveProfile(false)">使用最新资料</button><button type="button" @click="resolveProfile(true)">保留我的修改</button></div>
      <div class="account-save-row"><button class="shop-primary" :disabled="busy || !!latestProfile || !nickname.trim()">{{ busy ? '正在保存…' : '保存资料' }}</button><span role="status">{{ notice }}</span></div>
    </form>
    <ReviewDialog v-if="changingLogin && profile" title="修改登录账号" :busy="busy" compact @close="closeLogin">
      <form :id="loginFormId" class="login-name-form account-editor" @submit.prevent="changeLogin"><label>新账号<input v-model="loginName" required pattern="[a-zA-Z0-9][a-zA-Z0-9_-]{2,59}" maxlength="60" :disabled="busy" autocomplete="username" /></label><label>当前密码<input v-model="password" required type="password" autocomplete="current-password" :disabled="busy" /></label><p>修改后，请使用新账号重新登录。</p><p v-if="error" role="alert" class="account-error">{{ error }}</p></form>
      <template #footer><button type="button" :disabled="busy" @click="closeLogin">取消</button><button type="submit" :form="loginFormId" class="shop-primary" :disabled="busy">{{ busy ? '正在保存…' : '确认修改' }}</button></template>
    </ReviewDialog>
    <template v-if="mode === 'addresses'">
      <div class="address-toolbar"><button class="shop-primary" :disabled="busy" @click="edit()">添加收货地址</button><button v-if="memory().address && !editing" :disabled="busy" @click="resumeAddress">继续编辑地址</button><span role="status">{{ notice }}</span></div>
      <p v-if="!loading && !rows.length" class="account-empty">还没有收货地址</p>
      <article v-for="row in rows" :key="row.address_id" class="account-card address-row"><div><strong>{{ row.recipient }}</strong><span>{{ row.phone }}</span><small v-if="row.is_default">默认</small></div><p>{{ row.province }} {{ row.city }} {{ row.district }} {{ row.detail }}</p><div class="account-actions"><button :disabled="busy" @click="edit(row)">编辑</button><button v-if="!row.is_default" :disabled="busy" @click="makeDefault(row)">设为默认</button><button :disabled="busy" @click="deleting = row; error = ''">删除</button></div></article>
      <ReviewDialog v-if="editing" :title="editingId ? '编辑收货地址' : '添加收货地址'" :busy="busy" @close="dismissAddress()">
        <form :id="addressFormId" class="address-form account-editor" @submit.prevent="saveAddress" @input="rememberAddress" @change="rememberAddress">
          <div class="address-contact"><label>收货人<input v-model="form.recipient" required maxlength="80" autocomplete="name" :disabled="busy" /></label><label>联系电话<input v-model="form.phone" required maxlength="32" type="tel" autocomplete="tel" :disabled="busy" /></label></div>
          <div class="address-region"><label>省份<input v-model="form.province" required maxlength="80" autocomplete="address-level1" :disabled="busy" /></label><label>城市<input v-model="form.city" required maxlength="80" autocomplete="address-level2" :disabled="busy" /></label><label>区县<input v-model="form.district" required maxlength="80" autocomplete="address-level3" :disabled="busy" /></label></div>
          <label>详细地址<textarea v-model="form.detail" required maxlength="300" autocomplete="street-address" :disabled="busy" /></label><label class="account-check"><input v-model="form.is_default" type="checkbox" :disabled="busy" />设为默认地址</label><p v-if="error" role="alert" class="account-error">{{ error }}</p><button v-if="error && editingId" type="button" :disabled="busy" @click="reloadAddress">放弃修改并读取最新地址</button>
        </form>
        <template #footer><button type="button" :disabled="busy" @click="dismissAddress(true)">取消</button><button class="shop-primary" type="submit" :form="addressFormId" :disabled="busy">{{ busy ? '正在保存…' : '保存地址' }}</button></template>
      </ReviewDialog>
      <ReviewDialog v-if="deleting" title="删除收货地址？" :busy="busy" compact @close="deleting = null; error = ''"><p>{{ deleting.recipient }}　{{ deleting.phone }}</p><p>{{ deleting.province }} {{ deleting.city }} {{ deleting.district }} {{ deleting.detail }}</p><p v-if="error" role="alert" class="account-error">{{ error }}</p><template #footer><button :disabled="busy" @click="deleting = null">保留地址</button><button class="dialog-danger" :disabled="busy" @click="remove">确认删除</button></template></ReviewDialog>
    </template>
  </component>
</template>
