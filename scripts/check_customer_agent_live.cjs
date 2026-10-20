// Actual Vue -> Gateway -> retained backend. No API interception, no model requests.
const { chromium } = require('playwright');
const fs = require('fs');
const crypto = require('crypto');
const base = 'http://127.0.0.1:5174';
const root = 'reports/customer-agent-live-v1';
const runtime = JSON.parse(fs.readFileSync(`${root}/runtime-results.json`, 'utf8'));
const plan = JSON.parse(fs.readFileSync('evals/customer-agent-live-v1/cases.json', 'utf8'));
const checks = [], errors = [], writes = [], httpErrors = [], images = [];
function assert(value, message) { if (!value) throw Error(message); }
async function login(browser, user) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { const path = new URL(request.url()).pathname; if (path.startsWith('/api/') && request.method() !== 'GET') writes.push({ method: request.method(), path }); });
  page.on('response', response => { if (response.url().includes('/api/') && response.status() >= 400) httpErrors.push({ path: new URL(response.url()).pathname, status: response.status() }); });
  await page.goto(base + '/#/login');
  await page.locator('[name="username"]').fill(user);
  await page.locator('[name="password"]').fill(process.env.RESOLVEFLOW_DEMO_PASSWORD || '123456');
  await page.locator('[data-test="login"]').click();
  if (user === 'buyer01') await page.getByRole('link', { name: '售后咨询', exact: true }).click();
  else await page.locator('.nav-link').filter({ hasText: '咨询核查' }).click();
  await page.locator('.support-chat-heading').waitFor();
  return page;
}
async function select(page, turn) {
  await page.locator(`[data-conversation][data-line-id="${turn.line_id}"]`).click();
  await page.locator('.support-product').waitFor();
  assert((await page.locator('.support-source').textContent()).includes(turn.line_id), 'Wrong bound order');
}
async function capture(page, name) {
  for (const [width, height] of [[1280, 800], [1440, 900]]) {
    await page.setViewportSize({ width, height });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const view = await page.evaluate(() => ({ horizontal: document.documentElement.scrollWidth > innerWidth + 1, outerScroll: document.documentElement.scrollHeight > innerHeight + 2, composerBottom: document.querySelector('.support-compose').getBoundingClientRect().bottom }));
    assert(!view.horizontal && !view.outerScroll && view.composerBottom <= height + 1, 'Actual content overflow: ' + name);
    checks.push({ view: name, width, height, ...view, passed: true });
  }
  await page.evaluate(() => document.fonts.ready);
  const path = `${root}/images/${name}.png`;
  await page.screenshot({ path, fullPage: true });
  images.push({ path: `images/${name}.png`, sha256: crypto.createHash('sha256').update(fs.readFileSync(path)).digest('hex') });
}
(async () => {
  fs.mkdirSync(`${root}/images`, { recursive: true });
  const browser = await chromium.launch({ headless: true, channel: process.env.CUSTOMER_PREVIEW_BROWSER || 'msedge' });
  try {
    const buyer = await login(browser, 'buyer01');
    for (const id of ['L01', 'L03', 'L07', 'L08']) {
      const turn = runtime.turns.find(t => t.id === id);
      assert(turn.answer, 'Actual turn failed: ' + id);
      await select(buyer, turn);
      const message = buyer.locator('.support-message.assistant').filter({ hasText: turn.answer.text.slice(0, 35) });
      await message.waitFor();
      assert((await message.textContent()).includes('智能回答'), 'Not a live answer');
      if (id === 'L03') {
        const source = message.locator('.support-citation').filter({ hasText: '店铺政策' }).first();
        await source.locator('summary').click();
        assert(await source.locator('.source-body').isVisible(), 'Actual policy cannot expand');
        assert((await source.textContent()).includes('版本'), 'Policy version missing');
        checks.push({ interaction: 'actual policy source expands with original and version', passed: true });
      }
      await message.scrollIntoViewIfNeeded();
      await capture(buyer, `buyer-${id.toLowerCase()}`);
    }
    const a = runtime.turns.find(t => t.id === 'L04'), b = runtime.turns.find(t => t.id === 'L06');
    await select(buyer, a);
    await buyer.getByRole('button', { name: '＋ 选择订单', exact: false }).click();
    await buyer.locator(`.support-order[data-line-id="${b.line_id}"]`).click();
    await buyer.locator('.support-product').waitFor();
    assert((await buyer.locator('.support-source').textContent()).includes(b.line_id), 'Order switch not bound to B');
    assert(!(await buyer.locator('.support-main').textContent()).includes(a.text), 'A private text appeared in B');
    await select(buyer, a);
    assert((await buyer.locator('.support-main').textContent()).includes(a.text), 'A history lost after switch');
    checks.push({ interaction: 'real order picker switches tenant context and restores prior history', passed: true });
    const merchant = await login(browser, 'admin01');
    const human = runtime.turns.find(t => t.id === plan.human_followup.case);
    await select(merchant, human);
    const text = await merchant.locator('.support-main').textContent();
    assert(text.includes(plan.human_followup.customer_answer) && text.includes(plan.human_followup.merchant_reply), 'Actual human followup missing');
    assert(!(await merchant.locator('.support-message.assistant').count()), 'Private assistant messages visible');
    assert(await merchant.getByLabel('咨询消息', { exact: true }).isDisabled(), 'Resolved ticket can still reply');
    const expectedPrivate = runtime.turns.filter(t => t.id !== human.id).map(t => t.text);
    assert(expectedPrivate.every(t => !text.includes(t)), 'Other private conversation shown');
    await capture(merchant, 'merchant-followup');
    checks.push({ interaction: 'confirmed report and real human replies visible; private assistant absent; resolved composer disabled', passed: true });
    assert(!errors.length && !httpErrors.length, JSON.stringify({ errors, httpErrors }));
    assert(writes.every(w => w.path.endsWith('/auth/login') || w.path === '/api/v1/support/conversations'), 'Unexpected business write');
    fs.writeFileSync(`${root}/ui-check.json`, JSON.stringify({ real_api: true, api_interception: false, model_requests_from_ui_check: 0, checks, images, page_errors: errors, http_errors: httpErrors, writes }, null, 2) + '\n');
    console.log(JSON.stringify({ passed: checks.length, images: images.length, page_errors: errors.length, model_calls: 0 }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
