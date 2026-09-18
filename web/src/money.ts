/**
 * Money helpers.
 *
 * Every amount in ResolveFlow is an integer count of minor units (fen) end to end
 * (docs/domain-model.md, INV-01). The browser must not introduce floating point
 * arithmetic on money, so formatting is the ONLY thing that happens here — no
 * arithmetic beyond integer-safe operations.
 */

const MINOR_UNITS_PER_MAJOR = 100

export function formatMinorUnits(amountMinor: number, currency = 'CNY'): string {
  if (!Number.isInteger(amountMinor)) {
    // Reject rather than silently round: a fractional minor unit means an
    // upstream bug, and quietly formatting it would hide the corruption.
    throw new Error(`amountMinor must be an integer number of minor units, got ${amountMinor}`)
  }

  const negative = amountMinor < 0
  // Integer-only split; avoids (amountMinor / 100).toFixed() drifting on large values.
  const absolute = Math.abs(amountMinor)
  const major = Math.trunc(absolute / MINOR_UNITS_PER_MAJOR)
  const minor = absolute % MINOR_UNITS_PER_MAJOR
  const sign = negative ? '-' : ''

  return `${sign}${major}.${String(minor).padStart(2, '0')} ${currency}`
}

export function sumMinorUnits(amounts: readonly number[]): number {
  return amounts.reduce((total, amount) => {
    if (!Number.isInteger(amount)) {
      throw new Error(`amountMinor must be an integer number of minor units, got ${amount}`)
    }
    return total + amount
  }, 0)
}