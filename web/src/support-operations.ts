import { apiRequest } from './client'
export interface OperationsRun {
  run_id: string; merchant_id: string; status: string; mode: string | null; reason: string | null; created_at: string
  model_requests: number | null; tool_attempts: number | null; local_reads: number | null; source_counts: Record<string, number>
}
export interface OperationsEvent { kind: string; category: string | null; created_at: string }
export interface OperationsPage { items: OperationsRun[]; limit: number }
export interface OperationsDetail { run: OperationsRun; events: OperationsEvent[]; events_truncated: boolean }
const base = '/api/v1/platform/support-runs'
export const operationsApi = {
  list: (token: string) => apiRequest<OperationsPage>(base, token),
  read: (token: string, id: string) => apiRequest<OperationsDetail>(`${base}/${encodeURIComponent(id)}`, token),
}
