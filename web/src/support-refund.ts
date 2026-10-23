import { apiRequest, type CustomerCaseDetail } from './client'

export interface RefundDraft {
  draft_id: string; revision: number; expected_version: number
  status: 'DRAFT' | 'CANCELLED' | 'CONFIRMED' | 'EXPIRED' | 'STALE'
  reason: string; quantity: number; amount_minor: number; currency: string; expires_at: string; case_id: string | null
}
export interface RefundView { draft: RefundDraft | null; application: CustomerCaseDetail | null }
export interface RefundRequest {
  conversation: string; draft?: string; kind: 'prepare' | 'edit' | 'cancel' | 'confirm'; key: string
  body: { expected_version?: number; revision?: number; reason?: string }
}
const base = (id: string) => `/api/v1/support/conversations/${encodeURIComponent(id)}`
export const refundApi = {
  read: (token: string, id: string) => apiRequest<RefundView>(`${base(id)}/refund-application`, token),
  mutate: (token: string, request: RefundRequest) => apiRequest<RefundView>(`${base(request.conversation)}/refund-drafts${request.kind === 'prepare' ? '' : `/${encodeURIComponent(request.draft!)}/${request.kind}`}`, token, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': request.key }, body: JSON.stringify(request.body),
  }),
}
const storageKey = (owner: string, id: string) => `resolveflow-refund-v1:${owner}:${id}`
export function saveRefundRequest(owner: string, request: RefundRequest) { sessionStorage.setItem(storageKey(owner, request.conversation), JSON.stringify(request)) }
export function clearRefundRequest(owner: string, id: string) { sessionStorage.removeItem(storageKey(owner, id)) }
export function readRefundRequest(owner: string, id: string): RefundRequest | null {
  try {
    const raw = sessionStorage.getItem(storageKey(owner, id)); if (!raw) return null
    const value = JSON.parse(raw)
    if (value.conversation !== id || !['prepare', 'edit', 'cancel', 'confirm'].includes(value.kind) || !/^[A-Za-z0-9_-]{1,128}$/.test(value.key) || !value.body || (value.kind !== 'prepare' && typeof value.draft !== 'string')) throw Error('invalid')
    return value as RefundRequest
  } catch { clearRefundRequest(owner, id); return null }
}
export const refundStatus = (status: string) => ({ QUEUED: '申请已提交', ANALYZING: '正在核查', WAITING_CUSTOMER: '待你补充材料', PENDING_REVIEW: '等待商家审核', AUTHORIZED: '已审核，等待退款处理', EXECUTING: '退款处理中', RECONCILING: '退款结果待确认', CLOSED_SUCCESS: '退款完成', CLOSED_REJECTED: '申请未通过', CANCELLED: '申请已撤销' }[status] ?? '正在读取申请状态')
