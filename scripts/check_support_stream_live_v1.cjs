// Real Vue -> Gateway -> Case -> Agent -> DeepSeek. No intercepted or synthetic API responses.
const { chromium } = require('playwright');
const fs = require('fs');
const assert = require('assert/strict');
const directory = process.env.SUPPORT_STREAM_ACCEPTANCE_DIR || 'reports/chat-stream-live-v1';
const plan = JSON.parse(fs.readFileSync(`${directory}/plan.json`, 'utf8'));
const output = `${directory}/browser.json`;
assert(!fs.existsSync(output), 'Do not overwrite an earlier attempt');
const observations = [], writes = [], errors = [], turns = [], httpErrors = [], checks = [];
let active = null;
const save = () => fs.writeFileSync(output, JSON.stringify({ turns, observations, writes, errors, httpErrors, checks }, null, 2) + '\n');
(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    await page.exposeBinding('recordStreamAcceptance', (_, record) => {
      if (!active) return;
      record.turn = active.index;
      record.elapsed_ms = record.at - active.started_at;
      observations.push(record);
      if (record.type === 'body' && active.first_body_ms === undefined) active.first_body_ms = record.elapsed_ms;
      if (record.type === 'state' && active.first_state_ms === undefined) active.first_state_ms = record.elapsed_ms;
    });
    await page.addInitScript(() => {
      let lastBody = '', lastState = '';
      const observe = () => {
        const body = document.querySelector('[data-generation] .support-message-bubble p')?.textContent?.replace(/▍$/, '') || '';
        const state = document.querySelector('.support-agent-state')?.textContent || '';
        if (body && body !== '正在完善回答…' && body !== lastBody) window.recordStreamAcceptance({ type: 'body', at: Date.now(), text: body });
        if (state && state !== lastState) window.recordStreamAcceptance({ type: 'state', at: Date.now(), text: state });
        lastBody = body; lastState = state;
      };
      new MutationObserver(observe).observe(document, { subtree: true, childList: true, characterData: true });
      const original = window.fetch;
      let currentStream;
      window.interruptAcceptanceStream = () => currentStream?.abort();
      window.fetch = async function (...args) {
        const url = typeof args[0] === 'string' ? args[0] : args[0].url;
        if (url?.includes('/events')) {
          currentStream = new AbortController();
          const previous = args[1]?.signal;
          args[1] = { ...args[1], signal: previous ? AbortSignal.any([previous, currentStream.signal]) : currentStream.signal };
        }
        const response = await original.apply(this, args);
        if (response.headers.get('content-type')?.includes('text/event-stream')) {
          window.recordStreamAcceptance({ type: 'connection', at: Date.now() });
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
                  const data = frame.split('\n').find(line => line.startsWith('data:'));
                  if (data) window.recordStreamAcceptance({ type: 'event', at: Date.now(), event: JSON.parse(data.slice(5)) });
                }
              }
            } catch { /* Navigation closes the observation copy, too. */ }
            finally { reader.releaseLock(); }
          })();
        }
        return response;
      };
    });
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {
      const path = new URL(request.url()).pathname;
      if (path.startsWith('/api/') && request.method() !== 'GET') writes.push({ path, method: request.method() });
    });
    page.on('response', response => {
      const path = new URL(response.url()).pathname;
      if (path.startsWith('/api/') && response.status() >= 400) httpErrors.push({ path, status: response.status() });
    });
    await page.goto('http://127.0.0.1:5174/#/login');
    await page.locator('[name=username]').fill('buyer01');
    await page.locator('[name=password]').fill(process.env.RESOLVEFLOW_DEMO_PASSWORD || '123456');
    await page.locator('[data-test=login]').click();
    await page.getByRole('link', { name: '售后咨询', exact: true }).click();
    const select = async () => {
      await page.locator(`[data-conversation][data-line-id="${plan.line_id}"]`).click();
      await page.getByLabel('咨询消息', { exact: true }).waitFor();
      const assistant = page.getByRole('button', { name: '询问智能助手', exact: true });
      if (await assistant.count()) await assistant.click();
    };
    await select();
    if (plan.recovered_answer) {
      assert((await page.locator('.support-messages').innerText()).includes(plan.recovered_answer));
      checks.push('Previous policy answer restored after fresh login; no message resubmitted');
      await page.screenshot({ path: `${directory}/restored-policy.png`, fullPage: true });
    }
    for (const [index, text] of plan.turns.entries()) {
      const count = await page.locator('.support-message.assistant:not([data-generation])').count();
      await page.getByLabel('咨询消息', { exact: true }).fill(text);
      active = { index, text, started_at: Date.now() }; turns.push(active);
      await page.locator('[data-action=send]').click();
      if (index === 1 || plan.reconnect_mode === 'transport-abort') {
        // A real page reload while the saved turn is running; it must only read/reconnect.
        const until = Date.now() + 15000;
        while (!observations.some(o => o.turn === index && o.type === 'event' && o.event.kind === 'turn.started') && Date.now() < until) await page.waitForTimeout(50);
        if (plan.reconnect_mode === 'transport-abort') {
          active.transport_abort_ms = Date.now() - active.started_at;
          await page.evaluate(() => window.interruptAcceptanceStream());
        } else {
          active.reload_at_ms = Date.now() - active.started_at;
          await page.reload(); await select();
        }
      }
      const until = Date.now() + 75000;
      let captured = false;
      while (Date.now() < until) {
        const formal = page.locator('.support-message.assistant:not([data-generation])');
        if (active.first_body_ms !== undefined && !captured) {
          captured = true;
          await page.screenshot({ path: `${directory}/turn-${index + 1}-stream.png`, fullPage: true });
        }
        if (await formal.count() > count) {
          active.completed_ms = Date.now() - active.started_at;
          active.answer = await formal.last().locator('.support-message-bubble p').innerText();
          active.formal_message_delta = await formal.count() - count;
          active.generation_removed = await page.locator('[data-generation]').count() === 0;
          break;
        }
        assert.equal(httpErrors.length, 0, 'HTTP command failed: ' + JSON.stringify(httpErrors));
        await page.waitForTimeout(40);
      }
      active.terminal_visible = active.completed_ms !== undefined;
      await page.screenshot({ path: `${directory}/turn-${index + 1}-final.png`, fullPage: true });
      save();
      assert(active.terminal_visible, `Turn ${index + 1} did not publish within 75 seconds`);
      assert.equal(active.formal_message_delta, 1);
      assert(active.generation_removed);
      console.log(JSON.stringify({ turn: index + 1, first_body_ms: active.first_body_ms, completed_ms: active.completed_ms }));
      active = null;
    }
    assert.equal(writes.filter(w => w.path.endsWith('/messages')).length, plan.turn_limit);
    if (plan.reconnect_mode === 'transport-abort') {
      assert(observations.some(o => o.type === 'connection' && o.elapsed_ms >= turns[0].transport_abort_ms));
      checks.push('Real fetch SSE aborted and reconnected; one user POST and one final message');
    }
    assert.equal(errors.length, 0);
  } catch (error) {
    errors.push(error.message); process.exitCode = 1;
  } finally {
    save(); await browser.close();
  }
})();
