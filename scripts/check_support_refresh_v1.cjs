// Read-only real-system reload check. Only login is POSTed; never sends a consultation.
const { chromium } = require('playwright');
const fs = require('fs');
const crypto = require('crypto');
const assert = require('assert/strict');
const directory = 'reports/chat-refresh-v1';
const line = JSON.parse(fs.readFileSync('reports/chat-stream-live-v3/plan.json', 'utf8')).line_id;
const output = `${directory}/browser.json`;
assert(!fs.existsSync(output)); fs.mkdirSync(directory, { recursive: true });
const writes = [], events = [], errors = [], checks = [];
(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {
      const path = new URL(request.url()).pathname;
      if (!path.startsWith('/api/')) return;
      if (request.method() !== 'GET') writes.push({ path, method: request.method() });
      if (path.endsWith('/events')) events.push(path);
    });
    await page.goto('http://127.0.0.1:5174/#/login');
    await page.locator('[name=username]').fill('buyer01');
    await page.locator('[name=password]').fill(process.env.RESOLVEFLOW_DEMO_PASSWORD || '123456');
    await page.locator('[data-test=login]').click();
    await page.getByRole('link', { name: '售后咨询', exact: true }).click();
    await page.locator(`[data-conversation][data-line-id="${line}"]`).click();
    await page.locator(`[data-line-id="${line}"][aria-current=true]`).waitFor();
    const before = await page.locator('.support-messages').innerText();
    const route = page.url();
    await page.reload();
    await page.locator(`[data-line-id="${line}"][aria-current=true]`).waitFor();
    assert.equal(page.url(), route);
    assert.equal(await page.locator('.support-messages').innerText(), before);
    assert.equal(writes.length, 1);
    assert(writes[0].path.endsWith('/auth/login'));
    assert(events.length >= 2);
    assert.equal(await page.locator('.login-panel').count(), 0);
    checks.push('Reload retains buyer, current consultation, messages and route; reads/SSE only');
    await page.screenshot({ path: `${directory}/restored.png`, fullPage: true });
    await page.locator('.logout-button').click();
    await page.reload();
    await page.locator('.login-panel').waitFor();
    assert.equal(await page.locator('[data-conversation]').count(), 0);
    checks.push('Explicit logout remains logged out after reload');
    assert.equal(errors.length, 0);
  } catch (error) { errors.push(error.message); process.exitCode = 1; }
  finally {
    const files = ['web/src/tab-session.ts', 'web/src/App.vue', 'web/src/ui/SupportWorkspace.vue', 'scripts/check_support_refresh_v1.cjs'];
    fs.writeFileSync(output, JSON.stringify({ synthetic_business_data: true, new_consultations: 0,
      checks, writes, event_connections: events.length, errors,
      files: Object.fromEntries(files.map(path => [path, crypto.createHash('sha256').update(fs.readFileSync(path)).digest('hex')])) }, null, 2) + '\n');
    await browser.close();
  }
})();
