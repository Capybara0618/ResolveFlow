// Requires the explicitly started local verification stack and synthetic acceptance records.
const { chromium } = require('playwright');
const fs = require('fs');
const base = process.env.SUPPORT_WEB_URL || 'http://127.0.0.1:5174';
const password = process.env.RESOLVEFLOW_DEMO_PASSWORD || '123456';
(async () => {
  const runtime = JSON.parse(fs.readFileSync('reports/customer-support-v1/runtime-check.json', 'utf8'));
  const browser = await chromium.launch({ headless: true, channel: process.env.CUSTOMER_PREVIEW_BROWSER || 'msedge' });
  const errors = [], checks = [];
  fs.mkdirSync('reports/customer-support-v1/images', { recursive: true });
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
    await page.screenshot({ path: `reports/customer-support-v1/images/${name}.png`, fullPage: true });
  }
  try {
    const buyer = await login('buyer01');
    await buyer.getByRole('link', { name: '售后咨询', exact: true }).click();
    await buyer.getByRole('heading', { name: '选择需要咨询的商品', exact: true }).waitFor();
    await buyer.locator('.support-order').first().waitFor();
    await capture(buyer, 'buyer-select');
    await buyer.locator('[data-conversation]').filter({ hasText: '无线降噪耳机' }).click();
    await buyer.locator('.support-product').waitFor();
    if (!(await buyer.locator('.support-source').textContent()).includes(runtime.conversation_a) && !(await buyer.locator('.support-source').textContent()).includes(runtime.ticket_id)) throw Error('wrong buyer consultation');
    if (!(await buyer.locator('.support-main').textContent()).includes('演示个人备注')) throw Error('buyer cannot see own private note');
    await capture(buyer, 'buyer-conversation');
    await buyer.locator('[data-conversation]').filter({ hasText: '桌面台灯' }).click();
    await buyer.locator('.support-product').filter({ hasText: '桌面台灯' }).waitFor();
    if ((await buyer.locator('.support-main').textContent()).includes('演示个人备注')) throw Error('A note leaked into B');
    await buyer.locator('[data-action="handoff"]').click();
    await buyer.getByLabel('核查摘要', { exact: true }).fill('只核查台灯物流，不申请退款。');
    if (await buyer.locator('.support-preview input[type="checkbox"]').first().evaluate(el => el.getBoundingClientRect().width > 24)) throw Error('checkbox stretched by global styles');
    if (await buyer.locator('[data-action="confirm-handoff"]').evaluate(el => getComputedStyle(el).backgroundColor !== 'rgb(22, 93, 255)')) throw Error('primary action style overridden');
    await capture(buyer, 'buyer-handoff');
    const merchant = await login('admin01');
    await merchant.locator('.nav-link').filter({ hasText: '咨询核查' }).click();
    await merchant.locator('[data-conversation]').first().click();
    await merchant.locator('.support-product').waitFor();
    if (await merchant.locator('[data-conversation]').first().evaluate(el => getComputedStyle(el).display !== 'block')) throw Error('history laid out as a row');
    const detail = await merchant.locator('.support-main').textContent();
    if (!detail.includes('核查补充3') || !detail.includes('家人和代收点') || detail.includes('演示个人备注') || detail.includes('这条个人补充')) throw Error('incorrect shared scope');
    await capture(merchant, 'merchant-ticket');
    if (errors.length) throw Error(errors.join('\n'));
    fs.writeFileSync('reports/customer-support-v1/browser-check.json', JSON.stringify({ real_backend: true, synthetic: true, model_calls: 0, checks, interactions: ['buyer selects actual order line', 'own private note visible', 'B context independent', 'handoff preview without submit', 'merchant receives shared originals and supplements only'], style_checks: ['bounded checkbox width', 'visible primary action', 'stacked history text'], browser_errors: errors }, null, 2) + '\n');
    console.log('12 desktop viewport checks; real buyer/merchant projections and handoff preview passed; 4 screenshots');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
