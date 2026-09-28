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
    observed_at?: string; reviewed_evidence_id?: string; verification_result?: string
  }>
  timeline: TimelineEvent[]
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
  reviewQueue: (token: string, cursor?: string) =>
    apiRequest<Page<ReviewItem>>(`/api/v1/review/cases?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`, token),
  review: (token: string, snapshot: CaseSnapshot, decision: 'APPROVE' | 'REJECT' | 'REQUEST_INFO', reason: string) => {
    if (!snapshot.authorization) throw new Error('No authorization to review')
    return jsonPost(`/api/v1/cases/${encodeURIComponent(snapshot.case.case_id)}/reviews`, token, {
      authorization_id: snapshot.authorization.authorization_id,
      authorization_version: snapshot.authorization.authorization_version,
      decision, reason,
    }, { 'If-Match': `"${snapshot.case.version}"` })
  },
}
