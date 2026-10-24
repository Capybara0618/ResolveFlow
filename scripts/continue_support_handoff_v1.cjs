// Continue an already successful persisted answer. This script must never send a model message.
const { chromium } = require('playwright');
const fs = require('fs');
const assert = require('assert/strict');
const dir = 'reports/customer-agent-orchestration-acceptance-v1/recheck-v1';
const group = JSON.parse(fs.readFileSync(`${dir}/plan.json`, 'utf8')).groups[0];
const output = `${dir}/handoff-continuation.json`;
assert(!fs.existsSync(output));
const report = { success: false, model_messages_sent: 0, writes: [], errors: [] };
const save = () => fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
async function api(page, path) {
  return page.evaluate(async path => {
    const token = JSON.parse(sessionStorage.getItem('resolveflow.tab-session.v1')).session.access_token;
    const response = await fetch(path, { headers: { Authorization: `Bearer ${token}` } });
    return { status: response.status, body: await response.json() };
  }, path);
}
async function login(browser, name) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  page.on('pageerror', e => report.errors.push(e.message));
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/') || request.method() === 'GET' || path.includes('/auth/')) return;
    assert(!path.endsWith('/messages'), 'Cannot resend a model or customer message');
    report.writes.push({ path, body: request.postDataJSON(), key: request.headers()['idempotency-key'] });
  });
  await page.goto('http://127.0.0.1:5174/#/login');
  await page.locator('[name=username]').fill(name);
  await page.locator('[name=password]').fill(process.env.RESOLVEFLOW_DEMO_PASSWORD || '123456');
  await page.locator('[data-test=login]').click();
  await page.getByRole('button', { name: /退出/ }).waitFor();
  return page;
}
(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  try {
    const page = await login(browser, group.customer);
    await page.goto('http://127.0.0.1:5174/#/shop/support');
    await page.locator(`[data-conversation][data-line-id="${group.line_id}"]`).click();
    await page.locator('[data-action=preview-handoff]').waitFor();
    const base = `/api/v1/support/conversations/${group.conversation_id}`;
    const conversation = (await api(page, base)).body;
    const latest = conversation.messages.findLast(m => m.author === 'ASSISTANT');
    assert.equal(latest.assistant.run_id, 'c0c9ba17-e53a-4188-9d6a-d5f9edcd2230');
    assert(latest.assistant.handoff_summary && !latest.assistant.refund_summary);
    report.accepted_assistant = latest;
    await page.locator('[data-action=preview-handoff]').click();
    assert.equal(await page.getByLabel('核查摘要', { exact: true }).inputValue(), latest.assistant.handoff_summary);
    const summary = latest.assistant.handoff_summary + ' 请商家核对承运记录后回复核查进度。';
    await page.getByLabel('核查摘要', { exact: true }).fill(summary);
    await page.locator('[data-share-report]').check();
    await page.getByRole('checkbox', { name: group.turns[0], exact: true }).check();
    await page.screenshot({ path: `${dir}/human-editable-preview.png`, fullPage: true });
    await page.locator('[data-action=confirm-handoff]').click();
    await page.locator('.support-ticket').waitFor();
    report.shared_conversation = (await api(page, base)).body;
    const refund = (await api(page, base + '/refund-application')).body;
    assert.equal(refund.draft, null); assert.equal(refund.application, null);
    const merchant = await login(browser, group.merchant);
    const ticket = await api(merchant, `/api/v1/support/tickets/${report.shared_conversation.ticket.ticket_id}`);
    assert.equal(ticket.status, 200);
    report.merchant_projection = ticket.body;
    assert.equal(ticket.body.ticket.summary, summary);
    assert.equal(ticket.body.ticket.shared_messages.length, 1);
    assert.equal(ticket.body.ticket.shared_messages[0].text, group.turns[0]);
    assert(ticket.body.ticket.report.citations.length > 0);
    assert(!ticket.body.messages.some(m => m.text === '我现在不打算退款，只想请商家人工帮忙核查耳机没收到的问题。我已经问过家人和代收点，都没有找到。请先给我一份可以确认后转交商家的摘要。'));
    await page.screenshot({ path: `${dir}/human-confirmed-handoff.png`, fullPage: true });
    assert.equal(report.errors.length, 0);
    report.success = true;
  } catch (error) { report.failure = error.message; process.exitCode = 1; }
  finally { save(); await browser.close(); }
})();
