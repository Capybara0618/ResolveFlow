<script setup lang="ts">
/**
 * The proposal's own findings, each linked back to what the run actually read.
 *
 * The one rule this file exists to keep: a finding may only be shown next to a source when the
 * proposal's citation for that source matches it on **all four** members
 * (`observation_id`/`source_ref`/`source_version`/`content_hash`,
 * `docs/core-contracts.md:101`). Matching on the id alone is how an old proposal comes to look
 * like it cites current content — an id that was re-read at a new version would silently show
 * today's text beside yesterday's finding. When the citation is missing or does not match, the
 * page says so and shows nothing in its place.
 */
import { computed } from 'vue'
import type { CaseSnapshot, InvestigationObservation } from '../client'
import { sourceOf, type SourceView } from './investigation-format'

const props = defineProps<{ snapshot: CaseSnapshot; observations?: InvestigationObservation[] }>()
type Finding = { kind: 'FACT' | 'INFERENCE' | 'CONFLICT'; text: string; observation_ids: string[] }
const labels = { FACT: '来源陈述 · Agent 整理', INFERENCE: '模型判断', CONFLICT: '信息冲突' }
const findings = computed(() => {
  const values = props.snapshot.proposal?.review_findings
  if (!Array.isArray(values)) return []
  return values.filter((item): item is Finding => !!item && typeof item === 'object'
    && ['FACT', 'INFERENCE', 'CONFLICT'].includes(item.kind) && typeof item.text === 'string' && Array.isArray(item.observation_ids))
})
const missing = computed(() => {
  const values = props.snapshot.proposal?.missing_evidence
  return Array.isArray(values) ? values.filter((item): item is string => typeof item === 'string') : []
})
const views = computed(() => {
  const map = new Map<string, SourceView>()
  for (const finding of findings.value) {
    for (const id of finding.observation_ids) {
      if (!map.has(id)) map.set(id, sourceOf(id, props.snapshot, props.observations ?? []))
    }
  }
  return map
})
const view = (id: string) => views.value.get(id) ?? sourceOf(id, props.snapshot, props.observations ?? [])
</script>

<template>
  <div class="investigation-findings" aria-label="调查依据与待确认事项">
    <p v-if="snapshot.proposal?.status === 'STALE'" class="finding-warning">这份建议对应旧版材料，已过期。请等待新调查或形成人工方案。</p>
    <p v-if="snapshot.proposal?.refusal_reason" class="finding-warning">服务端复核未通过：{{ snapshot.proposal.refusal_reason }}</p>
    <template v-if="findings.length">
      <article v-for="(finding, index) in findings" :key="index" class="finding" :class="finding.kind.toLowerCase()">
        <strong>{{ labels[finding.kind] }}</strong><p>{{ finding.text }}</p>
        <details v-for="id in finding.observation_ids" :key="id">
          <summary>核对依据：{{ view(id).ref || id }}</summary>
          <template v-if="view(id).state === 'MATERIAL'">
            <p>{{ (view(id) as Extract<SourceView, { state: 'MATERIAL' }>).text }}</p>
            <small>观察 {{ id }} · 版本 {{ view(id).version || '未提供' }} · 四项引用与本条材料一致</small>
            <small v-if="(view(id) as Extract<SourceView, { state: 'MATERIAL' }>).verification">人工核验记录：{{ (view(id) as Extract<SourceView, { state: 'MATERIAL' }>).verification }}</small>
          </template>
          <template v-else-if="view(id).state === 'OBSERVATION'">
            <dl v-if="(view(id) as Extract<SourceView, { state: 'OBSERVATION' }>).facts.length" class="finding-facts">
              <template v-for="fact in (view(id) as Extract<SourceView, { state: 'OBSERVATION' }>).facts" :key="fact.label">
                <dt>{{ fact.label }}</dt><dd>{{ fact.value }}</dd>
              </template>
            </dl>
            <details class="finding-raw"><summary>展开完整原始结果</summary><pre>{{ (view(id) as Extract<SourceView, { state: 'OBSERVATION' }>).text }}</pre></details>
            <small>观察 {{ id }} · 版本 {{ view(id).version || '未提供' }} · 四项引用与已保存记录一致</small>
          </template>
          <p v-else-if="view(id).state === 'VERSION_MISMATCH'" class="finding-warning">
            该引用与当前材料或已保存记录的来源、版本或内容摘要不一致，不能据此认定本页内容就是当时依据。
          </p>
          <p v-else-if="view(id).state === 'UNCITED'" class="finding-warning">
            此历史方案未记录完整引用，无法与当前材料核对；不展示当前内容作为当时依据。
          </p>
          <p v-else class="finding-warning">此观察的原始正文尚未提供给审核页面，请勿仅凭摘要认定事实。</p>
          <small v-if="view(id).state !== 'MATERIAL' && view(id).state !== 'OBSERVATION'">观察 {{ id }} · 引用版本 {{ view(id).version || '未提供' }}</small>
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
.finding-facts { display: grid; grid-template-columns: 96px 1fr; gap: 4px 8px; margin: 6px 0; }
.finding-facts dt { color: #74829a; }
.finding-facts dd { margin: 0; color: #33445c; overflow-wrap: anywhere; white-space: pre-wrap; }
.finding-raw summary { color: #285ba6; }
.finding-raw pre { white-space: pre-wrap; overflow-wrap: anywhere; color: #33445c; }
</style>
