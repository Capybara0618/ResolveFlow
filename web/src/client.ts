/** Thin client for the existing core HTTP contract. Tokens only travel in headers. */

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

export interface LoginResponse {
  access_token: string
  role: 'CUSTOMER' | 'REVIEWER' | 'OPERATOR'
  merchant_id: string
  customer_id?: string
  expires_in: number
}

export interface OrderLine {
  order_id: string
  line_id: string
  sku: string
  category: string
  quantity: number
  line_paid_amount: number
  currency: string
  status: string
}

export interface Page<T> {
  items: T[]
  page: { next_cursor?: string; limit: number }
}

export interface TimelineEvent {
  event_id: string
  type: string
  occurred_at: string
  summary: string
  revision?: number
}

export interface CaseSnapshot {
  case: {
    case_id: string
    status: string
    input_revision: number
    version: number
    line_id: string
    order_id?: string
    description?: string
  }
  authorization?: {
    authorization_id: string
    authorization_version: number
    status: string
    input_revision: number
  }
  proposal?: Record<string, unknown>
  evidence: Array<{
    observation_id: string; content: string; evidence_kind: string; source_ref?: string
    source_version?: string; content_hash?: string; input_revision?: number; appended_by?: string
    observed_at?: string; reviewed_evidence_id?: string; verification_result?: string
  }>
  timeline: TimelineEvent[]
}

export interface PolicyText {
  bundle_id: string; version: string; rule_id: string; title: string; text: string
  chunk_id: string; content_hash: string
}
export interface ReviewContext {
  case_version: number; input_revision: number; allowed_actions: string[]; blocked_reason: string
  policy_rules: PolicyText[]; policy_status: 'PINNED' | 'UNAVAILABLE'
  review_history?: Array<{ type: string; occurred_at: string; revision: number; actor: string | null; reason: string | null; question_id: string | null }>
  execution?: { case_status: string; operation_id: string | null; outcome: string | null; amount_minor: number | null; reason_code: string | null }
}
export interface ReviewerAction {
  action: 'MANUAL_PROPOSAL' | 'REJECT' | 'REQUEST_INFO'; reason: string
  evidence_refs?: Array<{ observation_id: string; source_ref: string; source_version: string; content_hash: string }>
  policy_refs?: Array<{ bundle_id: string; version: string; rule_id: string; chunk_id: string; content_hash: string }>
}

export interface ReviewItem {
  case_id: string
  status: string
  version: number
  line_id: string
  description?: string
  updated_at: string
}

export async function apiRequest<T>(path: string, token: string | null, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(path, { ...init, headers })
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const error = body && typeof body === 'object' ? body as Record<string, unknown> : {}
    throw new ApiError(response.status, String(error.code ?? 'HTTP_ERROR'), String(error.message ?? response.statusText))
  }
  return body as T
}

function jsonPost<T>(path: string, token: string | null, body: unknown, headers: Record<string, string> = {}) {
  return apiRequest<T>(path, token, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
  })
}

export const coreApi = {
  reviewContext: (token: string, caseId: string) =>
    apiRequest<ReviewContext>(`/api/v1/cases/${encodeURIComponent(caseId)}/review-context`, token),
  reviewerAction: (token: string, snapshot: CaseSnapshot, action: ReviewerAction) =>
    jsonPost<CaseSnapshot>(`/api/v1/cases/${encodeURIComponent(snapshot.case.case_id)}/review-actions`, token,
      action, { 'If-Match': `"${snapshot.case.version}"` }),
  login: (username: string, password: string) =>
    jsonPost<LoginResponse>('/api/v1/auth/login', null, { username, password }),
  orders: (token: string, cursor?: string) =>
    apiRequest<Page<OrderLine>>(`/api/v1/orders?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`, token),
  order: (token: string, orderId: string) =>
    apiRequest<Page<OrderLine>>(`/api/v1/orders/${encodeURIComponent(orderId)}`, token),
  createCase: (token: string, lineId: string, description: string, key: string) =>
    jsonPost<{ case_id: string }>('/api/v1/cases', token, {
      line_id: lineId, description, requested_actions: ['REFUND'],
    }, { 'Idempotency-Key': key }),
  case: async (token: string, caseId: string): Promise<CaseSnapshot> => {
    const view = await apiRequest<CaseSnapshot>(`/api/v1/cases/${encodeURIComponent(caseId)}`, token)
    // The core response omits empty collections; the workbench renders them as empty sections.
    return { ...view, evidence: view.evidence ?? [], timeline: view.timeline ?? [] }
  },
  appendEvidence: (token: string, caseId: string, text: string, questionId?: string) =>
    jsonPost<{ input_revision: number }>(`/api/v1/cases/${encodeURIComponent(caseId)}/evidence`, token, {
      question_id: questionId || null, text, evidence_kind: 'CUSTOMER_STATEMENT',
    }),
  reviewEvidence: (token: string, caseId: string, evidenceId: string,
    verification: 'CONFIRMED' | 'REFUTED' | 'INCONCLUSIVE', reason: string) =>
    jsonPost(`/api/v1/cases/${encodeURIComponent(caseId)}/reviewed-evidence`, token, {
      source_evidence_id: evidenceId, verification_result: verification, reason,
    }),
  reviewQueue: (token: string, cursor?: string, view = 'REVIEW', query = '') =>
    apiRequest<Page<ReviewItem>>(`/api/v1/review/cases?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}${view !== 'REVIEW' || query ? `&view=${encodeURIComponent(view)}&query=${encodeURIComponent(query)}` : ''}`, token),
  review: (token: string, snapshot: CaseSnapshot, decision: 'APPROVE' | 'REJECT' | 'REQUEST_INFO', reason: string) => {
    if (!snapshot.authorization) throw new Error('No authorization to review')
    return jsonPost(`/api/v1/cases/${encodeURIComponent(snapshot.case.case_id)}/reviews`, token, {
      authorization_id: snapshot.authorization.authorization_id,
      authorization_version: snapshot.authorization.authorization_version,
      decision, reason,
    }, { 'If-Match': `"${snapshot.case.version}"` })
  },
}
