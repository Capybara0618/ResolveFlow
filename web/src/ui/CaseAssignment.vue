<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { ApiError, coreApi, type CaseCollaboration, type CollaborationAction } from '../client'
import ReviewDialog from './ReviewDialog.vue'

const props = defineProps<{ token: string; current: CaseCollaboration | null; loading: boolean; busy: boolean }>()
const emit = defineEmits<{ changed: []; working: [value: boolean]; expired: [] }>()
const action = ref<CollaborationAction | null>(null)
const captured = ref<CaseCollaboration | null>(null)
const reason = ref('')
const target = ref('')
const error = ref('')
const message = ref('')
const staff = ref<NonNullable<CaseCollaboration['owner']>[]>([])
const loadingStaff = ref(false)
const submitting = ref(false)
let active = true
let generation = 0
let feedbackCase = props.current?.case_id
let feedbackToken = props.token
const labels: Record<CollaborationAction, string> = { CLAIM: '领取工单', RELEASE: '释放工单', TRANSFER: '转交工单', TAKEOVER: '管理员接管' }
const candidates = computed(() => staff.value.filter(item => item.username !== captured.value?.owner?.username))
function close() { action.value = null; captured.value = null; reason.value = ''; target.value = ''; generation++ }
watch(() => `${props.token}:${props.current?.case_id}:${props.current?.version}`, () => {
  close()
  // A refresh temporarily clears current. Keep the outcome for this case, but never
  // carry it to another case/account or leave an old form open at the new version.
  if (props.token !== feedbackToken || (props.current && props.current.case_id !== feedbackCase)) {
    message.value = ''; error.value = ''
  }
  feedbackToken = props.token
  if (props.current) feedbackCase = props.current.case_id
})
onUnmounted(() => { active = false; generation++ })
async function open(next: CollaborationAction) {
  if (props.busy || !props.current?.allowed_actions.includes(next)) return
  error.value = ''; captured.value = props.current; action.value = next; reason.value = ''; target.value = ''; staff.value = []
  if (next !== 'TRANSFER') return
  loadingStaff.value = true
  const request = ++generation; const token = props.token
  try {
    const result = await coreApi.reviewStaff(token)
    if (active && request === generation && token === props.token) staff.value = result
  } catch (cause) {
    if (active && request === generation && token === props.token) {
      error.value = cause instanceof Error ? cause.message : '无法读取本商家工作人员'
      if (cause instanceof ApiError && cause.status === 401) emit('expired')
    }
  } finally { if (active && request === generation) loadingStaff.value = false }
}
async function submit() {
  const current = captured.value; const next = action.value; const token = props.token
  if (!current || !next || !reason.value.trim() || submitting.value || (next === 'TRANSFER' && !target.value)) return
  submitting.value = true; emit('working', true); error.value = ''; message.value = ''
  let refresh = false
  try {
    await coreApi.changeCollaboration(token, current, next, reason.value.trim(), next === 'TRANSFER' ? target.value : undefined)
    if (!active || token !== props.token) return
    message.value = `${labels[next]}已记录`; close(); refresh = true
  } catch (cause) {
    if (!active || token !== props.token) return
    error.value = cause instanceof ApiError && cause.status === 409
      ? '负责人或工单状态已变化，请刷新后重新操作。' : cause instanceof Error ? cause.message : '提交结果未确认，请刷新查看归属'
    if (cause instanceof ApiError && cause.status === 401) emit('expired')
    if (cause instanceof ApiError && cause.status === 409) { close(); refresh = true }
  } finally { submitting.value = false; if (active && token === props.token) { emit('working', false); if (refresh) emit('changed') } }
}
</script>

<template>
  <section class="assignment-panel" aria-label="工单负责人">
    <div class="assignment-heading"><div><h3>工单负责人</h3><p v-if="loading">正在读取负责人…</p><p v-else-if="current?.owner"><strong>{{ current.owner.display_name }}</strong><span v-if="!current.owner.enabled"> · 账号已禁用</span><span>{{ current.is_owner ? ' · 我负责' : ' · 当前仅可查看' }}</span></p><p v-else-if="current">{{ current.allowed_actions.includes('CLAIM') ? '未领取 · 请先领取，再执行人工审核' : '未分配负责人 · 当前仅可查看' }}</p><p v-else>负责人信息未加载，暂不开放人工操作</p></div><button type="button" class="secondary-button" :disabled="busy || loading" @click="emit('changed')">刷新归属</button></div>
    <div v-if="current && !loading" class="assignment-actions"><button v-for="next in current.allowed_actions" :key="next" type="button" :class="next === 'CLAIM' ? '' : 'secondary-button'" :disabled="busy" @click="open(next)">{{ labels[next] }}</button></div>
    <p v-if="current && !current.allowed_actions.length" class="subtle">当前身份没有可用的归属操作，可查看负责人和协作记录。</p>
    <p v-if="current && error && !action" role="alert" class="message error">{{ error }}</p><p v-if="current && message" role="status" class="message">{{ message }}</p>
    <details v-if="current?.history.length" class="assignment-history"><summary>协作记录（{{ current.history.length }}）</summary><ol><li v-for="item in current.history" :key="item.version"><strong>{{ labels[item.action] }}</strong> · {{ item.actor_username }}<p>{{ item.reason }}</p><small>{{ item.from_username || '未领取' }} → {{ item.to_username || '未领取' }} · {{ new Date(item.occurred_at).toLocaleString('zh-CN') }}</small></li></ol></details>
    <ReviewDialog v-if="action && captured" :title="labels[action]" :busy="submitting" @close="close">
      <p>当前负责人：{{ captured.owner?.display_name || '未领取' }}</p><p v-if="action === 'TAKEOVER'" class="subtle">接管会将负责人改为你，之后仍需核对材料并单独审批。</p>
      <label v-if="action === 'TRANSFER'">转交给<select v-model="target" :disabled="loadingStaff || submitting"><option value="">{{ loadingStaff ? '正在读取工作人员…' : '请选择本商家工作人员' }}</option><option v-for="person in candidates" :key="person.username" :value="person.username">{{ person.display_name }}</option></select></label>
      <p v-if="action === 'TRANSFER' && !loadingStaff && !candidates.length" class="subtle">暂无可转交的工作人员，请刷新归属后重试。</p>
      <label>操作理由<textarea v-model="reason" rows="3" maxlength="1000" placeholder="请说明领取或更改归属的理由" /></label>
      <p v-if="error" role="alert" class="message error">{{ error }}</p><div class="dialog-actions"><button type="button" class="secondary-button" :disabled="submitting" @click="close">取消</button><button type="button" :disabled="submitting || !reason.trim() || (action === 'TRANSFER' && (!target || loadingStaff))" @click="submit">{{ submitting ? '正在提交…' : '确认' + labels[action] }}</button></div>
    </ReviewDialog>
  </section>
</template>

<style scoped>
.assignment-panel{margin:16px 0;padding:16px;border:1px solid #dbe7f7;border-radius:10px;background:#f5f9ff}.assignment-heading{display:flex;align-items:center;justify-content:space-between;gap:16px}.assignment-heading h3{font-size:15px;margin:0 0 6px}.assignment-heading p{margin:0;color:#60718c;font-size:13px}.assignment-heading strong{color:#152b4e}.assignment-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}.assignment-history{margin-top:12px;font-size:13px;color:#60718c}.assignment-history ol{padding-left:20px}.assignment-history li{margin-top:10px}.assignment-history p{margin:4px 0}.assignment-history small{overflow-wrap:anywhere}
</style>
