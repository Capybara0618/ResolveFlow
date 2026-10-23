/* Built Vue + real loopback HTTP, synthetic business responses. No model or real business writes. */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const http = require('http');
const assert = require('assert/strict');
const root = path.resolve('web/dist');
const out = path.resolve('reports/chat-refund-closure-v1/browser');
const fixture = JSON.parse(fs.readFileSync('contracts/core/fixtures/support.json', 'utf8'));
const refundFixture = JSON.parse(fs.readFileSync('contracts/core/fixtures/support-refund.json', 'utf8'));
const conversation = { ...fixture.Conversation, version: 3, ticket: null, messages: [
  { message_id: 'customer-1', sequence: 2, author: 'CUSTOMER', recipient: 'ASSISTANT', text: '家人和门卫都问过了，确实没有收到，请核查后退款。', ticket_id: null, created_at: '2026-10-23T10:00:00Z' },
  { message_id: 'assistant-1', sequence: 3, author: 'ASSISTANT', recipient: 'CUSTOMER', text: '你反馈商品尚未收到。可以核对下面的申请原因，再确认提交；商家将进一步核查签收情况。', ticket_id: null, created_at: '2026-10-23T10:00:01Z', assistant: { run_id: 'synthetic-run', mode: 'mock', citations: [], handoff_summary: null } },
] };
let view = { draft: null, application: null }, creates = 0, lost = false;
let confirmation, confirmations = [], unexpected = [];
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  function json(body, code = 200) { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(body)); }
  try {
    if (url.pathname.startsWith('/api/')) {
      if (url.pathname.endsWith('/events')) { res.writeHead(200, { 'Content-Type': 'text/event-stream' }); res.write(': synthetic heartbeat\n\n'); return; }
      if (url.pathname === '/api/v1/shop/stores') return json([]);
      if (url.pathname === '/api/v1/orders') return json({ items: [], page: { limit: 20 } });
      if (url.pathname === '/api/v1/support/conversations') return json({ items: [conversation], next_before: null });
      const base = '/api/v1/support/conversations/' + conversation.conversation_id;
      if (url.pathname === base) return json(conversation);
      if (url.pathname === base + '/refund-application') return json(view);
      const parts = url.pathname.slice(base.length).split('/').filter(Boolean);
      if (req.method === 'POST' && parts[0] === 'refund-drafts') {
        let raw = ''; for await (const chunk of req) raw += chunk;
        const body = JSON.parse(raw), key = req.headers['idempotency-key']; assert(key);
        if (parts.length === 1) {
          assert.equal(body.expected_version, conversation.version);
          view.draft = { ...refundFixture.Draft, expected_version: conversation.version, reason: body.reason, expires_at: new Date(Date.now() + 1800000).toISOString() };
        } else if (parts[2] === 'edit') {
          assert.equal(body.revision, view.draft.revision); view.draft.reason = body.reason; view.draft.revision++;
        } else if (parts[2] === 'cancel') {
          view.draft.status = 'CANCELLED'; view.draft.revision++;
        } else if (parts[2] === 'confirm') {
          confirmations.push({ key, body });
          if (!confirmation) {
            confirmation = { key, body }; creates++;
            view.draft.status = 'CONFIRMED'; view.draft.case_id = 'synthetic-one-case';
            view.application = { case: { case_id: 'synthetic-one-case', status: 'QUEUED', description: view.draft.reason, line_id: conversation.line_id, version: 1 }, input_revision: 1, allowed_actions: [], blocked_reason: '', materials: [], questions: [], result: { status: 'QUEUED', message: '申请已保存，正在等待核查。', amount_minor: null, currency: 'CNY', public_reason: null }, timeline: [{ type: 'CASE_CREATED', occurred_at: '2026-10-23T10:00:02Z', summary: '申请已提交' }] };
          } else { assert.deepEqual({ key, body }, confirmation); }
          if (!lost) { lost = true; return json({ code: 'RESULT_UNCONFIRMED', message: '模拟：业务已提交，但回执尚未确认' }, 503); }
        } else throw Error('unexpected mutation');
        return json(view);
      }
      unexpected.push(req.method + ' ' + req.url); return json({ code: 'NOT_FOUND', message: 'unexpected synthetic route' }, 404);
    }
    const file = path.resolve(root, '.' + (url.pathname === '/' ? '/index.html' : url.pathname));
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) { res.writeHead(404); res.end(); return; }
    res.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html'); res.end(fs.readFileSync(file));
  } catch (e) { unexpected.push(e.message); json({ code: 'TEST_FAILURE', message: e.message }, 500); }
});
(async () => {
  fs.mkdirSync(out, { recursive: true });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  const errors = [], checks = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on('pageerror', e => errors.push(e.message));
    await page.addInitScript(() => sessionStorage.setItem('resolveflow.tab-session.v1', JSON.stringify({ expires_at: Date.now() + 3600000, session: { access_token: 'synthetic-ui-only', role: 'CUSTOMER', buyer_id: 'B-browser', display_name: '买家01', expires_in: 3600 } })));
    const url = `http://127.0.0.1:${server.address().port}/#/shop/support`;
    await page.goto(url);
    await page.locator('[data-refund="start"]').click();
    await page.locator('[data-refund="save"]').click();
    await page.locator('[data-refund="confirm"]').waitFor();
    assert.equal(creates, 0); checks.push('prepare does not create a Case');
    await page.locator('.chat-refund').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(out, 'confirm.png'), fullPage: true });
    for (const width of [1280, 1440, 1680]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      assert.equal(await page.locator('.refund-summary').evaluate(e => e.scrollWidth > e.clientWidth + 1), false);
      checks.push('no horizontal overflow at ' + width);
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.locator('[data-refund="edit"]').click();
    await page.locator('[aria-label="退款申请原因"]').fill('已与家人和门卫确认均未收到，请商家核实签收后处理退款申请。');
    await page.locator('[data-refund="save"]').click(); await page.locator('[data-refund="confirm"]').waitFor();
    assert.equal(view.draft.revision, 2); checks.push('edited reason persisted before confirm');
    await page.locator('.refund-summary footer button').first().click(); await page.locator('[data-refund="start"]').waitFor();
    assert.equal(creates, 0); await page.locator('[data-refund="start"]').click();
    assert.match(await page.locator('textarea[aria-label="退款申请原因"]').inputValue(), /门卫/);
    await page.locator('[data-refund="save"]').click(); await page.locator('[data-refund="confirm"]').click();
    await page.locator('[data-refund="retry"]').waitFor(); checks.push('lost response retains request');
    await page.reload(); await page.locator('[data-refund="retry"]').waitFor();
    await page.locator('[data-refund="retry"]').click(); await page.locator('.refund-pending').waitFor({ state: 'hidden' });
    assert.equal(creates, 1); assert.deepEqual(confirmations[0], confirmations[1]); checks.push('reload retries identical key/body and returns one Case');
    assert.equal(await page.locator('.refund-progress a').getAttribute('href'), '#/customer/applications/synthetic-one-case');
    await page.locator('.chat-refund').scrollIntoViewIfNeeded(); await page.screenshot({ path: path.join(out, 'progress.png'), fullPage: true });
    view.application.case.status = 'RECONCILING'; view.application.result.message = '模拟退款结果待确认，请等待核查。';
    await page.locator('.refund-progress button').click();
    await page.getByText('退款结果待确认', { exact: true }).waitFor();
    assert.equal(await page.locator('.chat-refund').innerText().then(t => t.includes('退款完成')), false);
    await page.screenshot({ path: path.join(out, 'unknown.png'), fullPage: true }); checks.push('unknown is not refund success');
    assert.deepEqual(unexpected, []); assert.deepEqual(errors, []);
    const summary = { scope: 'built Vue + real loopback HTTP, synthetic business only', live_calls: 0, real_business_writes: 0, synthetic_cases_created: creates, checks, browser_errors: errors, unexpected_routes: unexpected };
    fs.writeFileSync(path.join(out, 'checks.json'), JSON.stringify(summary, null, 2) + '\n');
    console.log(JSON.stringify(summary));
  } finally { await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
})().catch(e => { console.error(e); process.exitCode = 1; });
