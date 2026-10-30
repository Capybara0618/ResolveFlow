<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ApiError } from '../client'
import { enrollmentApi, type RecoveryReceipt } from '../enrollment-client'
const props = defineProps<{ mode: 'register' | 'recover' | 'rotate'; token?: string }>()
const emit = defineEmits<{ close: [username?: string]; working: [value: boolean]; expired: [] }>()
const username = ref(''), nickname = ref(''), password = ref(''), confirm = ref(''), recovery = ref(''), busy = ref(false), error = ref(''), saved = ref(false), receipt = ref<RecoveryReceipt | null>(null)
const title = computed(() => props.mode === 'register' ? '创建买家账号' : props.mode === 'recover' ? '找回账号' : '账号安全')
async function submit() {
  if (busy.value) return
  error.value = ''
  if (props.mode !== 'rotate' && password.value !== confirm.value) { error.value = '两次输入的密码不一致'; return }
  busy.value = true; emit('working', true)
  try { receipt.value = props.mode === 'register' ? await enrollmentApi.register(username.value, nickname.value, password.value) : props.mode === 'recover' ? await enrollmentApi.recover(username.value, recovery.value.trim(), password.value) : await enrollmentApi.rotate(props.token!, password.value)
    password.value = ''; confirm.value = ''; recovery.value = ''
  } catch (e) { if (e instanceof ApiError && e.status === 401) emit('expired'); error.value = e instanceof ApiError ? e.message : '保存结果尚未确认。可用刚才的账号密码登录后，在账号安全中重新生成恢复密钥。' }
  finally { busy.value = false; emit('working', false) }
}
watch(() => props.mode, () => { username.value = ''; nickname.value = ''; password.value = ''; confirm.value = ''; recovery.value = ''; error.value = ''; receipt.value = null; saved.value = false })
</script>
<template><section class="enrollment" :aria-label="title"><h1>{{ title }}</h1>
  <template v-if="receipt"><h2>{{ mode === 'register' ? '账号已创建' : mode === 'recover' ? '密码已更新' : '恢复密钥已更新' }}</h2><p>请妥善保存恢复密钥。忘记密码时，用它找回账号。</p><code class="recovery-key">{{ receipt.recovery_key }}</code><p>旧恢复密钥已失效。请勿把密钥发给他人。</p><label class="enrollment-check"><input v-model="saved" type="checkbox" />我已妥善保存恢复密钥</label><button class="shop-primary" :disabled="!saved" @click="emit('close', receipt.username)">{{ mode === 'rotate' ? '完成' : '去登录' }}</button></template>
  <form v-else @submit.prevent="submit"><p v-if="mode === 'recover'">使用注册时保存的恢复密钥重设买家账号密码。</p><p v-if="mode === 'recover'">没有恢复密钥时，可联系平台管理员协助重置。</p><p v-if="mode === 'rotate'">验证当前密码后，生成新的恢复密钥。</p>
    <label v-if="mode !== 'rotate'">账号<input v-model="username" autocomplete="username" required minlength="3" maxlength="60" pattern="[a-zA-Z0-9][a-zA-Z0-9_-]{2,59}" :disabled="busy" /></label>
    <label v-if="mode === 'register'">昵称<input v-model="nickname" autocomplete="nickname" required maxlength="120" :disabled="busy" /></label>
    <label v-if="mode === 'recover'">恢复密钥<input v-model="recovery" type="password" autocomplete="off" required minlength="64" maxlength="64" :disabled="busy" /></label>
    <label>{{ mode === 'rotate' ? '当前密码' : mode === 'recover' ? '新密码' : '密码' }}<input v-model="password" type="password" :autocomplete="mode === 'rotate' ? 'current-password' : 'new-password'" required :minlength="mode === 'rotate' ? 1 : 8" maxlength="200" :disabled="busy" /></label>
    <label v-if="mode !== 'rotate'">确认密码<input v-model="confirm" type="password" autocomplete="new-password" required minlength="8" maxlength="200" :disabled="busy" /></label>
    <p v-if="error" role="alert">{{ error }}</p><button class="shop-primary" :disabled="busy">{{ busy ? '正在保存…' : mode === 'register' ? '创建账号' : mode === 'recover' ? '重设密码' : '生成恢复密钥' }}</button><button type="button" class="enrollment-back" :disabled="busy" @click="emit('close')">{{ mode === 'rotate' ? '返回个人中心' : '返回登录' }}</button>
  </form></section></template>
<style scoped>.enrollment{max-width:440px;width:100%;box-sizing:border-box;margin:32px auto;padding:32px;background:#fffdf8;border:1px solid #e0e4db;border-radius:var(--rf-radius-surface);color:#293d34}.enrollment h1{font-size:26px;font-weight:500;margin:0 0 24px}.enrollment h2{font-size:19px}.enrollment p{font-size:14px;line-height:1.7;color:#637165}.enrollment form>label{display:grid;gap:8px;margin:18px 0}.enrollment input:not([type=checkbox]){box-sizing:border-box;width:100%;min-height:44px;font:inherit;font-size:15px;border:1px solid #cdd7cb;border-radius:7px;padding:11px}.enrollment button{min-height:40px;font-size:14px;font:inherit;padding:10px 16px;border-radius:8px;cursor:pointer}.enrollment .shop-primary{background:#205e50;color:white;border:1px solid #205e50}.enrollment-back{border:0;background:none;color:#205e50;margin-top:12px}.enrollment button:disabled{opacity:.5;cursor:default}.recovery-key{display:block;overflow-wrap:anywhere;padding:16px;font-size:15px;line-height:1.8;background:#f0f3eb;border-radius:8px}.enrollment-check{display:flex;align-items:center;gap:8px;font-size:14px;margin:24px 0}.enrollment [role=alert]{color:#a33e31}</style>
