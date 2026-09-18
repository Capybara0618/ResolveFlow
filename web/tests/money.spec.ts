import { describe, expect, it } from 'vitest'
import { formatMinorUnits, sumMinorUnits } from '../src/money'

describe('formatMinorUnits', () => {
  it('formats integer minor units without floating point drift', () => {
    expect(formatMinorUnits(20000)).toBe('200.00 CNY')
    expect(formatMinorUnits(1)).toBe('0.01 CNY')
    expect(formatMinorUnits(999)).toBe('9.99 CNY')
    expect(formatMinorUnits(0)).toBe('0.00 CNY')
  })

  it('handles the documented maximum amount', () => {
    // docs/contracts.md caps amount_minor at 1_000_000_000.
    expect(formatMinorUnits(1_000_000_000)).toBe('10000000.00 CNY')
  })

  it('formats the values that break naive float division', () => {
    // 0.1 + 0.2 style drift and values where (n/100) is not exact.
    expect(formatMinorUnits(19999999)).toBe('199999.99 CNY')
    expect(formatMinorUnits(70)).toBe('0.70 CNY')
    expect(formatMinorUnits(115)).toBe('1.15 CNY')
  })

  it('keeps the sign', () => {
    expect(formatMinorUnits(-1500)).toBe('-15.00 CNY')
  })

  it('refuses a fractional minor unit instead of rounding it away', () => {
    expect(() => formatMinorUnits(100.5)).toThrow(/integer number of minor units/)
  })
})

describe('sumMinorUnits', () => {
  it('sums exactly', () => {
    expect(sumMinorUnits([19999, 1, 1])).toBe(20001)
  })

  it('refuses to sum a fractional amount', () => {
    expect(() => sumMinorUnits([100, 0.5])).toThrow(/integer number of minor units/)
  })
})
