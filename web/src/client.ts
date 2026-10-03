/** Thin client for the existing core HTTP contract. Tokens only travel in headers. */

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

export interface LoginResponse {
  access_token: string
  role: 'CUSTOMER' | 'REVIEWER' | 'MERCHANT_ADMIN' | 'OPERATOR' | 'PLATFORM_ADMIN'
  merchant_id?: string
  buyer_id?: string
  customer_id?: string
  expires_in: number
  display_name?: string
  merchant_name?: string
  single_operator?: boolean
}

export interface MerchantCoordinationItem {
  case_id: string; status: string; description: string | null; owner_name: string | null
  owner_username: string | null; updated_at: string
  reasons: Array<'UNCLAIMED' | 'RESULT_UNKNOWN' | 'OWNER_UNAVAILABLE' | 'INVESTIGATION_FAILED'>
}
export interface MerchantOverview {
  unclaimed: number; mine: number; attention: number; enabled_staff: number
  coordination_total: number; items: MerchantCoordinationItem[]; observed_at: string
}
export interface AdminPolicy {
  bundle_id: string; version: string; manifest_hash: string; safety_epoch: number
  effective_from: string; effective_to: string | null; imported_at: string; rule_count: number
}
export interface PolicyIndexStatus {
  status: 'READY' | 'BUILDING' | 'FAILED' | 'MISSING' | 'UNAVAILABLE'; generation_id?: string | null
  bundle_id?: string; manifest_hash?: string; chunk_count?: number | null; built_at?: string | null
}
export interface AdminPolicyDetail {
  policy: AdminPolicy; rules: Array<{ rule_id: string; title: string; text: string; chunk_id: string; content_hash: string }>
  index: PolicyIndexStatus
}

export interface AdminAccount {
  username: string; display_name: string; role: LoginResponse['role']; enabled: boolean
  version: number; created_at: string; updated_at: string
}
export interface AccountFilter { query: string; role: string; status: string }
export interface AdminAccountPage extends Page<AdminAccount> {
  total: number; enabled_admins: number; current_username: string
}
export interface AccountMutation { account: AdminAccount; session_invalidated: boolean }
export interface AccountUpdate { display_name: string; role: LoginResponse['role']; enabled: boolean; reason: string }
export interface AccountCreate { username: string; display_name: string; role: 'REVIEWER' | 'MERCHANT_ADMIN'; password: string; reason: string }
export interface AccountAudit {
  id: string; action: 'CREATED' | 'UPDATED' | 'PASSWORD_RESET'; actor_username: string
  account_version: number; reason: string; occurred_at: string
  before: Omit<AccountUpdate, 'reason'> | null; after: Omit<AccountUpdate, 'reason'>
}
export interface AccountAuditPage extends Page<AccountAudit> { total: number }

export interface OrderLine {
  merchant_id?: string
  merchant_name?: string
  order_id: string
  line_id: string
  sku: string
  /**
   * Optional presentation members (core OpenAPI `OrderLineSummary`).
   *
   * Both are absent for lines that predate them, and `null` when the merchant recorded nothing —
   * a page must render the SKU rather than fill either in. They are display data: the review
   * re-check recomputes amounts from the server's line context, which does not carry them.
   */
  product_name?: string | null
  variant_text?: string | null
  category: string
  quantity: number
  line_paid_amount: number
  currency: string
  /** Already on the wire; declared so the page can show the payment time without a second read. */
  paid_at?: string
  status: string
}

export interface Page<T> {
  items: T[]
  page: { next_cursor?: string | null; limit: number }
}

export type CollaborationAction = 'CLAIM' | 'RELEASE' | 'TRANSFER' | 'TAKEOVER'
export interface CaseCollaboration {
  case_id: string; version: number; is_owner: boolean
  owner: { username: string; display_name: string; role: LoginResponse['role']; enabled: boolean } | null
  allowed_actions: CollaborationAction[]
  history: Array<{ version: number; action: CollaborationAction | 'AUTO_ASSIGN'; actor_username: string
    from_username: string | null; to_username: string | null; reason: string; occurred_at: string }>
}

export type CustomerView = 'ALL' | 'WAITING' | 'PROCESSING' | 'REVIEW' | 'CLOSED'
export interface CustomerCaseSummary {
  merchant_id?: string
  case_id: string; status: string; line_id: string; order_id: string | null; description: string | null
  version: number; created_at: string; updated_at: string
}
export interface CustomerMaterial {
  id: string; text: string | null; submitted_at: string; question_id: string | null
  verification_result: 'CONFIRMED' | 'REFUTED' | 'INCONCLUSIVE' | null
}
export interface CustomerQuestion {
  question_id: string | null; prompts: string[]; status: 'PENDING' | 'ANSWERED' | 'CLOSED' | 'EXPIRED' | 'UNAVAILABLE'
  asked_at: string; expires_at: string; answers: CustomerMaterial[]
}
export interface CustomerCaseDetail {
  case: CustomerCaseSummary; input_revision: number; allowed_actions: string[]; blocked_reason: string
  materials: CustomerMaterial[]; questions: CustomerQuestion[]
  result: { status: string; message: string; amount_minor: number | null; currency: string; public_reason: string | null }
  timeline: Array<{ type: string; occurred_at: string; summary: string }>
}
export interface CustomerOrderLine {
  order_line: OrderLine; application: CustomerCaseSummary | null; can_apply: boolean; blocked_reason: string
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

export interface InvestigationObservation {
  call_id: string; observation_id: string; tool_name: string; source_type: string; source_ref: string
  source_version: string | null; content_hash: string | null; observed_at: string
  result: Record<string, unknown> | null; body_omitted: boolean; error_code: string | null
}
export interface InvestigationView {
  case_version: number; input_revision: number; availability: 'AVAILABLE' | 'NOT_SCHEDULED' | 'UNAVAILABLE'
  investigation: { run_id: string; case_id: string; input_revision: number; status: string
    model_provider: string | null; model_id: string | null; observations: InvestigationObservation[]; truncated: boolean } | null
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
  owner?: CaseCollaboration['owner']
  collaboration_version?: number | null
}

export type ReviewScope = 'PUBLIC' | 'MINE' | 'UNCLAIMED'
export interface ReviewQueueCounts {
  total: number; public: number; mine: number; unclaimed: number
  stages: Record<string, number>
}
export interface ReviewQueuePage extends Page<ReviewItem> { counts?: ReviewQueueCounts }

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
  merchantOverview: (token: string) => apiRequest<MerchantOverview>('/api/v1/admin/overview', token),
  adminPolicies: (token: string) => apiRequest<{ items: AdminPolicy[]; truncated: boolean }>('/api/v1/admin/policies', token),
  adminPolicy: (token: string, bundle: string) => apiRequest<AdminPolicyDetail>(`/api/v1/admin/policies/${encodeURIComponent(bundle)}`, token),
  adminAccounts: (token: string, filter: AccountFilter, cursor?: string) => {
    const params = new URLSearchParams({ ...filter, limit: '20', ...(cursor ? { cursor } : {}) })
    return apiRequest<AdminAccountPage>(`/api/v1/admin/accounts?${params}`, token)
  },
  createStaff: (token: string, body: AccountCreate) => jsonPost<AccountMutation>('/api/v1/admin/accounts', token, body),
  updateAccount: (token: string, original: AdminAccount, body: AccountUpdate) =>
    jsonPost<AccountMutation>(`/api/v1/admin/accounts/${encodeURIComponent(original.username)}`, token, body, { 'If-Match': `"${original.version}"` }),
  resetAccountPassword: (token: string, original: AdminAccount, password: string, reason: string) =>
    jsonPost<AccountMutation>(`/api/v1/admin/accounts/${encodeURIComponent(original.username)}/password`, token, { password, reason }, { 'If-Match': `"${original.version}"` }),
  accountHistory: (token: string, username: string, cursor?: string) =>
    apiRequest<AccountAuditPage>(`/api/v1/admin/accounts/${encodeURIComponent(username)}/history?limit=10${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`, token),
  reviewStaff: (token: string) => apiRequest<NonNullable<CaseCollaboration['owner']>[]>('/api/v1/review/staff', token),
  collaboration: (token: string, caseId: string) =>
    apiRequest<CaseCollaboration>(`/api/v1/cases/${encodeURIComponent(caseId)}/collaboration`, token),
  changeCollaboration: (token: string, current: CaseCollaboration, action: CollaborationAction,
    reason: string, targetUsername?: string) =>
    jsonPost<CaseCollaboration>(`/api/v1/cases/${encodeURIComponent(current.case_id)}/collaboration`, token,
      { action, reason, ...(targetUsername !== undefined ? { target_username: targetUsername } : {}) },
      { 'If-Collaboration-Match': `"${current.version}"` }),
  customerCases: (token: string, view: CustomerView = 'ALL', cursor?: string) =>
    apiRequest<Page<CustomerCaseSummary>>(`/api/v1/customer/cases?view=${view}&limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`, token),
  customerCase: (token: string, caseId: string) =>
    apiRequest<CustomerCaseDetail>(`/api/v1/customer/cases/${encodeURIComponent(caseId)}`, token),
  customerOrderLine: (token: string, lineId: string) =>
    apiRequest<CustomerOrderLine>(`/api/v1/customer/order-lines/${encodeURIComponent(lineId)}`, token),
  answerQuestion: (token: string, detail: CustomerCaseDetail, questionId: string, text: string) =>
    jsonPost<CustomerCaseDetail>(`/api/v1/customer/cases/${encodeURIComponent(detail.case.case_id)}/answers`, token,
      { question_id: questionId, text }, { 'If-Match': `"${detail.case.version}"` }),
  cancelCase: (token: string, caseId: string, reason: string) =>
    jsonPost(`/api/v1/cases/${encodeURIComponent(caseId)}/cancel`, token, { reason }),
  investigation: (token: string, caseId: string) =>
    apiRequest<InvestigationView>(`/api/v1/cases/${encodeURIComponent(caseId)}/investigation`, token),
  reviewContext: (token: string, caseId: string) =>
    apiRequest<ReviewContext>(`/api/v1/cases/${encodeURIComponent(caseId)}/review-context`, token),
  reviewerAction: (token: string, snapshot: CaseSnapshot, action: ReviewerAction, collaboration?: CaseCollaboration | null) =>
    jsonPost<CaseSnapshot>(`/api/v1/cases/${encodeURIComponent(snapshot.case.case_id)}/review-actions`, token,
      action, { 'If-Match': `"${snapshot.case.version}"`, ...(collaboration ? { 'If-Collaboration-Match': `"${collaboration.version}"` } : {}) }),
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
    verification: 'CONFIRMED' | 'REFUTED' | 'INCONCLUSIVE', reason: string,
    snapshot?: CaseSnapshot | null, collaboration?: CaseCollaboration | null) =>
    jsonPost(`/api/v1/cases/${encodeURIComponent(caseId)}/reviewed-evidence`, token, {
      source_evidence_id: evidenceId, verification_result: verification, reason,
    }, { ...(snapshot ? { 'If-Match': `"${snapshot.case.version}"` } : {}),
      ...(collaboration ? { 'If-Collaboration-Match': `"${collaboration.version}"` } : {}) }),
  reviewQueue: (token: string, cursor?: string, view = 'REVIEW', query = '', scope: ReviewScope = 'PUBLIC') =>
    apiRequest<ReviewQueuePage>(`/api/v1/review/cases?limit=20&scope=${scope}&view=${encodeURIComponent(view)}&query=${encodeURIComponent(query)}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`, token),
  review: (token: string, snapshot: CaseSnapshot, decision: 'APPROVE' | 'REJECT' | 'REQUEST_INFO', reason: string,
    collaboration?: CaseCollaboration | null) => {
    if (!snapshot.authorization) throw new Error('No authorization to review')
    return jsonPost(`/api/v1/cases/${encodeURIComponent(snapshot.case.case_id)}/reviews`, token, {
      authorization_id: snapshot.authorization.authorization_id,
      authorization_version: snapshot.authorization.authorization_version,
      decision, reason,
    }, { 'If-Match': `"${snapshot.case.version}"`, ...(collaboration ? { 'If-Collaboration-Match': `"${collaboration.version}"` } : {}) })
  },
}
