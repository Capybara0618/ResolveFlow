import { afterEach, expect, it, vi } from 'vitest'
import { clearTabSession, readTabSession, saveTabSession, readSupportSelection, saveSupportSelection } from '../src/tab-session'

afterEach(() => { sessionStorage.clear(); vi.restoreAllMocks() })
const buyer = { access_token: 'buyer-token', role: 'CUSTOMER' as const, buyer_id: 'B-1', expires_in: 3600 }

it('restores a tab session until its original expiry, without extending it on read', () => {
  vi.spyOn(Date, 'now').mockReturnValue(1000)
  saveTabSession(buyer)
  vi.spyOn(Date, 'now').mockReturnValue(3600999)
  expect(readTabSession()).toEqual(buyer)
  vi.spyOn(Date, 'now').mockReturnValue(3601000)
  expect(readTabSession()).toBeNull()
})

it('logout removes only the login, leaving existing pending business commands intact', () => {
  sessionStorage.setItem('existing-pending', 'request-key')
  saveTabSession(buyer); clearTabSession()
  expect(readTabSession()).toBeNull()
  expect(sessionStorage.getItem('existing-pending')).toBe('request-key')
})

it('a malformed stored login is discarded rather than blocking ordinary login', () => {
  saveTabSession(buyer)
  const key = sessionStorage.key(0)!
  sessionStorage.setItem(key, '{broken')
  expect(readTabSession()).toBeNull()
  expect(sessionStorage.getItem(key)).toBeNull()
})

it('isolates selected conversations by account and tolerates disabled storage', () => {
  saveSupportSelection('CUSTOMER:B-1', 'conversation-1')
  expect(readSupportSelection('CUSTOMER:B-1')).toBe('conversation-1')
  expect(readSupportSelection('CUSTOMER:B-2')).toBeNull()
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw Error('blocked') })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw Error('blocked') })
  expect(() => saveTabSession(buyer)).not.toThrow()
  expect(readTabSession()).toBeNull()
})
