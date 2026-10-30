<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiError, coreApi, type AdminPolicy, type AdminPolicyDetail, type LoginResponse } from '../client'
import Icon from './ReviewIcon.vue'

const props = defineProps<{ account: LoginResponse }>()
const emit = defineEmits<{ expired: [] }>()
const rows = ref<AdminPolicy[]>([]), detail = ref<AdminPolicyDetail | null>(null), selected = ref('')
const loading = ref(false), detailLoading = ref(false), error = ref(''), detailError = ref(''), truncated = ref(false), loaded = ref(false)
let alive = true, listGeneration = 0, detailGeneration = 0
const date = (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false })
const indexLabels = { READY: '索引已就绪', BUILDING: '索引构建中', FAILED: '索引构建失败', MISSING: '该版本尚无索引', UNAVAILABLE: '索引状态暂不可用' }
function coversNow(policy: AdminPolicy) { const now = Date.now(); return Date.parse(policy.effective_from) <= now && (!policy.effective_to || now < Date.parse(policy.effective_to)) }
function fail(cause: unknown, target: typeof error) {
  if (cause instanceof ApiError && cause.status === 401) emit('expired')
  else target.value = '暂时无法读取，请重试。'
}
async function select(bundle: string) {
  selected.value = bundle; detail.value = null; detailError.value = ''; detailLoading.value = true
  const g = ++detailGeneration, token = props.account.access_token
  try {
    const result = await coreApi.adminPolicy(token, bundle)
    if (alive && g === detailGeneration && token === props.account.access_token && selected.value === bundle) detail.value = result
  } catch (cause) { if (alive && g === detailGeneration && token === props.account.access_token) fail(cause, detailError) }
  finally { if (alive && g === detailGeneration) detailLoading.value = false }
}
async function load() {
  if (loading.value) return
  loading.value = true; error.value = ''
  const g = ++listGeneration, token = props.account.access_token
  try {
    const result = await coreApi.adminPolicies(token)
    if (!alive || g !== listGeneration || token !== props.account.access_token) return
    rows.value = result.items; truncated.value = result.truncated; loaded.value = true
    const id = rows.value.find(p => p.bundle_id === selected.value)?.bundle_id ?? rows.value[0]?.bundle_id
    if (id) void select(id)
    else { ++detailGeneration; selected.value = ''; detail.value = null; detailLoading.value = false }
  } catch (cause) { if (alive && g === listGeneration && token === props.account.access_token) fail(cause, error) }
  finally { if (alive && g === listGeneration) loading.value = false }
}
onMounted(() => { void load() })
onBeforeUnmount(() => { alive = false; ++listGeneration; ++detailGeneration })
</script>

<template>
  <main class="admin-workspace" aria-label="政策只读页面">
    <header class="admin-heading"><div><span class="admin-eyebrow">{{ account.merchant_name ?? account.merchant_id }} · 商家管理</span><h1>政策与版本</h1></div><button type="button" class="secondary-button" :disabled="loading" @click="load"><Icon name="clock" />{{ loading ? '更新中…' : '刷新政策' }}</button></header>

    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <p v-if="loading && !loaded" class="admin-loading" role="status">正在读取本商家政策…</p>
    <div v-if="rows.length" class="policy-layout">
      <section class="panel policy-version-list" aria-label="已导入政策版本"><div class="admin-card-heading"><h2>已导入版本（{{ rows.length }}）</h2></div><button v-for="policy in rows" :key="policy.bundle_id" type="button" class="policy-version" :aria-pressed="selected === policy.bundle_id" @click="select(policy.bundle_id)"><span class="policy-version-top"><Icon name="file" /><strong>{{ policy.version }}</strong><span class="admin-chip">已导入</span></span><span class="admin-id">{{ policy.bundle_id }}</span><small>生效起点 {{ date(policy.effective_from) }}</small><small>{{ policy.rule_count }} 条原始规则 · {{ coversNow(policy) ? '区间覆盖当前时间' : '区间不覆盖当前时间' }}</small></button><p v-if="truncated" class="admin-note">最多显示最近100个版本，更早版本仍保留在历史工单依据中。</p></section>
      <section class="panel admin-card policy-detail" aria-label="政策原文">
        <p v-if="detailLoading" class="admin-loading" role="status">正在读取所选版本原文与索引…</p>
        <div v-if="detailError" class="admin-empty"><p class="message error" role="alert">{{ detailError }}</p><button type="button" class="secondary-button" @click="select(selected)">重试所选版本</button></div>
        <template v-if="detail"><div class="admin-card-heading"><div><h2>政策原文 <span class="admin-chip">{{ detail.policy.version }}</span></h2><p class="admin-id">{{ detail.policy.bundle_id }}</p></div><span class="admin-index-status" :class="{ ready: detail.index.status === 'READY' }"><Icon :name="detail.index.status === 'READY' ? 'check' : 'clock'" :size="15" />{{ indexLabels[detail.index.status] }}</span></div>
          <dl class="policy-metadata"><div><dt>有效区间</dt><dd>{{ date(detail.policy.effective_from) }} 起<br />{{ detail.policy.effective_to ? date(detail.policy.effective_to) + ' 止（不含）' : '未指定结束时间' }}</dd></div><div><dt>导入时间</dt><dd>{{ date(detail.policy.imported_at) }}</dd></div><div><dt>规则数量</dt><dd>{{ detail.policy.rule_count }} 条</dd></div></dl>

          <article v-for="rule in detail.rules" :key="rule.rule_id" class="policy-original-rule"><div><span class="policy-rule-marker"><Icon name="file" :size="17" /></span><h3>{{ rule.title || rule.rule_id }}</h3><span class="admin-chip">{{ rule.rule_id }}</span></div><p>{{ rule.text }}</p><details><summary>查看条款来源标识</summary><dl><dt>块编号</dt><dd>{{ rule.chunk_id }}</dd><dt>内容hash</dt><dd>{{ rule.content_hash }}</dd></dl></details></article>
          <p v-if="!detail.rules.length" class="admin-note">这个已导入版本没有可展示的原始规则。</p>
          <details class="policy-source"><summary>查看固定政策版本与索引标识</summary><dl><dt>政策hash</dt><dd>{{ detail.policy.manifest_hash }}</dd><dt>安全版本</dt><dd>{{ detail.policy.safety_epoch }}</dd><dt>索引generation</dt><dd>{{ detail.index.generation_id ?? '暂无可核验记录' }}</dd><dt>索引块数</dt><dd>{{ detail.index.chunk_count ?? '未读取' }}</dd><dt>索引时间</dt><dd>{{ detail.index.built_at ? date(detail.index.built_at) : '未读取' }}</dd></dl></details>
        </template>
      </section>
    </div>
    <section v-else-if="loaded" class="panel admin-empty"><Icon name="file" :size="36" /><h2>本商家尚未导入政策</h2><button type="button" class="secondary-button" :disabled="loading" @click="load">重新读取</button></section>
  </main>
</template>
