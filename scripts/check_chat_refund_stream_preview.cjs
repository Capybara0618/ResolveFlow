/* Local prototype QA. No model, network, project startup or real application creation. */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');

(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  try {
    const errors = [];
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
    page.on('pageerror', e => errors.push(e.message));
    const base = pathToFileURL(path.resolve('docs/ui-chat-refund-stream-v1/index.html')).href;
    const directory = 'docs/ui-chat-refund-stream-v1/images';
    fs.mkdirSync(directory, { recursive: true });
    const checks = [];
    for (const width of [1440, 1280, 1680]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const state of ['stream', 'confirm', 'progress', 'merchant']) {
        await page.goto(base + '#' + state);
        await page.locator(`[data-screen="${state}"][aria-selected="true"]`).waitFor();
        await page.evaluate(() => document.fonts.ready);
        await page.waitForTimeout(200); // Allow the prototype's CSS tab transition and scroll positioning to paint.
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
        if (overflow) throw new Error('horizontal overflow: ' + state + '/' + width);
        if (width === 1440) await page.screenshot({ path: `${directory}/${state}.png`, fullPage: true });
        checks.push({ state, width, no_horizontal_overflow: true });
      }
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(base + '#confirm');
    await page.locator('#editReason').click();
    await page.locator('#reasonEditor').fill('家人和门卫均未代收，请核实签收后处理退款申请。');
    await page.locator('#saveReason').click();
    if (!(await page.locator('#reasonText').innerText()).includes('请核实签收')) throw Error('edit not saved');
    await page.locator('#cancelApply').click();
    if (await page.locator('#progressCard').isVisible()) throw Error('cancel creates application');
    await page.locator('[data-screen="confirm"]').click();
    if (!(await page.locator('#reasonText').innerText()).includes('请核实签收')) throw Error('cancel lost reason');
    await page.locator('#confirmApply').click();
    await page.locator('#progressCard:not([hidden])').waitFor();
    if (!(await page.locator('#progressBadge').innerText()).includes('核查')) throw Error('wrong initial progress');
    await page.locator('#statusDemo').selectOption('unknown');
    if ((await page.locator('#progressTitle').innerText()).includes('已完成')) throw Error('unknown became success');
    await page.screenshot({ path: `${directory}/result-pending.png`, fullPage: true });
    await page.locator('#statusDemo').selectOption('success');
    if (!(await page.locator('#progressTitle').innerText()).includes('模拟退款已完成')) throw Error('success missing');
    await page.locator('[data-screen="stream"]').click();
    await page.locator('#replay').click();
    await page.waitForFunction(() => document.getElementById('answerText').textContent.length > 4);
    if (await page.locator('#refundCard').isVisible()) throw Error('card visible before completion');
    await page.locator('#refundCard:not([hidden])').waitFor();
    await page.locator('#viewSource').click();
    await page.locator('#sourceDialog[open]').waitFor();
    await page.locator('#closeSource').click();
    await page.locator('[data-screen="merchant"]').click();
    if (await page.locator('#refundCard').isVisible()) throw Error('merchant sees draft card');
    if (!(await page.locator('#merchantIntro').innerText()).includes('客户确认')) throw Error('merchant scope unclear');
    if (errors.length) throw Error(errors.join('\n'));
    const output = { prototype_only: true, live_calls: 0, business_writes: 0, layouts: checks,
      interaction_checks: ['edit summary', 'cancel does not create', 'cancel preserves edit',
        'confirm switches to same application', 'unknown differs from success', 'success explicitly simulated',
        'stream animation precedes card', 'policy dialog', 'merchant no draft'],
      browser_errors: errors };
    fs.mkdirSync('reports/chat-refund-stream-design-v1', { recursive: true });
    fs.writeFileSync('reports/chat-refund-stream-design-v1/preview-check.json', JSON.stringify(output, null, 2) + '\n');
    console.log('12 layout checks, 9 interactions, 5 screenshots passed; prototype only');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
