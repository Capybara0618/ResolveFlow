import { apiRequest } from './client'
export interface RecoveryReceipt { username: string; recovery_key: string }
const post = <T>(path: string, body: unknown, token: string | null = null) => apiRequest<T>(path, token, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
export const enrollmentApi = {
  register: (username: string, display_name: string, password: string) => post<RecoveryReceipt>('/api/v1/auth/register', { username, display_name, password }),
  recover: (username: string, recovery_key: string, new_password: string) => post<RecoveryReceipt>('/api/v1/auth/recover', { username, recovery_key, new_password }),
  changeLogin: (token: string, login_name: string, current_password: string, expected_version: number) => post<{ login_name: string }>('/api/v1/account/login-name', { login_name, current_password, expected_version }, token),
  rotate: (token: string, current_password: string) => post<RecoveryReceipt>('/api/v1/account/recovery-key', { current_password }, token),
}
