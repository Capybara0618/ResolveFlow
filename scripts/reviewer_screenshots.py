#!/usr/bin/env python
"""Screenshot the real workbench page against a real backend, at named viewports.

Authority: ``tasks/dsh-reviewer/03-readable-sources.md`` section 5 and
``tasks/dsh-reviewer/05-fields-visual.md`` section 5 both ask for screenshots of the **formal
page** driven by the **real API**, not of the design preview and not of a build artefact. This
script is how those are taken: it starts the Vue dev server pointed at whichever gateway it is
told to use, drives a real Chrome over the DevTools protocol, and captures the page after the
data has actually arrived.

Why the DevTools protocol rather than a test browser library: this repository has no browser
automation dependency and the batch instructions forbid adding one for a screenshot. Chrome is
already installed, ``websocket-client`` is already in the Agent's venv, and the protocol calls
used here (navigate, evaluate, emulate, capture) are the four a login-then-open-a-case flow
needs. Nothing about the page is stubbed: the login is a real login against the demo gateway,
and the case is opened through the panel's own lookup field.

Usage::

    agent/.venv/Scripts/python.exe scripts/reviewer_screenshots.py `
        --proxy http://127.0.0.1:8180 --port 5174 `
        --username demo-reviewer --password demo-pass-1003 `
        --case 406a0ef1-1c16-4442-b077-14641c971f65 `
        --viewport 1680x960 --viewport 1440x900 --viewport 390x844 `
        --out reports/reviewer-demo/screenshots --label lost-review
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import websocket  # type: ignore[import-untyped] - no stubs published

ROOT = Path(__file__).resolve().parents[1]
CHROME_CANDIDATES = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)


class ScreenshotRefused(RuntimeError):
    """The capture will not proceed, and says which fact stopped it."""


class DevTools:
    """The smallest DevTools client this job needs: navigate, evaluate, emulate, capture."""

    def __init__(self, websocket_url: str) -> None:
        self._socket = websocket.create_connection(websocket_url, timeout=60)
        self._counter = 0

    def call(self, method: str, **params: object) -> dict:
        self._counter += 1
        identifier = self._counter
        self._socket.send(json.dumps({"id": identifier, "method": method, "params": params}))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            message = json.loads(self._socket.recv())
            if message.get("id") != identifier:
                continue
            if "error" in message:
                raise ScreenshotRefused(f"{method} refused: {message['error']}")
            return message.get("result", {})
        raise ScreenshotRefused(f"{method} produced no answer within 60s")

    def evaluate(self, script: str) -> object:
        result = self.call("Runtime.evaluate", expression=script, returnByValue=True, awaitPromise=True)
        return result.get("result", {}).get("value")

    def close(self) -> None:
        self._socket.close()


def chrome_binary() -> Path:
    from_env = os.environ.get("REVIEWER_DEMO_CHROME")
    if from_env and Path(from_env).is_file():
        return Path(from_env)
    for candidate in CHROME_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise ScreenshotRefused("no Chrome or Edge binary found; set REVIEWER_DEMO_CHROME")


def start_dev_server(port: int, proxy: str, log: Path) -> subprocess.Popen:
    """Vue dev server, pointed at the backend this run names — never at the default silently."""
    handle = log.open("w", encoding="utf-8", errors="replace")
    environment = dict(os.environ)
    environment["VITE_API_PROXY"] = proxy
    environment["VITE_PORT"] = str(port)
    process = subprocess.Popen(  # noqa: S603 - fixed argv built from this repository's paths
        ["cmd", "/c", "pnpm", "--dir", "web", "dev"],
        cwd=str(ROOT),
        env=environment,
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ScreenshotRefused(f"the dev server exited early; see {log}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2):
                return process
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    raise ScreenshotRefused(f"the dev server did not answer on port {port} within 90s")


def start_chrome(profile: Path, debug_port: int) -> subprocess.Popen:
    if profile.exists():
        shutil.rmtree(profile, ignore_errors=True)
    profile.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(  # noqa: S603 - the resolved browser binary
        [
            str(chrome_binary()),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            f"--remote-debugging-port={debug_port}",
            # Chrome rejects a DevTools websocket whose Origin it did not allow; this process is
            # the only client and it talks to its own loopback port.
            "--remote-allow-origins=*",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def target_websocket(debug_port: int) -> str:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{debug_port}/json/list", timeout=2) as response:
                targets = json.loads(response.read().decode("utf-8"))
            page = next((item for item in targets if item.get("type") == "page"), None)
            if page and page.get("webSocketDebuggerUrl"):
                return str(page["webSocketDebuggerUrl"])
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(0.5)
    raise ScreenshotRefused("the browser never exposed a page target")


PAGE_READY = """
(() => {
  const tag = document.querySelector('.demo-tag');
  const ready = !!document.querySelector('[name="username"]') || !!tag;
  return ready;
})()
"""

LOGIN_AND_OPEN = """
(async () => {
  const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
  const setNative = (element, value) => {
    const setter = Object.getOwnPropertyDescriptor(element.constructor.prototype, 'value').set;
    setter.call(element, value);
    element.dispatchEvent(new Event('input', { bubbles: true }));
  };
  const user = document.querySelector('[name="username"]');
  if (user) {
    setNative(user, %s);
    setNative(document.querySelector('[name="password"]'), %s);
    document.querySelector('.login-panel').requestSubmit();
    await sleep(1200);
  }
  const caseId = %s;
  if (caseId) {
    const details = document.querySelector('.lookup-tools');
    if (details && !details.open) details.querySelector('summary').click();
    await sleep(200);
    const field = document.querySelector('[name="case-id"]');
    setNative(field, caseId);
    await sleep(200);
    const buttons = Array.from(document.querySelectorAll('.lookup button'));
    const open = buttons.find(button => button.textContent.includes('查看工单'));
    if (!open) return { ok: false, reason: 'the lookup button is missing' };
    open.click();
  }
  return { ok: true };
})()
"""

WAIT_FOR_PANEL = """
(() => {
  // A reviewer sees the hand-off workspace; a customer never does. Waiting for that one element
  // made every customer capture fail with "the workspace never rendered", which is the harness
  // being wrong about the page rather than the page being wrong.
  const ready = !!document.querySelector('.reviewer-workspace') || !!document.querySelector('.case-title');
  return { ready: ready, status: (document.querySelector('.status-tag') || {}).textContent || '' };
})()
"""


def set_viewport(devtools: DevTools, viewport: tuple[int, int]) -> None:
    """Set the emulated viewport.

    Separate from :func:`capture` because this call re-lays-out the page and **resets its scroll
    position**: applying it after the clicks would capture the top of the document instead of the
    clause a citation just opened.
    """
    width, height = viewport
    devtools.call(
        "Emulation.setDeviceMetricsOverride",
        width=width, height=height, deviceScaleFactor=1, mobile=width < 700,
    )
    time.sleep(0.6)


def capture(devtools: DevTools, viewport: tuple[int, int], path: Path, *, full_page: bool) -> dict:
    time.sleep(0.4)
    params: dict[str, object] = {"format": "png"}
    if full_page:
        params["captureBeyondViewport"] = True
    shot = devtools.call("Page.captureScreenshot", **params)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(shot["data"]))
    layout = devtools.evaluate(
        "JSON.stringify({scrollWidth: document.documentElement.scrollWidth,"
        " clientWidth: document.documentElement.clientWidth,"
        " scrollHeight: document.documentElement.scrollHeight,"
        " title: document.title,"
        " status: (document.querySelector('.status-tag')||{}).textContent||'',"
        " agent: (document.querySelector('[data-test=agent-reading]')||{}).textContent||''})"
    )
    return json.loads(str(layout))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proxy", default="http://127.0.0.1:8180", help="gateway the dev server proxies to")
    parser.add_argument("--port", type=int, default=5174)
    parser.add_argument("--debug-port", type=int, default=9333)
    parser.add_argument("--username", default="demo-reviewer")
    parser.add_argument("--password", default="demo-pass-1003")
    parser.add_argument("--case", default="", help="case id to open through the page's own lookup field")
    parser.add_argument("--viewport", action="append", default=[], help="WxH; repeatable")
    parser.add_argument("--out", default="reports/reviewer-demo/screenshots")
    parser.add_argument("--label", default="case")
    parser.add_argument("--full-page", action="store_true", help="also capture beyond the viewport")
    parser.add_argument("--click", action="append", default=[],
                        help="a CSS selector to click before capturing; repeatable, applied in order")
    parser.add_argument("--scroll-into", default="",
                        help="a CSS selector to scroll into view before capturing")
    args = parser.parse_args()

    viewports = [tuple(int(part) for part in item.lower().split("x")) for item in args.viewport] or [(1680, 960)]
    output = Path(args.out)
    if not output.is_absolute():
        output = ROOT / output
    runtime = ROOT / "tmp" / "reviewer-demo" / "screenshots"
    runtime.mkdir(parents=True, exist_ok=True)

    server = chrome = None
    report: dict[str, object] = {"proxy": args.proxy, "port": args.port, "label": args.label, "captures": []}
    try:
        server = start_dev_server(args.port, args.proxy, runtime / f"dev-server-{args.port}.log")
        chrome = start_chrome(runtime / f"chrome-{args.debug_port}", args.debug_port)
        devtools = DevTools(target_websocket(args.debug_port))
        devtools.call("Page.enable")
        devtools.call("Runtime.enable")
        devtools.call("Page.navigate", url=f"http://127.0.0.1:{args.port}/")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not devtools.evaluate(PAGE_READY):
            time.sleep(0.5)
        opened = devtools.evaluate(
            LOGIN_AND_OPEN % (json.dumps(args.username), json.dumps(args.password), json.dumps(args.case))
        )
        if not isinstance(opened, dict) or not opened.get("ok"):
            raise ScreenshotRefused(f"could not log in and open the case: {opened}")
        deadline = time.monotonic() + 60
        state: dict = {}
        while time.monotonic() < deadline:
            state = devtools.evaluate(WAIT_FOR_PANEL) or {}
            if state.get("ready"):
                break
            time.sleep(0.5)
        if not state.get("ready"):
            raise ScreenshotRefused(f"the reviewer workspace never rendered; last state {state}")
        time.sleep(2.0)  # let the investigation and order requests settle before capturing

        for width, height in viewports:
            # The click sequence runs **after** the viewport is set for every capture, because
            # `Emulation.setDeviceMetricsOverride` re-lays-out the page and resets the scroll
            # position: a click applied once would be captured at the top of the document instead
            # of at the clause it opened.
            set_viewport(devtools, (width, height))
            for selector in args.click:
                clicked = devtools.evaluate(
                    "(() => { const node = document.querySelector(%s);"
                    " if (!node) return false; node.click(); return true; })()" % json.dumps(selector)
                )
                if not clicked:
                    raise ScreenshotRefused(f"nothing matched the selector to click: {selector}")
            if args.scroll_into:
                scrolled = devtools.evaluate(
                    "(() => { const node = document.querySelector(%s);"
                    " if (!node) return false; node.scrollIntoView({ block: 'center' }); return true; })()"
                    % json.dumps(args.scroll_into)
                )
                if not scrolled:
                    raise ScreenshotRefused(f"nothing matched the selector to scroll to: {args.scroll_into}")
                time.sleep(0.5)
            suffix = "" if not args.full_page else "-full"
            name = f"{args.label}-{width}x{height}{suffix}.png"
            layout = capture(devtools, (width, height), output / name, full_page=args.full_page)
            overflow = int(layout["scrollWidth"]) > int(layout["clientWidth"])
            report["captures"].append({"file": name, "viewport": f"{width}x{height}", **layout, "horizontal_overflow": overflow})
            print(f"[shot] {name} status={layout.get('status')!r} overflow={overflow}")
        report["case_id"] = args.case
        report["clicked"] = args.click
        with (output / f"{args.label}-captures.json").open("w", encoding="utf-8", newline="\n") as handle:
            # LF, like every other text file in this repository: a CRLF manifest shows up as
            # "trailing whitespace" on every line of `git diff --check`.
            handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return 0
    finally:
        if chrome is not None:
            chrome.terminate()
        if server is not None:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(server.pid)], capture_output=True, text=True, errors="replace"
            )


if __name__ == "__main__":
    sys.exit(main())
