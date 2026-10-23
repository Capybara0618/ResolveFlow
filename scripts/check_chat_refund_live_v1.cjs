// Actual Vue -> Gateway -> Case -> Python -> DeepSeek, with one new simulated commerce transaction.
const { chromium } = require('playwright');
const fs = require('fs');
const assert = require('assert/strict');
const directory = 'reports/chat-refund-live-v1';
const plan = JSON.parse(fs.readFileSync(`${directory}/plan.json`, 'utf8'));
const output = `${directory}/browser.json`;
assert(!fs.existsSync(output), 'Never overwrite an earlier execution');
const report = { turns: [], events: [], writes: [], checks: [], errors: [], httpErrors: [] };
let active;
const save = () => fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
async function api(page, path, method = 'GET', body, key) {
  return page.evaluate(async ({ path, method, body, key }) => {
    const token = JSON.parse(sessionStorage.getItem('resolveflow.tab-session.v1')).session.access_token;
    const response = await fetch(path, { method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...(key ? { 'Idempotency-Key': key } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) });
    return { status: response.status, body: await response.json() };
  }, { path, method, body, key });
}
async function login(browser, username) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  page.on('pageerror', error => report.errors.push(error.message));
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/') || request.method() === 'GET' || path.includes('/auth/')) return;
    report.writes.push({ path, method: request.method(), body: request.postDataJSON(), key: request.headers()['idempotency-key'] });
  });
  page.on('response', response => { if (response.url().includes('/api/') && response.status() >= 400) report.httpErrors.push({ path: new URL(response.url()).pathname, status: response.status() }); });
  await page.goto('http://127.0.0.1:5174/#/login');
  await page.locator('[name=username]').fill(username);
  await page.locator('[name=password]').fill(process.env.RESOLVEFLOW_DEMO_PASSWORD || '123456');
  await page.locator('[data-test=login]').click();
  await page.getByRole('button', { name: /退出/ }).waitFor();
  return page;
}
async function screenshot(page, name) {
  await page.screenshot({ path: `${directory}/${name}.png`, fullPage: true });
}
(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  try {
    const page = await login(browser, plan.customer);
    await page.exposeBinding('recordRefundAcceptance', (_, value) => {
      if (!active) return;
      const record = { ...value, turn: active.index, elapsed_ms: value.at - active.started_at };
      report.events.push(record);
      if (value.type === 'body' && active.first_body_ms === undefined) active.first_body_ms = record.elapsed_ms;
      if (value.type === 'state' && active.first_feedback_ms === undefined) active.first_feedback_ms = record.elapsed_ms;
    });
    await page.addInitScript(() => {
      let lastBody = '', lastState = '';
      new MutationObserver(() => {
        const body = document.querySelector('[data-generation] .support-message-bubble p')?.textContent?.replace(/▍$/, '') || '';
        const state = document.querySelector('.support-agent-state')?.textContent || '';
        if (body && body !== '正在完善回答…' && body !== lastBody) window.recordRefundAcceptance({ type: 'body', at: Date.now(), text: body });
        if (state && state !== lastState) window.recordRefundAcceptance({ type: 'state', at: Date.now(), text: state });
        lastBody = body; lastState = state;
      }).observe(document, { subtree: true, childList: true, characterData: true });
      const original = window.fetch;
      window.fetch = async function (...args) {
        const response = await original.apply(this, args);
        if (response.headers.get('content-type')?.includes('text/event-stream')) {
          const reader = response.clone().body.getReader();
          void (async () => {
            const decoder = new TextDecoder(); let buffer = '';
            try {
              while (true) {
                const chunk = await reader.read(); if (chunk.done) break;
                buffer += decoder.decode(chunk.value, { stream: true }).replace(/\r\n/g, '\n');
                let boundary;
                while ((boundary = buffer.indexOf('\n\n')) >= 0) {
                  const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
                  const data = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n');
                  if (data) window.recordRefundAcceptance({ type: 'event', at: Date.now(), event: JSON.parse(data) });
                }
              }
            } catch { /* UI owns reconnect; observing the transport never resends anything. */ }
          })();
        }
        return response;
      };
    });
    await page.goto('http://127.0.0.1:5174/#/shop/support');
    await page.locator(`[data-conversation][data-line-id="${plan.line_id}"]`).click();
    await page.locator('.support-product').waitFor();
    for (const [index, text] of plan.turns.entries()) {
      const count = await page.locator('.support-message.assistant:not([data-generation])').count();
      await page.getByLabel('咨询消息', { exact: true }).fill(text);
      active = { index, text, started_at: Date.now() }; report.turns.push(active);
      await page.locator('[data-action=send]').click();
      const deadline = Date.now() + 90000;
      while (Date.now() < deadline) {
        const formal = page.locator('.support-message.assistant:not([data-generation])');
        if (await formal.count() > count) {
          active.completed_ms = Date.now() - active.started_at;
          active.answer = await formal.last().locator('.support-message-bubble p').innerText();
          break;
        }
        if (await page.locator('.support-agent-state').filter({ hasText: '未能完成' }).count()) break;
        await page.waitForTimeout(50);
      }
      await screenshot(page, `turn-${index + 1}`); save();
      assert(active.completed_ms !== undefined, 'Agent did not publish this turn');
      assert.equal(await page.locator('[data-generation]').count(), 0);
      console.log(JSON.stringify({ turn: index + 1, first_body_ms: active.first_body_ms, completed_ms: active.completed_ms }));
      active = null;
      if (index === 0) {
        const v = await api(page, `/api/v1/support/conversations/${plan.conversation_id}/refund-application`);
        assert.equal(v.status, 200); assert.equal(v.body.draft, null); assert.equal(v.body.application, null);
        report.checks.push('logistics-only turn creates no draft or Case');
      }
    }
    await page.locator('[data-refund=confirm]').waitFor({ timeout: 15000 });
    const base = `/api/v1/support/conversations/${plan.conversation_id}`;
    let response = await api(page, base + '/refund-application');
    assert.equal(response.status, 200); assert.equal(response.body.draft.amount_minor, plan.amount_minor); assert.equal(response.body.application, null);
    report.original_draft = response.body.draft;
    await page.locator('[data-refund=edit]').click();
    const reason = '合成验收：本人未收到商品，承运商记录为丢失，请商家核实后退还这件商品全部实付款。';
    await page.locator('[aria-label="退款申请原因"]').fill(reason);
    await page.locator('[data-refund=save]').click(); await page.locator('[data-refund=confirm]').waitFor();
    response = await api(page, base + '/refund-application');
    assert.equal(response.body.draft.reason, reason); assert.equal(response.body.application, null);
    report.checks.push('accepted summary editable; correct paid amount; no Case before confirm');
    await page.locator('.chat-refund').scrollIntoViewIfNeeded(); await screenshot(page, 'editable-confirmation');
    const confirmAt = Date.now(); await page.locator('[data-refund=confirm]').click();
    await page.locator('.refund-progress').waitFor({ timeout: 15000 });
    report.confirm_receipt_ms = Date.now() - confirmAt;
    response = await api(page, base + '/refund-application');
    const caseId = response.body.application.case.case_id; report.case_id = caseId; report.confirmed = response.body;
    const sent = report.writes.find(w => w.path.endsWith('/confirm'));
    const replay = await api(page, sent.path, 'POST', sent.body, sent.key);
    assert.equal(replay.status, 200); assert.equal(replay.body.application.case.case_id, caseId);
    await page.reload(); await page.locator('.refund-progress').waitFor();
    assert.equal(await page.locator('.refund-progress a').getAttribute('href'), `#/customer/applications/${caseId}`);
    report.checks.push('same-key confirmation and browser refresh restore the same application');
    await screenshot(page, 'submitted-progress'); save();
    const merchant = await login(browser, plan.merchant);
    let detail;
    const until = Date.now() + 180000;
    while (Date.now() < until) {
      const read = await api(merchant, '/api/v1/cases/' + caseId);
      assert.equal(read.status, 200); detail = read.body;
      if (!['QUEUED', 'ANALYZING'].includes(detail.case.status)) break;
      await merchant.waitForTimeout(1000);
    }
    report.case_investigation = detail; save();
    assert.equal(detail.case.description, reason);
    assert.equal(detail.case.status, 'PENDING_REVIEW', 'No usable independently reviewable live refund proposal');
    await merchant.getByRole('link', { name: '售后工单', exact: true }).click();
    await merchant.getByLabel('搜索工单', { exact: true }).fill(caseId);
    await merchant.locator('.queue-filters').getByRole('button', { name: '查询', exact: true }).click();
    await merchant.locator('.merchant-case-card').filter({ hasText: reason.slice(0, 30) }).getByRole('button', { name: '查看工单' }).click();
    await merchant.locator('[data-test=approve]').waitFor();
    await screenshot(merchant, 'merchant-review');
    assert(!(await merchant.locator('body').innerText()).includes(plan.turns[0]));
    report.checks.push('merchant sees confirmed reason and review proposal, not private chat');
    await merchant.locator('[data-test=approve]').click();
    await merchant.locator('.decision-reason textarea').fill('合成验收：已核对承运商丢失记录、当前订单行实付与政策依据，同意本次整行模拟退款。');
    await merchant.locator('[data-test=confirm-review]').click();
    const settle = Date.now() + 60000;
    while (Date.now() < settle) {
      response = await api(page, base + '/refund-application');
      if (response.body.application.case.status === 'CLOSED_SUCCESS') break;
      await page.waitForTimeout(1000);
    }
    report.final = response.body; save();
    assert.equal(response.body.application.case.status, 'CLOSED_SUCCESS');
    await page.locator('.refund-progress button').click();
    await page.locator('.refund-progress header strong').filter({ hasText: '退款完成' }).waitFor();
    await screenshot(page, 'refund-complete');
    await page.locator('.refund-progress a').click();
    await page.locator('body').filter({ hasText: caseId }).waitFor();
    await screenshot(page, 'same-application-detail');
    report.checks.push('merchant approval settles simulated refund; conversation and original detail show same Case');
    assert.equal(report.writes.filter(w => w.path.endsWith('/messages')).length, 2);
    assert.equal(report.writes.filter(w => w.path.endsWith('/confirm')).length, 2);
    assert.equal(report.errors.length, 0); assert.equal(report.httpErrors.length, 0);
    report.success = true;
  } catch (error) {
    report.failure = error.message; process.exitCode = 1;
    console.error(error.message);
  } finally { save(); await browser.close(); }
})();
