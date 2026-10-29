import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import BuyerApplicationProgress from '../src/ui/BuyerApplicationProgress.vue'
import type { CustomerCaseDetail } from '../src/client'

function application(status: string, amount: number | null = null): CustomerCaseDetail {
  return { case: { case_id: 'case-demo', line_id: 'line-demo', order_id: 'order-demo', description: '没有收到商品', status, version: 1,
    created_at: '2026-10-28T02:00:00Z', updated_at: '2026-10-28T02:10:00Z' },
  input_revision: 1, allowed_actions: [], blocked_reason: '', materials: [], questions: [],
  result: { status, message: status === 'PENDING_REVIEW' ? '本次调查未完成，已转商家继续核查' : '服务端公开进展', amount_minor: amount, currency: 'CNY', public_reason: null },
  timeline: [{ type: 'CASE_CREATED', occurred_at: '2026-10-28T02:00:00Z', summary: '退款申请已提交' }] }
}

describe('buyer application progress', () => {
  it.each(['QUEUED', 'ANALYZING', 'PENDING_REVIEW', 'AUTHORIZED', 'EXECUTING', 'RECONCILING'])('does not present %s as a completed refund', status => {
    const w = mount(BuyerApplicationProgress, { props: { application: application(status, 32900) } })
    expect(w.find('[data-refund-success]').exists()).toBe(false)
    expect(w.text()).not.toContain('已退金额')
    expect(w.find('[role="progressbar"]').exists()).toBe(false)
    if (status === 'RECONCILING') {
      expect(w.text()).toContain('退款结果待确认')
      expect(w.text()).toContain('请勿重复申请')
    }
  })

  it('keeps Java pending-review distinctions and public reasons without repeating the headline', () => {
    const detail = application('PENDING_REVIEW')
    detail.result.public_reason = '需要核实包裹是否实际收到。'
    const w = mount(BuyerApplicationProgress, { props: { application: detail } })
    expect(w.get('header strong').text()).toBe(detail.result.message)
    expect(w.text().split(detail.result.message)).toHaveLength(2)
    expect(w.text()).toContain(detail.result.public_reason)
    expect(w.get<HTMLDetailsElement>('details').element.open).toBe(false)
    expect(w.text()).toContain('退款申请已提交')
  })

  it('shows only the confirmed Java amount and keeps the simulated-money boundary visible', () => {
    const w = mount(BuyerApplicationProgress, { props: { application: application('CLOSED_SUCCESS', 32900) } })
    expect(w.get('[data-refund-success]').text()).toContain('退款完成')
    expect(w.get('[data-refund-result-amount]').text()).toContain('329.00')
    expect(w.text()).toContain('模拟退款')
    expect(w.text()).not.toContain('原路到账')
    expect(w.find('[aria-current="step"]').exists()).toBe(false)
    expect(w.find('.buyer-progress-stages').exists()).toBe(false)
  })

  it('keeps product context inside the receipt instead of requiring a separate overview panel', () => {
    const w = mount(BuyerApplicationProgress, { props: { application: application('CLOSED_SUCCESS', 32900) }, slots: { product: '<span>无线降噪耳机 · 银色 · 松间数码</span>' } })
    expect(w.get('.buyer-receipt-product').text()).toContain('无线降噪耳机')
    expect(w.get<HTMLDetailsElement>('details').element.open).toBe(false)
  })

  it('does not invent a paid amount or a success date when the result omits them', () => {
    const detail = application('CLOSED_SUCCESS')
    detail.case.updated_at = ''
    const w = mount(BuyerApplicationProgress, { props: { application: detail } })
    expect(w.find('[data-refund-result-amount]').exists()).toBe(false)
    expect(w.text()).not.toContain('¥0')
    expect(w.find('time').exists()).toBe(true) // Only the actual timeline event has a timestamp.
    expect(w.text()).not.toContain('到账时间')
  })

  it.each(['CLOSED_REJECTED', 'CANCELLED', 'FUTURE_STATE'])('keeps %s separate from refund success and exposes public blockers', status => {
    const detail = application(status)
    detail.blocked_reason = '当前申请不能继续操作。'
    const w = mount(BuyerApplicationProgress, { props: { application: detail } })
    expect(w.find('[data-refund-success]').exists()).toBe(false)
    expect(w.find('[aria-current="step"]').exists()).toBe(false)
    expect(w.text()).toContain(detail.blocked_reason)
  })
})
