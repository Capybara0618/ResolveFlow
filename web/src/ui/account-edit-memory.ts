import type { AddressInput } from '../account-client'

/** Owned by the current buyer workspace; never persisted and never contains passwords. */
export interface AccountEditMemory {
  profile?: { version: number; nickname: string; phone: string; gender: string; birthday: string }
  address?: { id: string | null; form: AddressInput }
}
