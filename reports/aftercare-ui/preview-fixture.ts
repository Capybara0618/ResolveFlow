// Temporary visual fixture: actual CustomerWorkspace, no credentials or business writes.
import { createApp, h } from 'vue'
import CustomerWorkspace from '../src/ui/CustomerWorkspace.vue'
import { coreApi } from '../src/client'
import '../src/ui/tokens.css'
import '../src/ui/workbench.css'
import '../src/ui/marketplace.css'
const line = { order_id: 'preview-order', line_id: 'preview-line', sku: 'preview-sku',
  merchant_id: 'preview-store', merchant_name: '松间数码', product_name: '无线降噪耳机',
  variant_text: '黑色', asset_key: 'headphones', category: 'electronics', quantity: 1,
  line_paid_amount: 32900, currency: 'CNY', status: 'PAID' }
const pending = { case_id: 'preview-case', line_id: line.line_id, order_id: line.order_id,
  description: '收到耳机后右耳有明显杂音，重置和更换设备后仍然存在，希望申请退款。',
  status: 'WAITING_CUSTOMER', version: 2, created_at: '2026-10-03T06:20:00Z', updated_at: '2026-10-03T06:25:00Z' }
coreApi.orderLine = async () => line
coreApi.orders = async () => ({ items: [line], page: { limit: 20 } })
coreApi.customerOrderLine = async () => ({ order_line: line, application: null, can_apply: true, blocked_reason: '' })
coreApi.customerCases = async () => ({ items: [pending], page: { limit: 20 } })
coreApi.customerCase = async () => ({ case: pending, input_revision: 1, allowed_actions: ['ANSWER', 'CANCEL'], blocked_reason: '', materials: [],
  questions: [{ question_id: 'preview-question', prompts: ['请补充耳机杂音出现的情况，以及更换设备后的结果。'],
    status: 'PENDING', asked_at: '2026-10-03T06:25:00Z', expires_at: new Date(Date.now() + 86400000).toISOString(), answers: [] }],
  result: { status: 'WAITING_CUSTOMER', message: '商家需要您补充说明', amount_minor: null, currency: 'CNY', public_reason: null },
  timeline: [{ type: 'CASE_CREATED', occurred_at: pending.created_at, summary: '申请已提交' },
    { type: 'QUESTION_CREATED', occurred_at: pending.updated_at, summary: '商家请求补充说明' }] })
// Fail closed if any button ever attempts a network write or an unmocked API read.
window.fetch = async () => { throw new Error('前端预览禁止网络请求与业务写入') }
createApp({ render: () => h('div', { class: 'workbench shopping-workbench' }, [
  h('header', { class: 'topbar' }, [h('div', { class: 'brand' }, 'ResolveFlow'),
    h('span', { class: 'demo-tag' }, '前端状态预览 · 合成数据 · 不写入业务')]),
  h('div', { class: 'marketplace buyer-aftercare' }, [h('nav', { class: 'shop-nav', 'aria-label': '买家导航' },
    ['商城', '购物车', '我的订单', '我的售后'].map(text => h('span', { style: 'font-size:18px;padding:24px;' }, text))),
    h(CustomerWorkspace, { account: { access_token: 'preview-no-auth', role: 'CUSTOMER', buyer_id: 'preview-buyer', expires_in: 3600, display_name: '合成买家' } })])]) }).mount('#app')
