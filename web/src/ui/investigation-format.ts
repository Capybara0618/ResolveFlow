/**
 * Reading evidence and policy the way the server bound them.
 *
 * Two things live here, and they are both about not letting the page say more than the
 * record does:
 *
 * 1. **Citation identity.** A policy citation is the five members
 *    `bundle_id`/`version`/`rule_id`/`chunk_id`/`content_hash`, and an evidence citation is
 *    `observation_id`/`source_ref`/`source_version`/`content_hash` (docs/core-contracts.md:56,
 *    :101). Comparing fewer members is how a stale proposal comes to look like it cites the
 *    current revision: the same `rule_id` exists in two bundle versions and the same
 *    `observation_id` can be seen at two versions, so a match on one member proves nothing.
 *    Every helper below requires all of them, and reports the ones that are missing instead of
 *    quietly degrading to a weaker comparison.
 *
 * 2. **Business summaries.** The reviewer should not have to read raw JSON to learn what an
 *    order line cost or what the carrier concluded, so each tool's *saved* result is reduced to
 *    a few labelled facts. The shapes are read from what the tools actually returned (and from
 *    the core schemas they are built on), never guessed, and nothing here changes the payload:
 *    the full result stays available underneath. `0` is a value, `null` is not `0`, and an
 *    absent member is left out rather than rendered as `0` or `—`.
 */

import { formatMinorUnits } from '../money'

// --------------------------------------------------------------------------- identity

export type Json = Record<string, unknown>

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value : null
}

export const POLICY_MEMBERS = ['bundle_id', 'version', 'rule_id', 'chunk_id', 'content_hash'] as const
export const EVIDENCE_MEMBERS = ['observation_id', 'source_ref', 'source_version', 'content_hash'] as const

/** The five members a policy citation must carry, or `null` when any is missing. */
export function policyKey(reference: unknown): string | null {
  if (!reference || typeof reference !== 'object') return null
  const source = reference as Json
  const parts = POLICY_MEMBERS.map(member => text(source[member]))
  return parts.every(part => part !== null) ? parts.join('\u0000') : null
}

/** The four members an evidence citation must carry, or `null` when any is missing. */
export function evidenceKey(reference: unknown): string | null {
  if (!reference || typeof reference !== 'object') return null
  const source = reference as Json
  const parts = EVIDENCE_MEMBERS.map(member => text(source[member]))
  return parts.every(part => part !== null) ? parts.join('\u0000') : null
}

export function missingPolicyMembers(reference: unknown): string[] {
  if (!reference || typeof reference !== 'object') return [...POLICY_MEMBERS]
  const source = reference as Json
  return POLICY_MEMBERS.filter(member => text(source[member]) === null)
}

export function missingEvidenceMembers(reference: unknown): string[] {
  if (!reference || typeof reference !== 'object') return [...EVIDENCE_MEMBERS]
  const source = reference as Json
  return EVIDENCE_MEMBERS.filter(member => text(source[member]) === null)
}

export type PolicyMatch =
  | { state: 'MATCHED'; rule: Json }
  | { state: 'INCOMPLETE'; missing: string[] }
  | { state: 'MISMATCH' }

/**
 * Find the bound clause a citation names, on all five members.
 *
 * `INCOMPLETE` and `MISMATCH` are different answers on purpose: the first says the citation
 * cannot be checked at all (a historical proposal that recorded fewer members), the second says
 * it was checked and does not name a clause this case is bound to. Neither may fall back to the
 * newest policy or to a same-named rule, and neither may show another clause's text.
 */
export function matchPolicyReference(reference: unknown, rules: readonly unknown[]): PolicyMatch {
  const missing = missingPolicyMembers(reference)
  if (missing.length) return { state: 'INCOMPLETE', missing }
  const wanted = policyKey(reference)
  const rule = rules.find(candidate => policyKey(candidate) === wanted)
  return rule ? { state: 'MATCHED', rule: rule as Json } : { state: 'MISMATCH' }
}

export type EvidenceMatch =
  | { state: 'MATCHED'; observation: Json }
  | { state: 'INCOMPLETE'; missing: string[] }
  | { state: 'MISMATCH' }

/** The same three answers for an evidence citation against the observations a run saved. */
export function matchEvidenceReference(reference: unknown, observations: readonly unknown[]): EvidenceMatch {
  const missing = missingEvidenceMembers(reference)
  if (missing.length) return { state: 'INCOMPLETE', missing }
  const wanted = evidenceKey(reference)
  const observation = observations.find(candidate => evidenceKey(candidate) === wanted)
  return observation ? { state: 'MATCHED', observation: observation as Json } : { state: 'MISMATCH' }
}

/** The citation in a proposal's `evidence_refs` that names this observation id, if any. */
export function citationFor(referenceList: unknown, observationId: unknown): Json | null {
  if (!Array.isArray(referenceList) || text(observationId) === null) return null
  return (
    (referenceList.find(
      candidate => candidate && typeof candidate === 'object' && (candidate as Json).observation_id === observationId,
    ) as Json | undefined) ?? null
  )
}

// --------------------------------------------------------------------------- tool summaries

export interface ObservationFact {
  label: string
  value: string
}

const TOOL_LABELS: Record<string, string> = {
  get_order_context: '读取订单与支付事实',
  get_order_line: '读取订单行',
  get_shipment_trace: '核对合成物流记录',
  get_refund_status: '读取退款状态',
  get_case_evidence: '读取工单材料引用',
  get_policy_manifest: '读取绑定政策版本',
  search_policy: '检索政策片段',
  read_policy: '读取政策原文',
  read_observation: '回读已保存观察',
}

export function toolLabel(toolName: unknown): string {
  const name = text(toolName)
  if (name === null) return '未知工具'
  return TOOL_LABELS[name] ?? name
}

function amount(value: unknown, currency: unknown): string | null {
  // `0` is a real amount and `null` is an absent one: only integers are formatted, and only
  // when the member was actually present.
  if (typeof value !== 'number' || !Number.isInteger(value)) return null
  return formatMinorUnits(value, typeof currency === 'string' && currency ? currency : 'CNY')
}

function scalar(value: unknown): string | null {
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  if (typeof value === 'boolean') return value ? '是' : '否'
  return text(value)
}

const CONCLUSION_LABELS: Record<string, string> = {
  LOST: '承运商确认丢失',
  DELIVERED: '已送达',
  IN_TRANSIT: '运输中',
  UNKNOWN: '承运商未给出结论',
  SIGNED: '已签收',
}

const REFUND_STATE_LABELS: Record<string, string> = {
  FREE: '未发生退款',
  RESERVED: '已预留（尚未确认结果）',
  CONSUMED: '已退款',
  RELEASED: '预留已释放',
}

const EVIDENCE_KIND_LABELS: Record<string, string> = {
  ORDER_LINE: '订单行记录',
  PAYMENT_LEDGER: '支付记录',
  SHIPMENT: '物流记录',
  SHIPMENT_TRACK: '物流轨迹',
  CUSTOMER_STATEMENT: '客户陈述',
  REVIEWER_VERIFICATION: '人工核验',
  POLICY_RULE: '政策条款',
}

function eventLine(event: unknown): string | null {
  if (!event || typeof event !== 'object') return null
  const row = event as Json
  const code = scalar(row.code) ?? scalar(row.status)
  if (code === null) return null
  const at = scalar(row.occurred_at) ?? scalar(row.observed_at)
  const version = scalar(row.source_version)
  return [CONCLUSION_LABELS[code] ?? code, at, version === null ? null : `版本 ${version}`]
    .filter((part): part is string => part !== null)
    .join(' · ')
}

/**
 * A few labelled business facts from one saved tool result.
 *
 * Unknown tools and unknown shapes fall through to `[]` — the caller keeps the raw result and
 * the source information, so nothing is lost and nothing is invented. A summary never turns a
 * customer's claim into a verified fact, and a retrieval `score` is reported as relevance
 * rather than as confidence or entitlement.
 */
export function summarizeObservation(toolName: unknown, result: unknown): ObservationFact[] {
  if (!result || typeof result !== 'object' || Array.isArray(result)) return []
  const body = result as Json
  const facts: ObservationFact[] = []
  const push = (label: string, value: string | null) => {
    if (value !== null) facts.push({ label, value })
  }

  switch (text(toolName)) {
    case 'get_order_context':
    case 'get_order_line': {
      const paid = amount(body.line_paid_amount, body.currency)
      push('订单行', scalar(body.line_id))
      push('商品编号', scalar(body.sku))
      push('商品类别', scalar(body.category))
      push('数量', scalar(body.quantity))
      push('实付金额', paid)
      push('已退金额', amount(body.refunded_amount, body.currency))
      push('预留金额', amount(body.reserved_refund_amount, body.currency))
      push('支付时间', scalar(body.paid_at))
      push('订单状态', scalar(body.order_status))
      break
    }
    case 'get_shipment_trace': {
      const conclusion = scalar(body.carrier_conclusion)
      push('记录状态', scalar(body.status))
      push('承运商结论', conclusion === null ? null : CONCLUSION_LABELS[conclusion] ?? conclusion)
      push('合成数据', body.synthetic === true ? '是（本地合成物流）' : null)
      const events = Array.isArray(body.events) ? body.events : []
      const lines = events.map(eventLine).filter((line): line is string => line !== null)
      if (lines.length) facts.push({ label: '关键事件', value: lines.join('\n') })
      push('记录更新时间', scalar(body.updated_at))
      if (body.next_cursor) facts.push({ label: '事件分页', value: `还有后续事件（游标 ${String(body.next_cursor)}）` })
      else if (events.length) facts.push({ label: '事件分页', value: '本页为最后一页；更早的事件未包含在此记录中' })
      break
    }
    case 'get_refund_status': {
      const state = scalar(body.state)
      push('退款状态', state === null ? null : REFUND_STATE_LABELS[state] ?? state)
      push('订单行', scalar(body.line_id))
      push('实付金额', amount(body.line_paid_amount, body.currency))
      push('已退金额', amount(body.refunded_amount, body.currency))
      push('预留金额', amount(body.reserved_refund_amount, body.currency))
      push('退款执行编号', scalar(body.operation_id))
      break
    }
    case 'get_case_evidence': {
      // This tool returns citations, not material text (docs/core-contracts.md:66: an
      // EvidenceRef carries no body), so the summary must not imply it read the content.
      const evidence = Array.isArray(body.evidence) ? body.evidence : []
      const kinds = evidence
        .map(item => {
          if (!item || typeof item !== 'object') return null
          const kind = scalar((item as Json).evidence_kind) ?? scalar((item as Json).source_type)
          return kind === null ? null : EVIDENCE_KIND_LABELS[kind] ?? kind
        })
        .filter((kind): kind is string => kind !== null)
      push('材料条数', String(evidence.length))
      if (kinds.length) facts.push({ label: '材料类型', value: kinds.join('、') })
      push('材料版本', scalar(body.input_revision))
      facts.push({ label: '说明', value: '工具只返回材料引用，正文见工单材料区；引用不等于已核验' })
      break
    }
    case 'get_policy_manifest': {
      push('政策归属商家', scalar(body.merchant_id))
      push('生效起点', scalar(body.effective_from))
      const bundles = Array.isArray(body.bundles) ? body.bundles : []
      const described = bundles
        .map(item => {
          if (!item || typeof item !== 'object') return null
          const row = item as Json
          const ids = Array.isArray(row.bundle_ids) ? row.bundle_ids.map(id => String(id)).join('、') : null
          const hash = scalar(row.manifest_hash)
          const epoch = scalar(row.safety_epoch)
          return [ids, hash === null ? null : `摘要 ${hash.slice(0, 12)}…`, epoch === null ? null : `epoch ${epoch}`]
            .filter((part): part is string => part !== null)
            .join(' · ')
        })
        .filter((line): line is string => line !== null && line !== '')
      if (described.length) facts.push({ label: '绑定政策版本', value: described.join('\n') })
      break
    }
    case 'search_policy':
    case 'read_policy': {
      const hits = Array.isArray(body.hits) ? body.hits : []
      push('检索词', scalar(body.query))
      push('命中条数', scalar(body.hit_count) ?? String(hits.length))
      const lines = hits.slice(0, 5).map(hit => {
        if (!hit || typeof hit !== 'object') return null
        const row = hit as Json
        const title = scalar(row.title) ?? scalar(row.rule_id)
        const where = [scalar(row.bundle_id), scalar(row.version)].filter((part): part is string => part !== null)
        const score = typeof row.score === 'number' && Number.isFinite(row.score) ? `相关度 ${row.score.toFixed(3)}` : null
        return [title, where.join(' · '), score].filter((part): part is string => part !== null && part !== '').join(' · ')
      })
      const kept = lines.filter((line): line is string => line !== null && line !== '')
      if (kept.length) facts.push({ label: '命中片段', value: kept.join('\n') })
      if (typeof body.score === 'number') push('相关度', body.score.toFixed(3))
      if (hits.length) {
        facts.push({ label: '说明', value: '相关度是检索排序，不代表退款资格或模型置信度；正文请展开原始结果核对' })
      }
      break
    }
    default:
      return []
  }
  return facts
}


// --------------------------------------------------------------------------- source projection

export interface CaseEvidenceLike {
  observation_id: string
  content: string
  source_ref?: string
  source_version?: string
  content_hash?: string
  verification_result?: string
}

export interface ObservationLike {
  tool_name: string
  source_ref: string
  source_version: string | null
  content_hash: string | null
  result: Record<string, unknown> | null
  body_omitted: boolean
  error_code: string | null
}

export interface SnapshotLike {
  evidence: CaseEvidenceLike[]
  proposal?: Record<string, unknown>
}

export type SourceView =
  | { state: 'MATERIAL'; text: string; ref: string | null; version: string | null; verification?: string }
  | { state: 'OBSERVATION'; text: string; ref: string | null; version: string | null; facts: ObservationFact[] }
  | { state: 'UNCITED'; ref: string | null; version: string | null }
  | { state: 'VERSION_MISMATCH'; ref: string | null; version: string | null; citationVersion: string | null }
  | { state: 'UNAVAILABLE'; ref: string | null; version: string | null }

function observationView(observation: ObservationLike): SourceView {
  if (observation.error_code) {
    return { state: 'UNAVAILABLE', ref: observation.source_ref, version: observation.source_version }
  }
  if (observation.body_omitted || observation.result === null) {
    return { state: 'UNAVAILABLE', ref: observation.source_ref, version: observation.source_version }
  }
  return {
    state: 'OBSERVATION',
    text: JSON.stringify(observation.result, null, 2),
    ref: observation.source_ref,
    version: observation.source_version,
    facts: summarizeObservation(observation.tool_name, observation.result),
  }
}

/**
 * What can honestly be shown beside one cited observation id.
 *
 * `UNCITED` covers the historical proposal that recorded no full evidence reference at all;
 * `VERSION_MISMATCH` covers the citation that exists but names different content. Neither is
 * allowed to borrow today's material, which is what an id-only lookup did: the same
 * `observation_id` can be re-read at a new version, so an id match alone is not a citation match.
 */
export function sourceOf(
  id: string,
  snapshot: SnapshotLike,
  observations: readonly ObservationLike[] = [],
): SourceView {
  const citation = citationFor(snapshot.proposal?.evidence_refs, id)
  const ref = typeof citation?.source_ref === 'string' ? citation.source_ref : null
  const citationVersion =
    citation?.source_version === undefined || citation?.source_version === null
      ? null
      : String(citation.source_version)

  if (!citation) return { state: 'UNCITED', ref: null, version: null }
  if (evidenceKey(citation) === null) return { state: 'UNCITED', ref, version: citationVersion }

  const material = snapshot.evidence.find(item => item.observation_id === id)
  if (material) {
    const matches = evidenceKey({
      observation_id: material.observation_id,
      source_ref: material.source_ref,
      source_version: material.source_version,
      content_hash: material.content_hash,
    }) === evidenceKey(citation)
    if (matches) {
      return {
        state: 'MATERIAL', text: material.content, ref: material.source_ref ?? ref,
        version: material.source_version ?? citationVersion, verification: material.verification_result,
      }
    }
    const recorded = observations.find(item => evidenceKey(item) === evidenceKey(citation))
    if (recorded) return observationView(recorded)
    return { state: 'VERSION_MISMATCH', ref, version: citationVersion, citationVersion }
  }

  const recorded = observations.find(item => evidenceKey(item) === evidenceKey(citation))
  if (recorded) return observationView(recorded)
  return { state: 'UNAVAILABLE', ref, version: citationVersion }
}


// --------------------------------------------------------------------------- clause text

/** Phrases that limit or qualify a rule, as they appear *in the stored text*. */
const LIMITING_PHRASES = ['例外', '除外', '但', '不得', '必须', '须', '仅在', '方可']

export interface PolicySpan {
  text: string
  /** The stored sentence contains one of the phrases above. Marked, not interpreted. */
  limiting: boolean
}

/**
 * The stored clause as paragraphs of original sentences, with limiting phrasing marked.
 *
 * This is deliberately **not** an interpretation: it splits on sentence boundaries and line
 * breaks and reports which sentences contain a limiting phrase, so a reviewer's eye lands on the
 * part of the authoritative text that changes the rule's scope. It never decides that an
 * exception applies, never rewords the clause, and never turns "且/除外/但" into a conclusion the
 * policy does not state — the marked sentence is shown exactly as stored.
 */
export function splitPolicySpans(raw: unknown): PolicySpan[] {
  const value = text(raw)
  if (value === null) return []
  const spans: PolicySpan[] = []
  for (const paragraph of value.split(/\n+/)) {
    if (paragraph.trim() === '') continue
    for (const sentence of paragraph.split(/(?<=[。；！？])/)) {
      if (sentence === '') continue
      spans.push({ text: sentence, limiting: LIMITING_PHRASES.some(phrase => sentence.includes(phrase)) })
    }
  }
  return spans
}
