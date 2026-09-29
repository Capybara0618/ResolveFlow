<script setup lang="ts">
/**
 * The citations a proposal carries, matched against what the case is actually bound to.
 *
 * This is the reviewer's entry point into the evidence: a citation that matches on every member
 * is a button that opens the clause it names; one that does not is *stated* to be unverifiable
 * rather than rendered as if it were a link. `docs/core-contracts.md:56` makes a policy citation
 * five members and `:101` makes an evidence citation four, so a same-named rule from another
 * bundle version or a same-id observation from another version can never be shown here as the
 * cited one.
 */
import { computed } from 'vue'
import {
  POLICY_MEMBERS,
  matchPolicyReference,
  missingEvidenceMembers,
  policyKey,
  type Json,
} from './investigation-format'
import Icon from './ReviewIcon.vue'

const props = defineProps<{
  evidenceRefs?: unknown
  policyRefs?: unknown
  policyRules?: readonly unknown[]
  policyStatus?: string | null
}>()
const emit = defineEmits<{ focus: [key: string] }>()

const evidence = computed<Json[]>(() =>
  Array.isArray(props.evidenceRefs) ? (props.evidenceRefs.filter(item => !!item && typeof item === 'object') as Json[]) : [])
const policies = computed<Json[]>(() =>
  Array.isArray(props.policyRefs) ? (props.policyRefs.filter(item => !!item && typeof item === 'object') as Json[]) : [])
const rules = computed(() => props.policyRules ?? [])
/** No bound policy is available to *this view* — a customer never loads it. That is not the
 * same fact as a citation that was checked and did not match, and the two must read
 * differently: only the second one is a statement about the citation. */
const rulesAvailable = computed(() => rules.value.length > 0)

const policyRows = computed(() =>
  policies.value.map(reference => ({
    reference,
    key: policyKey(reference),
    match: matchPolicyReference(reference, rules.value),
  })))

const evidenceRows = computed(() =>
  evidence.value.map(reference => ({
    reference,
    missing: missingEvidenceMembers(reference),
    ref: typeof reference.source_ref === 'string' ? reference.source_ref : null,
    version: reference.source_version === undefined || reference.source_version === null
      ? null : String(reference.source_version),
  })))

function describeRule(rule: Json): string {
  return [rule.bundle_id, rule.version === undefined ? null : `v${String(rule.version)}`, rule.rule_id, rule.chunk_id]
    .filter((part): part is string => typeof part === 'string' && part !== '')
    .join(' · ')
}
function describeReference(reference: Json): string {
  return POLICY_MEMBERS
    .map(member => (reference[member] === undefined || reference[member] === null
      ? `${member}=未记录` : `${member}=${String(reference[member])}`))
    .join(' · ')
}
function focus(key: string | null) {
  if (key) emit('focus', key)
}
</script>

<template>
  <div class="citation-block">
    <div v-if="policies.length" class="citation-group">
      <strong>引用的政策条款</strong>
      <p class="citation-hint">点击条款名可展开下方绑定政策原文，并按五项身份定位到同一版本。</p>
      <ul class="citation-rows">
        <li v-for="row in policyRows" :key="row.key ?? describeReference(row.reference)">
          <template v-if="row.match.state === 'MATCHED'">
            <button type="button" class="citation-button" data-test="policy-citation" @click="focus(row.key)">
              <Icon name="file" :size="15" />
              <span class="citation-name">{{ String(row.match.rule.title ?? row.match.rule.rule_id ?? '未命名条款') }}</span>
              <span class="citation-meta">{{ describeRule(row.match.rule) }}</span>
            </button>
          </template>
          <template v-else-if="row.match.state === 'INCOMPLETE'">
            <p class="citation-warning" data-test="policy-citation-incomplete">
              该引用未记录完整政策身份（缺少 {{ row.match.missing.join('、') }}），无法与当前绑定政策核对；不展示任何条款正文。
            </p>
            <span class="citation-meta">{{ describeReference(row.reference) }}</span>
          </template>
          <template v-else-if="rulesAvailable">
            <p class="citation-warning" data-test="policy-citation-mismatch">
              该引用未能匹配当前绑定政策；不展示最新政策或同名条款来代替。
            </p>
            <span class="citation-meta">{{ describeReference(row.reference) }}</span>
          </template>
          <template v-else>
            <span class="citation-meta">{{ describeReference(row.reference) }}</span>
          </template>
        </li>
      </ul>
      <p v-if="!rulesAvailable || policyStatus === 'UNAVAILABLE'" class="citation-warning" data-test="policy-unavailable">
        暂无可读取的绑定政策，无法核对上述引用。
      </p>
    </div>

    <div v-if="evidence.length" class="citation-group">
      <strong>引用的证据与材料</strong>
      <p class="citation-hint">证据引用需 observation_id、来源、版本与内容摘要四项齐全才算完整引用。</p>
      <ul class="citation-rows">
        <li v-for="(row, index) in evidenceRows" :key="index">
          <template v-if="row.missing.length">
            <p class="citation-warning" data-test="evidence-citation-incomplete">
              该引用缺少 {{ row.missing.join('、') }}，不能视为已核对的依据。
            </p>
          </template>
          <span class="citation-meta">{{ row.ref ?? '来源未提供' }} · 版本 {{ row.version ?? '未提供' }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.citation-block { display: grid; gap: 14px; margin: 12px 0; }
.citation-group { display: grid; gap: 6px; }
.citation-group > strong { font-size: 13px; color: #24456f; }
.citation-hint { margin: 0; font-size: 12px; color: #65758e; line-height: 1.6; }
.citation-rows { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.citation-button { display: grid; grid-template-columns: 18px 1fr; gap: 2px 8px; width: 100%; text-align: left;
  background: #f3f7ff; border: 1px solid #dbe7fc; border-radius: 8px; padding: 8px 10px; cursor: pointer; }
.citation-button:hover { border-color: #a9c8f7; }
.citation-button:focus-visible { outline: 2px solid #165dff; outline-offset: 2px; }
.citation-name { font-size: 13px; color: #165dff; font-weight: 600; }
.citation-meta { grid-column: 2; font-size: 12px; color: #65758e; overflow-wrap: anywhere; }
.citation-warning { margin: 0; padding: 8px 10px; background: #fff6e9; border: 1px solid #f1dfb9; border-radius: 6px;
  font-size: 12px; color: #8a4b12; line-height: 1.6; }
</style>
