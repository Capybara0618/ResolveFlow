// Real Vue pages with explicit synthetic API responses. No business server or model calls.
const { chromium } = require('playwright');
const fs = require('fs');
const crypto = require('crypto');
const base = process.env.SUPPORT_UI_PREVIEW_URL || 'http://127.0.0.1:5175';
const root = 'reports/customer-support-ui-v2';
const fixture = JSON.parse(fs.readFileSync('contracts/core/fixtures/support-assistant.json', 'utf8'));
const clone = value => JSON.parse(JSON.stringify(value));
const c = clone(fixture.Conversation);
c.store_name = '松间数码'; c.order_id = 'ui-demo-order-6382'; c.line_id = 'ui-demo-line-6382'; c.ticket = null;
c.product = { name: '无线降噪耳机', variant: '黑色', asset_key: 'headphones', quantity: 1, amount_minor: 32900, currency: 'CNY' };
const question = c.messages[0]; question.text = '显示签收了，但我没有收到，家里人也没代收。'; question.created_at = '2026-10-20T06:32:00Z';
const answer = c.messages[1]; answer.text = '物流记录显示今天 10:42 已签收，但不能据此确认由你本人签收。\n你已确认家人没有代收，建议请商家核查签收凭证。'; answer.created_at = '2026-10-20T06:33:00Z';
answer.assistant.handoff_summary = '客户否认收到商品，家人未代收。请核实签收凭证及代收地点。';
answer.assistant.citations[0].data = { status: 'DELIVERED', synthetic: true, lines: [{ line_id: c.line_id, carrier_conclusion: 'DELIVERED', events: [{ code: 'IN_TRANSIT', occurred_at: '2026-10-19T10:18:00Z' }, { code: 'IN_TRANSIT', occurred_at: '2026-10-20T01:18:00Z' }, { code: 'DELIVERED', occurred_at: '2026-10-20T02:42:00Z' }] }] };
answer.assistant.citations.push({ source_id: 'P1', source_type: 'POLICY', content_hash: 'b'.repeat(64), version: '2026.10', title: '签收争议处理', data: { merchant_id: 'M-1001', rule_id: 'R-SIGNED-001', text: '存在签收争议时，需要核验签收凭证与代收情况；客户单方陈述不直接作为退款依据。' } });
c.messages.unshift({ ...clone(question), message_id: '00000000-0000-4000-8000-000000000009', sequence: 1, text: '私人备注：白天不方便接电话。', created_at: '2026-10-20T06:31:00Z' });
const b = clone(c); b.conversation_id = '00000000-0000-4000-8000-000000000006'; b.store_name = '拾光家居'; b.merchant_id = 'M-1002'; b.order_id = 'ui-demo-order-4821'; b.line_id = 'ui-demo-line-4821'; b.product = { ...b.product, name: '桌面台灯', asset_key: 'lamp', variant: '米白色', amount_minor: 12900 }; b.messages = []; b.version = 1; delete b.assistant_turn;
const old = clone(c); old.conversation_id = '00000000-0000-4000-8000-000000000007'; old.order_id = 'ui-demo-order-3291'; old.line_id = 'ui-demo-line-3291'; old.messages = []; old.ticket = { ticket_id: '00000000-0000-4000-8000-000000000008', status: 'RESOLVED', summary: '之前的运输进度咨询', shared_messages: [] };
let merchantView = { ...clone(c), messages: [], ticket: { ticket_id: fixture.TicketDetail.ticket.ticket_id, status: 'PENDING', summary: '客户希望核查签收情况，暂不申请退款。', shared_messages: [clone(question)], report: clone(answer.assistant) } };
delete merchantView.assistant_turn;
const waiting = clone(merchantView); waiting.conversation_id = '00000000-0000-4000-8000-000000000010'; waiting.order_id = 'ui-demo-order-7729'; waiting.line_id = 'ui-demo-line-7729'; waiting.product = { ...waiting.product, name: '无线鼠标', asset_key: 'mouse', amount_minor: 9900 }; waiting.ticket.ticket_id = '00000000-0000-4000-8000-000000000011'; waiting.ticket.status = 'WAITING_CUSTOMER'; waiting.ticket.summary = '请补充物流异常情况';
const buyerItems = [c, b, old];
const merchantItems = [merchantView, waiting];
const orders = buyerItems.map(v => ({ merchant_id: v.merchant_id, merchant_name: v.store_name, order_id: v.order_id, line_id: v.line_id, sku: 'UI-DEMO', product_name: v.product.name, variant_text: v.product.variant, asset_key: v.product.asset_key, category: 'electronics', quantity: 1, line_paid_amount: v.product.amount_minor, currency: 'CNY', paid_at: '2026-10-18T06:00:00Z', status: 'PAID' }));
const calls = [], unknown = [], checks = [], errors = [];
function assert(value, message) { if (!value) throw Error(message); }
async function routes(page) {
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method();
    const body = method === 'POST' ? request.postDataJSON() : undefined;
    calls.push({ method, path, ...(body && !path.endsWith('/login') ? { body } : {}) });
    let data;
    if (path === '/api/v1/auth/login') data = body.username === 'buyer01' ? { access_token: 'ui-fixture-buyer', role: 'CUSTOMER', buyer_id: 'B-UI', display_name: '买家01', expires_in: 3600 } : { access_token: 'ui-fixture-merchant', role: 'MERCHANT_ADMIN', merchant_id: 'M-1001', merchant_name: '松间数码', display_name: '松间数码商家', single_operator: true, expires_in: 3600 };
    else if (path === '/api/v1/shop/stores') data = [];
    else if (path.startsWith('/api/v1/shop/products')) data = { items: [], page: { limit: 20 } };
    else if (path === '/api/v1/review/cases') data = { items: [], page: { limit: 20 }, counts: { ALL: 0, REVIEW: 0, ATTENTION: 0, CLOSED: 0 } };
    else if (path === '/api/v1/admin/overview') data = { unclaimed: 0, mine: 0, attention: 0, coordination_total: 0, items: [] };
    else if (path === '/api/v1/orders') data = { items: orders, page: { limit: 20 } };
    else if (path === '/api/v1/support/conversations' && method === 'GET') data = { items: buyerItems.map(v => ({ ...v, messages: [] })), next_before: null };
    else if (path === '/api/v1/support/tickets' && method === 'GET') data = { items: merchantItems.map(v => ({ ...v, messages: [] })), next_before: null };
    else if (path === '/api/v1/support/conversations' && method === 'POST') data = buyerItems.find(v => v.line_id === body.line_id);
    else if (path === `/api/v1/support/conversations/${c.conversation_id}/tickets` && method === 'POST') {
      assert(body.expected_version === c.version, 'preview used the wrong input version');
      assert(body.assistant_message_id === answer.message_id, 'source report was not explicitly confirmed');
      assert(body.shared_message_ids.length === 1 && body.shared_message_ids[0] === question.message_id, 'private original was shared');
      c.ticket = { ...clone(merchantView.ticket), summary: body.summary }; c.version++;
      merchantView = { ...clone(c), messages: [], ticket: clone(c.ticket) }; merchantItems[0] = merchantView;
      delete merchantView.assistant_turn;
      data = c;
    } else if (path === `/api/v1/support/tickets/${merchantView.ticket.ticket_id}/messages` && method === 'POST') {
      assert(body.kind === 'REQUEST_INFO', 'reply-kind control did not update request');
      merchantView.version++; merchantView.ticket.status = 'WAITING_CUSTOMER';
      merchantView.messages.push({ message_id: '00000000-0000-4000-8000-000000000012', sequence: merchantView.version, author: 'MERCHANT', recipient: 'CUSTOMER', ticket_id: merchantView.ticket.ticket_id, text: body.text, created_at: '2026-10-20T06:40:00Z' });
      data = merchantView;
    } else if (method === 'GET' && path.startsWith('/api/v1/support/conversations/')) data = buyerItems.find(v => path.endsWith(v.conversation_id));
    else if (method === 'GET' && path.startsWith('/api/v1/support/tickets/')) data = merchantItems.find(v => path.endsWith(v.ticket.ticket_id));
    if (!data) { unknown.push({ path, method }); await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ code: 'UNEXPECTED_UI_FIXTURE_REQUEST', message: 'Unexpected preview request' }) }); return; }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });
}
async function login(browser, username) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } }); await routes(page);
  await page.goto(base + '/#/login'); await page.locator('[name="username"]').fill(username); await page.locator('[name="password"]').fill('123456'); await page.locator('[data-test="login"]').click();
  if (username === 'buyer01') await page.getByRole('link', { name: '售后咨询', exact: true }).click();
  else await page.locator('.nav-link').filter({ hasText: '咨询核查' }).click();
  await page.locator('.support-main .support-chat-heading').waitFor(); return page;
}
async function capture(page, name, dialog = false) {
  for (const [width, height] of [[1280, 800], [1440, 900], [1600, 1000]]) {
    await page.setViewportSize({ width, height });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const result = await page.evaluate(() => {
      const main = document.querySelector('.support-main'), composer = document.querySelector('.support-compose'), context = document.querySelector('.support-context');
      return { horizontal_overflow: document.documentElement.scrollWidth > innerWidth + 1, page_vertical_overflow: document.documentElement.scrollHeight > innerHeight + 2, composer_bottom: composer.getBoundingClientRect().bottom, main_height: main.getBoundingClientRect().height, context_bottom: context.getBoundingClientRect().bottom };
    });
    assert(!result.horizontal_overflow, `${name} horizontal overflow at ${width}`);
    assert(!result.page_vertical_overflow, `${name} unexpected outer scrolling at ${width}`);
    assert(result.composer_bottom <= height + 1, `${name} composer outside viewport`);
    checks.push({ view: name, width, height, ...result, dialog });
  }
  await page.setViewportSize({ width: 1440, height: 900 }); await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))); await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: `${root}/images/${name}.png`, fullPage: true });
}
(async () => {
  fs.mkdirSync(`${root}/images`, { recursive: true });
  fs.writeFileSync(`${root}/preview-data.json`, JSON.stringify({ synthetic: true, original_contract_fixture: 'contracts/core/fixtures/support-assistant.json', conversations: buyerItems, tickets: merchantItems, orders }, null, 2) + '\n');
  const browser = await chromium.launch({ headless: true, channel: process.env.CUSTOMER_PREVIEW_BROWSER || 'msedge' });
  try {
    const buyer = await login(browser, 'buyer01');
    assert((await buyer.locator('[data-conversation]').count()) === 3, 'buyer conversations missing');
    assert(await buyer.locator('.support-context').getByText('记录显示已签收', { exact: true }).count(), 'cited logistics not shown');
    await capture(buyer, 'buyer-chat');
    const policy = buyer.locator('.support-message.assistant .support-citation').filter({ hasText: '店铺政策' });
    await policy.locator('summary').click();
    assert(await policy.locator('.source-body').isVisible(), 'policy source cannot be expanded');
    assert((await policy.textContent()).includes('版本 2026.10'), 'policy version missing');
    await policy.locator('summary').click();
    checks.push({ interaction: 'answer source chips expand to original policy and version', passed: true });
    await buyer.getByLabel('咨询消息', { exact: true }).fill('保留我的未发出补充');
    await buyer.getByRole('button', { name: '＋ 选择订单', exact: false }).click();
    await buyer.getByRole('dialog').waitFor();
    assert(await buyer.locator('.support-order').count() === 3, 'orders not shown in chooser');
    assert(await buyer.evaluate(() => document.querySelector('[role="dialog"]').contains(document.activeElement)), 'dialog did not receive focus');
    await buyer.keyboard.press('Shift+Tab'); await buyer.keyboard.press('Shift+Tab');
    assert(await buyer.locator('.support-order').last().evaluate(el => document.activeElement === el), 'Shift+Tab escaped the dialog');
    await buyer.keyboard.press('Tab');
    assert(await buyer.getByLabel('关闭弹层', { exact: true }).evaluate(el => document.activeElement === el), 'Tab escaped the dialog');
    await buyer.getByLabel('搜索已加载订单商品', { exact: true }).focus();
    await capture(buyer, 'buyer-order-picker', true);
    await buyer.keyboard.press('Escape');
    assert(await buyer.getByLabel('咨询消息', { exact: true }).inputValue() === '保留我的未发出补充', 'closing picker lost draft');
    checks.push({ interaction: 'order chooser traps focus and Escape preserves draft', passed: true });
    await buyer.getByLabel('咨询消息', { exact: true }).fill('');
    await buyer.locator('[data-action="preview-handoff"]').click();
    assert(!(await buyer.locator('[data-share-report]').isChecked()), 'report shared by default');
    await buyer.getByLabel('核查摘要', { exact: true }).fill('客户确认：请核查签收凭证及代收地点，暂不申请退款。');
    await buyer.locator('[data-share-report]').check();
    await buyer.locator('.support-preview .support-check').filter({ hasText: question.text }).locator('input').check();
    assert(!calls.some(v => v.method === 'POST' && v.path.endsWith('/tickets')), 'preview created a ticket');
    await capture(buyer, 'buyer-handoff-confirm', true);
    await buyer.locator('[data-action="confirm-handoff"]').click();
    await buyer.locator('.support-ticket').waitFor();
    checks.push({ interaction: 'editable summary, opt-in report and one selected original submitted only after confirmation', passed: true });
    const merchant = await login(browser, 'admin01');
    assert(!(await merchant.locator('.support-main').textContent()).includes('私人备注'), 'private note leaked to merchant');
    assert(!(await merchant.locator('.support-message.assistant').count()), 'private assistant chat leaked to merchant');
    await capture(merchant, 'merchant-investigation');
    await merchant.locator('.support-filters button').filter({ hasText: '待补充' }).click();
    assert(await merchant.locator('[data-conversation]').count() === 1, 'merchant status filter does not match actual queue');
    await merchant.locator('.support-filters button').filter({ hasText: '全部' }).click();
    checks.push({ interaction: 'merchant loaded queue counts and status filters are consistent', passed: true });
    await merchant.getByRole('button', { name: '请求客户补充', exact: true }).click();
    await merchant.getByLabel('咨询消息', { exact: true }).fill('请补充是否有授权代收，我们继续核查签收记录。');
    await merchant.locator('[data-action="send"]').click();
    await merchant.getByText('请补充是否有授权代收，我们继续核查签收记录。', { exact: true }).first().waitFor();
    checks.push({ interaction: 'merchant sees shared projection and can request more information', passed: true });
    assert(!unknown.length, JSON.stringify(unknown)); assert(!errors.length, JSON.stringify(errors));
    const images = ['buyer-chat', 'buyer-order-picker', 'buyer-handoff-confirm', 'merchant-investigation'].map(name => ({ path: `images/${name}.png`, sha256: crypto.createHash('sha256').update(fs.readFileSync(`${root}/images/${name}.png`)).digest('hex') }));
    fs.writeFileSync(`${root}/browser-check.json`, JSON.stringify({ data_mode: 'synthetic API fixtures', real_vue_components: true, business_servers_started: false, model_calls: 0, checks, images, unknown_requests: unknown, page_errors: errors, calls }, null, 2) + '\n');
    console.log(JSON.stringify({ checks: checks.length, images: images.length, page_errors: errors.length, model_calls: 0 }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
