// Four independent real browser conversations, fixed inputs and no retry of failed model turns.
const { chromium } = require('playwright');
const fs = require('fs');
const assert = require('assert/strict');
const directory = 'reports/customer-agent-orchestration-acceptance-v1';
const plan = JSON.parse(fs.readFileSync(`${directory}/plan.json`, 'utf8'));
const output = `${directory}/controls-browser.json`;
assert(!fs.existsSync(output), 'Do not overwrite a prior execution');
const report = { groups: [], errors: [], writes: [] };
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
  await page.goto('http://127.0.0.1:5174/#/login');
  await page.locator('[name=username]').fill(username);
  await page.locator('[name=password]').fill(process.env.RESOLVEFLOW_DEMO_PASSWORD || '123456');
  await page.locator('[data-test=login]').click();
  await page.getByRole('button', { name: /退出/ }).waitFor();
  return page;
}
async function observe(page, receive) {
  await page.exposeBinding('recordSupportAdoption', (_, value) => receive(value));
  await page.evaluate(() => {
    let lastState = '', lastBody = '';
    new MutationObserver(() => {
      const state = document.querySelector('.support-agent-state')?.textContent || '';
      const body = document.querySelector('[data-generation] .support-message-bubble p')?.textContent?.replace(/▍$/, '') || '';
      if (state && state !== lastState) window.recordSupportAdoption({ type: 'state', at: Date.now(), text: state });
      if (body && body !== lastBody) window.recordSupportAdoption({ type: 'body', at: Date.now(), text: body });
      lastState = state; lastBody = body;
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
                if (data) window.recordSupportAdoption({ type: 'event', at: Date.now(), event: JSON.parse(data) });
              }
            }
          } catch { /* Observation never reconnects or resends. */ }
        })();
      }
      return response;
    };
  });
}
(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  try {
    for (const group of plan.groups) {
      const row = { id: group.id, turns: [], events: [], checks: [] }; report.groups.push(row);
      let page, active;
      try {
        page = await login(browser, group.customer);
        await page.goto('http://127.0.0.1:5174/#/shop/support');
        await observe(page, value => {
          if (!active) return;
          const record = { ...value, index: active.index, elapsed_ms: value.at - active.started_at };
          row.events.push(record);
          if (value.type === 'state' && active.first_feedback_ms === undefined) active.first_feedback_ms = record.elapsed_ms;
          if (value.type === 'body' && active.first_candidate_ms === undefined) active.first_candidate_ms = record.elapsed_ms;
        });
        await page.locator(`[data-conversation][data-line-id="${group.line_id}"]`).click();
        await page.locator('.support-product').waitFor();
        const base = `/api/v1/support/conversations/${group.conversation_id}`;
        for (const [index, text] of group.turns.entries()) {
          const before = await page.locator('.support-message.assistant:not([data-generation])').count();
          active = { index, text, started_at: Date.now() }; row.turns.push(active);
          await page.getByLabel('咨询消息', { exact: true }).fill(text);
          await page.locator('[data-action=send]').click();
          const deadline = Date.now() + 90000;
          while (Date.now() < deadline) {
            if (await page.locator('.support-message.assistant:not([data-generation])').count() > before) {
              active.completed_ms = Date.now() - active.started_at; break;
            }
            if (await page.locator('.support-agent-state').filter({ hasText: '未能完成' }).count()) break;
            await page.waitForTimeout(100);
          }
          active.conversation = (await api(page, base)).body;
          active.refund = (await api(page, base + '/refund-application')).body;
          save();
          assert(active.completed_ms !== undefined, 'No finalized Agent answer; stop dependent turns');
          if (group.id === 'pause' && index === 0) {
            await page.locator('[data-refund=confirm]').waitFor({ timeout: 10000 });
            active.refund = (await api(page, base + '/refund-application')).body;
            assert(active.refund.draft && !active.refund.application);
          }
          await page.screenshot({ path: `${directory}/${group.id}-${index + 1}.png`, fullPage: true });
          console.log(JSON.stringify({ group: group.id, index, completed_ms: active.completed_ms }));
          active = null;
        }
        const last = row.turns.at(-1);
        if (group.id === 'pause') {
          assert.equal(last.refund.application, null);
          assert.equal(last.refund.draft.status, 'STALE');
          assert.equal(last.refund.draft.reason, row.turns[0].refund.draft.reason);
          assert.equal(await page.locator('[data-refund=confirm]').count(), 0);
          row.checks.push('old reason retained but stale; no directly confirmable draft');
        } else {
          assert.equal(last.refund.application, null);
          assert.equal(last.refund.draft, null);
        }
        if (group.id === 'human') {
          await page.locator('[data-action=preview-handoff]').click();
          const summary = await page.getByLabel('核查摘要', { exact: true }).inputValue();
          assert(summary.trim()); row.handoff_summary = summary;
          await page.locator('[data-share-report]').check();
          await page.locator('.support-preview input[type=checkbox]:not([data-share-report])').first().check();
          await page.locator('[data-action=confirm-handoff]').click();
          await page.locator('.support-ticket').waitFor();
          row.shared_conversation = (await api(page, base)).body;
          const merchant = await login(browser, group.merchant);
          const ticket = await api(merchant, `/api/v1/support/tickets/${row.shared_conversation.ticket.ticket_id}`);
          assert.equal(ticket.status, 200); row.merchant_projection = ticket.body;
          assert.equal(ticket.body.ticket.summary, summary);
          assert.equal(ticket.body.ticket.shared_messages.length, 1);
          assert.equal(ticket.body.ticket.shared_messages[0].text, group.turns[0]);
          assert(ticket.body.ticket.report?.citations.length > 0);
          row.checks.push('confirmed independent human handoff visible to merchant; selected source and raw message only');
        }
        row.success = true;
      } catch (error) {
        row.success = false; row.failure = error.message;
        if (page) await page.screenshot({ path: `${directory}/${group.id}-failure.png`, fullPage: true }).catch(() => {});
      } finally { active = null; if (page) await page.context().close(); save(); }
    }
    report.success = report.groups.every(row => row.success) && report.errors.length === 0;
    if (!report.success) process.exitCode = 1;
  } finally { save(); await browser.close(); }
})();
