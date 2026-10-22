import { apiRequest } from './client'

export interface ProductReview { review_id: number; product_id: string; product_name: string; variant: string
  rating: number; body: string; reply: string | null; version: number; created_at: string; updated_at: string }
export interface ReviewSummary { count: number; average: number | null; stars: number[] }
export interface ReviewPage { items: ProductReview[]; summary: ReviewSummary | null; next_before: number | null }
export interface OwnReview { can_review: boolean; blocked_reason: string | null; review: ProductReview | null }
export interface ReviewWrite { rating: number; body: string; expected_version: number }
function post<T>(path: string, token: string, body: unknown) {
  return apiRequest<T>(path, token, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
}
function paging(before?: number, limit = 10) { return new URLSearchParams({ limit: String(limit), ...(before ? { before: String(before) } : {}) }) }
export const reviewApi = {
  public: (product: string, before?: number) => apiRequest<ReviewPage>(`/api/v1/shop/products/${encodeURIComponent(product)}/reviews?${paging(before)}`, null),
  own: (token: string, line: string) => apiRequest<OwnReview>(`/api/v1/shop/orders/lines/${encodeURIComponent(line)}/review`, token),
  save: (token: string, line: string, body: ReviewWrite) => post<ProductReview>(`/api/v1/shop/orders/lines/${encodeURIComponent(line)}/review`, token, body),
  merchant: (token: string, before?: number, limit = 10) => apiRequest<ReviewPage>(`/api/v1/merchant/reviews?${paging(before, limit)}`, token),
  reply: (token: string, id: number, body: string, version: number) => post<ProductReview>(`/api/v1/merchant/reviews/${id}/reply`, token, { body, expected_version: version }),
}
