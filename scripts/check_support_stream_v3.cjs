// Actual built Vue + browser fetch + local chunked HTTP. Synthetic replies, no model/business service.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const http = require('http');
const assert = require('assert/strict');
const root = path.resolve('web/dist');
const report = 'reports/chat-refund-stream-s3/browser';
const fixture = JSON.parse(fs.readFileSync('contracts/core/fixtures/support.json', 'utf8'));
const conversation = structuredClone(fixture.Conversation);
conversation.store_name = '松间数码'; conversation.ticket = null; conversation.messages = []; conversation.version = 1;
conversation.product = { name: '无线降噪耳机', variant: '黑色', asset_key: 'headphones', quantity: 1, amount_minor: 32900, currency: 'CNY' };
const run = '65000000-0000-4000-8000-000000000001';
let sequence = 0, activeStream;
const errors = [], requests = [], checks = [];
const frame = (kind, payload, attempt = null) => ({ event_id: String(++sequence), conversation_id: conversation.conversation_id,
  run_id: run, input_version: 2, attempt_id: attempt, kind, payload, created_at: '2026-10-23T06:00:00Z' });
function emit(kind, payload, attempt = null) {
  assert(activeStream && !activeStream.destroyed, 'browser must already be subscribed');
  const event = frame(kind, payload, attempt);
  activeStream.write(`id: ${event.event_id}\nevent: ${kind}\ndata: ${JSON.stringify(event)}\n\n`);
}
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost'), route = url.pathname;
  const json = value => { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(value)); };
  if (route.startsWith('/api/')) {
    requests.push({ method: req.method, path: route });
    if (route.endsWith('/events')) {
      assert.equal(req.headers.authorization, 'Bearer browser-synthetic-token');
      activeStream = res;
      res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no' });
      res.write(': connected\n\n');
      const event = { ...frame('stream.snapshot', { conversation, generation: null }), input_version: conversation.version };
      res.write(`id: ${event.event_id}\nevent: stream.snapshot\ndata: ${JSON.stringify(event)}\n\n`);
      return;
    }
    if (route === '/api/v1/auth/login') return json({ access_token: 'browser-synthetic-token', role: 'CUSTOMER', buyer_id: 'B-1', display_name: '买家01', expires_in: 3600 });
    if (route === '/api/v1/shop/stores') return json([]);
    if (route === '/api/v1/support/conversations') return json({ items: [{ ...conversation, messages: [] }], next_before: null });
    if (route.endsWith('/messages') && req.method === 'POST') {
      let body = ''; for await (const chunk of req) body += chunk;
      const input = JSON.parse(body); assert.equal(input.expected_version, 1);
      conversation.version = 2;
      conversation.assistant_turn = { run_id: run, status: 'PENDING', reason: null };
      conversation.messages.push({ message_id: 'question', sequence: 2, author: 'CUSTOMER', recipient: 'ASSISTANT', text: input.text, ticket_id: null, created_at: '2026-10-23T06:00:00Z' });
      return json(conversation);
    }
    if (route === `/api/v1/support/conversations/${conversation.conversation_id}`) return json(conversation);
    if (route === '/api/v1/orders' || route.startsWith('/api/v1/shop/')) return json({ items: [], page: { limit: 20 } });
    res.writeHead(404); return res.end('{}');
  }
  const file = path.resolve(root, '.' + (route === '/' ? '/index.html' : decodeURIComponent(route)));
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) { res.writeHead(404); res.end(); return; }
  const mime = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png' }[path.extname(file)] || 'application/octet-stream';
  res.writeHead(200, { 'Content-Type': mime }); fs.createReadStream(file).pipe(res);
});
(async () => {
  fs.mkdirSync(report, { recursive: true });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/#/login`);
    await page.locator('[name=username]').fill('buyer01'); await page.locator('[name=password]').fill('123456');
    await page.locator('[data-test=login]').click();
    await page.getByRole('link', { name: '售后咨询', exact: true }).click();
    await page.locator('.support-chat-heading').waitFor();
    await page.locator('[aria-label=咨询消息]').fill('显示已签收，但我和家人都没有收到，请帮我查一下。');
    await page.locator('[data-action=send]').click();
    await page.getByText('问题已发送，助手正在处理。', { exact: true }).waitFor();
    emit('turn.started', { status: 'RUNNING' });
    emit('activity.started', { category: 'SHIPMENT' });
    await page.getByText('正在查询物流记录…', { exact: true }).waitFor();
    await page.screenshot({ path: `${report}/01-tool-activity.png`, fullPage: true });
    emit('activity.completed', { category: 'SHIPMENT' });
    emit('answer.started', {}, 'model-3');
    emit('answer.delta', { part_id: 'part-0', offset: 0, text: '我已经读取这笔订单的物流记录。' }, 'model-3');
    await page.locator('[data-generation]').filter({ hasText: '我已经读取这笔订单的物流记录。' }).waitFor();
    assert(!activeStream.writableEnded, 'first body must arrive while HTTP stream is still open');
    checks.push('body visible before HTTP completion');
    await page.screenshot({ path: `${report}/02-streaming-body.png`, fullPage: true });
    emit('answer.reset', {}, 'model-4');
    await page.getByText('正在完善回答…', { exact: false }).waitFor();
    assert(!(await page.locator('.support-messages').innerText()).includes('我已经读取这笔订单的物流记录。'));
    emit('answer.started', {}, 'model-4');
    emit('answer.delta', { part_id: 'part-0', offset: 0, text: '记录显示已签收，但仍需要核验签收凭证。' }, 'model-4');
    await page.locator('[data-generation]').filter({ hasText: '记录显示已签收' }).waitFor();
    await page.screenshot({ path: `${report}/03-repaired-body.png`, fullPage: true });
    checks.push('rejected draft removed and replacement stays in one bubble');
    const text = '物流记录显示已签收，但尚不能确认由你本人签收。你已说明家人没有代收，建议请商家进一步核查签收凭证。';
    emit('answer.committed', { message_id: 'final-answer', sequence: 3, text,
      assistant: { run_id: run, mode: 'mock', citations: [], handoff_summary: null } });
    await page.locator('.support-message.assistant').filter({ hasText: text }).waitFor();
    assert.equal(await page.locator('[data-generation]').count(), 0);
    assert.equal(await page.locator('.support-message.assistant').count(), 1);
    checks.push('single final message replaces provisional view');
    for (const width of [1280, 1440, 1680]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      checks.push(`no horizontal overflow at ${width}`);
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.screenshot({ path: `${report}/04-committed-answer.png`, fullPage: true });
    assert.equal(requests.filter(r => r.method === 'POST' && r.path.endsWith('/messages')).length, 1);
    assert.deepEqual(errors, []);
    fs.writeFileSync(`${report}/result.json`, JSON.stringify({ synthetic: true, real_model_calls: 0,
      scope: 'built Vue + actual local chunked HTTP + Edge; no Java/Agent service', checks, errors, requests }, null, 2) + '\n');
    console.log(JSON.stringify({ checks: checks.length, errors: errors.length, report }));
  } finally {
    await browser.close(); if (activeStream) activeStream.destroy(); server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
