// Actual local UI, explicit scripted model + retained BGE index. Never confirms another ticket.
const { chromium } = require('playwright');
const fs = require('fs');
const base = process.env.SUPPORT_WEB_URL || 'http://127.0.0.1:5174';
const password = process.env.RESOLVEFLOW_DEMO_PASSWORD || '123456';
(async () => {
  const runtime = JSON.parse(fs.readFileSync('reports/customer-agent-v1/runtime-check.json', 'utf8'));
  const samples = JSON.parse(fs.readFileSync('reports/customer-agent-design-v1/runtime-samples.json', 'utf8')).samples;
  const previewLine = samples.find(s => s.name === 'A-DELAYED');
  const browser = await chromium.launch({ headless: true, channel: process.env.CUSTOMER_PREVIEW_BROWSER || 'msedge' });
  const errors = [], checks = [];
  fs.mkdirSync('reports/customer-agent-v1/images', { recursive: true });
  async function login(user) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(base + '/#/login');
    await page.locator('[name="username"]').fill(user); await page.locator('[name="password"]').fill(password);
    await page.locator('[data-test="login"]').click();
    await page.getByRole('button', { name: '退出', exact: false }).waitFor();
    return page;
  }
  async function capture(page, name) {
    await page.evaluate(() => document.fonts.ready);
    for (const width of [1280, 1440, 1680]) {
      await page.setViewportSize({ width, height: 1050 });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
      if (overflow) throw Error(name + ' overflow at ' + width);
      checks.push({ view: name, width, overflow });
    }
    await page.setViewportSize({ width: 1440, height: 1050 });
    await page.screenshot({ path: `reports/customer-agent-v1/images/${name}.png`, fullPage: true });
  }
  async function selectConversation(page, line) {
    await page.locator(`[data-conversation][data-line-id="${line}"]`).click();
    await page.locator('.support-product').waitFor();
    if (!(await page.locator('.support-source').textContent()).includes(line)) throw Error('wrong conversation');
  }
  try {
    const buyer = await login('buyer01');
    await buyer.getByRole('link', { name: '售后咨询', exact: true }).click();
    await selectConversation(buyer, runtime.line_id);
    await buyer.locator('.support-message.assistant').waitFor();
    if (!(await buyer.locator('.support-message.assistant').textContent()).includes('脚本模型演示')) throw Error('mode missing');
    await buyer.locator('.support-message.assistant .support-citations summary').click();
    if (!(await buyer.locator('.support-message.assistant').textContent()).includes('店铺政策')) throw Error('policy missing');
    await capture(buyer, 'buyer-answer');

    // A second pre-existing synthetic line leaves a real unconfirmed preview for demonstration.
    await buyer.getByRole('button', { name: '＋ 选择订单商品', exact: true }).click();
    await buyer.locator(`.support-order[data-line-id="${previewLine.line_id}"] button`).click();
    await buyer.locator('.support-product').waitFor();
    if (!(await buyer.locator('.support-message.assistant').count())) {
      if (await buyer.locator('.support-message.customer').count()) throw Error('unfinished preview: inspect before submitting again');
      await buyer.getByLabel('咨询消息', { exact: true }).fill('请帮我看一下物流和适用政策，先核查运输情况。');
      await buyer.locator('[data-action="send"]').click();
      await buyer.locator('.support-message.assistant').waitFor({ timeout: 60000 });
    }
    await buyer.locator('[data-action="handoff"]').click();
    const summary = buyer.getByLabel('核查摘要', { exact: true });
    if (!(await summary.inputValue()).includes('运输进度')) throw Error('generated summary not adopted');
    if (await buyer.locator('[data-share-report]').isChecked()) throw Error('report shared without opt-in');
    await summary.fill('客户已核对：请商家核查运输进度，暂不退款。');
    await buyer.locator('[data-share-report]').check();
    await buyer.locator('.support-preview .support-citations summary').click();
    await capture(buyer, 'buyer-handoff-preview');
    await buyer.getByRole('button', { name: '返回咨询', exact: true }).click();
    if (await buyer.locator('.support-ticket').count()) throw Error('preview created a ticket');
    checks.push({ interaction: 'editable generated summary, sources opt-in, return without confirmation creates no ticket', passed: true });

    const merchant = await login('admin01');
    await merchant.locator('.nav-link').filter({ hasText: '咨询核查' }).click();
    await selectConversation(merchant, runtime.line_id);
    await merchant.locator('.support-report .support-citations summary').click();
    const detail = await merchant.locator('.support-main').textContent();
    if (!detail.includes('客户确认共享的调查依据') || !detail.includes('店铺政策') || detail.includes('演示私人备注')) throw Error('merchant report projection wrong');
    if (await merchant.locator('.support-message.assistant').count()) throw Error('private assistant message leaked');
    await capture(merchant, 'merchant-report');
    checks.push({ interaction: 'merchant sees confirmed fact/policy report and no private notes', passed: true });
    if (errors.length) throw Error(errors.join('\n'));
    fs.writeFileSync('reports/customer-agent-v1/ui-check.json', JSON.stringify({ model_mode: 'mock', retrieval: 'real local dense', checks, page_errors: errors, screenshot_count: 3 }, null, 2) + '\n');
    console.log(JSON.stringify({ checks: checks.length, screenshots: 3, errors: errors.length }));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
