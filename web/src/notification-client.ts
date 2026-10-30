import { apiRequest } from './client'
export interface Notification { notification_id: string; store_id?: string | null; sender_name?: string; sender_kind?: 'MERCHANT' | 'CUSTOMER' | 'ASSISTANT'; title: string; target: 'SUPPORT' | 'TICKET' | 'APPLICATION' | 'CASE'; target_id: string; conversation_id: string | null; created_at: string; read: boolean }
export interface NotificationPage { items: Notification[]; unread_count: number; next_cursor: string | null }
export const notificationApi = {
  list: (token: string, cursor?: string) => apiRequest<NotificationPage>(`/api/v1/account/notifications${cursor ? `?${new URLSearchParams({ cursor })}` : ''}`, token),
  read: (token: string, id: string) => apiRequest<void>(`/api/v1/account/notifications/${encodeURIComponent(id)}/read`, token, { method: 'POST' }),
}
