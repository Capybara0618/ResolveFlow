<script setup lang="ts">
import { computed } from 'vue'
import type { CaseSnapshot, InvestigationObservation } from '../client'
const props = defineProps<{ snapshot: CaseSnapshot; observations?: InvestigationObservation[] }>()
type Finding = { kind: 'FACT' | 'INFERENCE' | 'CONFLICT'; text: string; observation_ids: string[] }
const labels = { FACT: '来源陈述 · Agent 整理', INFERENCE: '模型判断', CONFLICT: '信息冲突' }
const findings = computed(() => {
  const values = props.snapshot.proposal?.review_findings
  if (!Array.isArray(values)) return []
  return values.filter((item): item is Finding => item && typeof item === 'object'
    && ['FACT', 'INFERENCE', 'CONFLICT'].includes(item.kind) && typeof item.text === 'string' && Array.isArray(item.observation_ids))
})
const missing = computed(() => {
  const values = props.snapshot.proposal?.missing_evidence
  return Array.isArray(values) ? values.filter((item): item is string => typeof item === 'string') : []
})
function source(id: string) {
  const material = props.snapshot.evidence.find(item => item.observation_id === id)
  if (material) return { text: material.content, ref: material.source_ref, version: material.source_version,
    verification: material.verification_result, available: true }
  const refs = props.snapshot.proposal?.evidence_refs
  const citation = Array.isArray(refs) ? refs.find(item => item?.observation_id === id) : null
  const recorded = props.observations?.find(item => item.observation_id === id && item.result !== null && !item.body_omitted && !item.error_code
    && item.source_ref === citation?.source_ref && item.source_version === citation?.source_version && item.content_hash === citation?.content_hash)
  if (recorded) return { text: JSON.stringify(recorded.result, null, 2), ref: recorded.source_ref,
    version: recorded.source_version, available: true, verification: undefined }
  return { text: '此观察的原始正文尚未提供给审核页面，请勿仅凭摘要认定事实。', ref: citation?.source_ref,
    version: citation?.source_version, available: false, verification: undefined }
}
</script>

<template>
  <div class="investigation-findings" aria-label="调查依据与待确认事项">
    <p v-if="snapshot.proposal?.status === 'STALE'" class="finding-warning">这份建议对应旧版材料，已过期。请等待新调查或形成人工方案。</p>
    <p v-if="snapshot.proposal?.refusal_reason" class="finding-warning">服务端复核未通过：{{ snapshot.proposal.refusal_reason }}</p>
    <template v-if="findings.length">
      <p class="finding-note">以下内容由 Agent 整理，请结合原始记录核对；来源陈述不等于真实性已核验。</p>
      <article v-for="(finding, index) in findings" :key="index" class="finding" :class="finding.kind.toLowerCase()">
        <strong>{{ labels[finding.kind] }}</strong><p>{{ finding.text }}</p>
        <details v-for="id in finding.observation_ids" :key="id"><summary>核对依据：{{ source(id).ref || id }}</summary>
          <p :class="{ 'finding-warning': !source(id).available }">{{ source(id).text }}</p>
          <small>观察 {{ id }} · 版本 {{ source(id).version || '未提供' }}</small>
          <small v-if="source(id).verification">人工核验记录：{{ source(id).verification }}</small>
        </details>
      </article>
    </template>
    <div v-if="missing.length" class="finding missing"><strong>仍需补充或确认</strong><ul><li v-for="item in missing" :key="item">{{ item }}</li></ul></div>
    <p v-if="snapshot.proposal?.origin === 'AGENT' && !findings.length" class="finding-note">该历史方案未记录分项调查依据，请核对下方引用及原始材料。</p>
  </div>
</template>

<style scoped>
.finding { margin: 10px 0; padding: 12px; background: #ffffffa8; border: 1px solid #dce7f8; border-radius: 8px; }
.finding strong { font-size: 12px; color: #245fbe; }
.finding p { font-size: 13px; line-height: 1.7; margin: 6px 0; white-space: pre-wrap; }
.finding details { margin-top: 8px; font-size: 12px; overflow-wrap: anywhere; }
.finding summary { cursor: pointer; color: #3f5e91; }
.finding small { display: block; color: #75839a; }
.finding.conflict, .finding.missing { background: #fff8ee; border-color: #f2dfb9; }
.finding-note { font-size: 12px; color: #63758f; line-height: 1.7; }
.finding-warning { color: #9b4e16; background: #fff6e9; padding: 10px; border-radius: 6px; line-height: 1.7; }
</style>
