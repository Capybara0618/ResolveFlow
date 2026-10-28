import type { SupportAssistant, SupportBuyerPart, SupportCitation, SupportConversation, SupportMessage } from './support-client'

/** A presentation never replaces history text or grants permission to submit an application. */
export function buyerParts(message: SupportMessage): SupportBuyerPart[] | null {
  const view = message.assistant?.buyer_view
  if (!view || view.version !== 'buyer-view-v1' || !Array.isArray(view.parts) || !view.parts.length || view.parts.length > 8) return null
  if (view.parts.some(p => !p || typeof p.text !== 'string' || !p.text.trim() || typeof p.task_id !== 'string' ||
    (p.guidance !== undefined && (typeof p.guidance !== 'string' || !p.guidance.trim() || !!p.action)))) return null
  return view.parts.flatMap(p => p.guidance ? [p.text, p.guidance] : [p.text]).join('\n\n') === message.text ? view.parts : null
}
export function assistantOffers(message: SupportMessage, action: 'REFUND_APPLICATION' | 'MERCHANT_REVIEW'): boolean {
  const assistant = message.assistant
  const reason = action === 'REFUND_APPLICATION' ? assistant?.refund_summary : assistant?.handoff_summary
  if (!reason?.trim()) return false
  if (!assistant?.buyer_view) return true // Historical offers keep their existing confirmation flow.
  return buyerParts(message)?.some(p => p.action === action) ?? false
}

export const sourceLabels = { ORDER: '订单事实', SHIPMENT: '物流事实', POLICY: '店铺政策', CONVERSATION: '对话原文', KNOWLEDGE: '使用指南' }
export const shipmentLabel = (value: unknown) => {
  const labels: Record<string, string> = { IN_TRANSIT: '运输中', DELAYED: '运输延迟', EXCEPTION_DELAYED: '物流延迟异常', DELIVERED: '记录显示已签收', LOST: '承运方确认丢失', UNKNOWN: '状态待核实', NOT_SHIPPED: '尚未发货', ORDER_PAID: '订单已付款', SIMULATED_SHIPPED: '已模拟发货' }
  return typeof value === 'string' ? labels[value] || value : '待核实'
}
export const rows = (value: unknown): Record<string, unknown>[] => Array.isArray(value) ? value.filter(v => v && typeof v === 'object' && !Array.isArray(v)) : []
export function buyerShipmentLabel(value: unknown) {
  return typeof value === 'string' && ['IN_TRANSIT', 'DELAYED', 'DELIVERED', 'LOST', 'UNKNOWN', 'NOT_SHIPPED', 'ORDER_PAID', 'SIMULATED_SHIPPED'].includes(value) ? shipmentLabel(value) : '暂未确认'
}
export const stamp = (value: unknown, short = false) => {
  if (typeof value !== 'string' || !Number.isFinite(Date.parse(value))) return ''
  return new Date(value).toLocaleString('zh-CN', short ? { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false } : { hour12: false })
}
export const tail = (value: string) => value.slice(-6).toUpperCase()
export function lastAssistant(conversation: SupportConversation): SupportMessage | undefined {
  return conversation.messages.filter(m => m.author === 'ASSISTANT' && m.assistant).sort((a, b) => b.sequence - a.sequence)[0]
}
export function reportFor(conversation: SupportConversation, merchant: boolean): SupportAssistant | undefined {
  return merchant ? conversation.ticket?.report : lastAssistant(conversation)?.assistant
}
export function conversationTitle(c: SupportConversation) {
  const request = c.messages.filter(m => m.author === 'CUSTOMER').sort((a, b) => b.sequence - a.sequence)[0]?.text
  return c.ticket?.summary || request || c.product.name
}
export function shipmentIn(citations: SupportCitation[]) { return citations.find(c => c.source_type === 'SHIPMENT') }
export function shipmentEvents(citation?: SupportCitation) {
  return rows(citation?.data.lines).flatMap(line => rows(line.events)).sort((a, b) => String(b.occurred_at).localeCompare(String(a.occurred_at)))
}
