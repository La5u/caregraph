"""Offline browser checks of site/dist; run ONLY under the requested memory cap:
  systemd-run --user --scope -p MemoryMax=1500M -p MemorySwapMax=0 /usr/bin/python3 -P scripts/site_smoke.py
No third-party requests are allowed. Chromium is always headless and must use a real GPU.
"""
import functools
import gzip
import http.server
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlparse

from playwright.sync_api import sync_playwright

dist = Path(__file__).resolve().parent.parent / "site" / "dist"
ids = [int(a) for a in sys.argv[1:]] or [1, 2, 50, 500]
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(dist))
http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_port}/index.html"
OVERLAPS = """() => { const ns = network.nodes.filter(n => !n.hidden); let o = 0;
  for (let i = 0; i < ns.length; i++) for (let j = i + 1; j < ns.length; j++) {
    const a = ns[i], b = ns[j]; if (Math.hypot(a.x - b.x, a.y - b.y) < (a.size || 7) + (b.size || 7) - 0.5) o++; }
  return {visible: ns.length, overlaps: o}; }"""

def wait_table(page):
    page.wait_for_selector("#table-results tbody tr", timeout=30000)
    page.wait_for_function("() => !document.getElementById('table-statusline').textContent.includes('Loading')")


def wait_panel(page):
    page.wait_for_function("() => !/Loading source records|Could not load source records/.test(document.getElementById('infobody').textContent) && document.querySelector('#side.detail')", timeout=30000)


def payload_report(paths):
    raw_total = packed_total = 0
    codec = "brotli" if shutil.which("brotli") else "gzip"
    for name in sorted(paths):
        raw = (dist / name).read_bytes()
        packed = subprocess.run(["brotli", "-c"], input=raw, capture_output=True, check=True).stdout if codec == "brotli" else gzip.compress(raw)
        raw_total += len(raw); packed_total += len(packed)
        print(f"  {name}: {len(raw):,} raw / {len(packed):,} {codec} bytes")
    print(f"Default payload: {raw_total:,} raw / {packed_total:,} {codec} bytes")
    assert packed_total <= 500_000, "Default page exceeds 500 KB compressed"


try:
    with sync_playwright() as p:
        exe = shutil.which("chromium-browser") or shutil.which("chromium")
        browser = p.chromium.launch(executable_path=exe, headless=True,
            args=["--mute-audio", "--enable-gpu", "--use-angle=gl-egl", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1400, "height": 900}, accept_downloads=True)
        errors, external, requests = [], [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        def local_only(route):
            url = urlparse(route.request.url)
            if url.scheme in ("http", "https") and url.hostname != "127.0.0.1":
                external.append(route.request.url); route.abort()
            else: route.continue_()
        page.route("**/*", local_only)
        page.on("request", lambda request: requests.append(urlparse(request.url).path))
        page.goto(base)
        wait_table(page)
        assert page.locator("body").get_attribute("data-section") == "agencies"
        assert page.locator("#table-results tbody > tr").count() <= 100
        initial = {"index.html"} | {p.lstrip("/") for p in requests if p.endswith((".json", ".js"))}
        assert all(re.search(r"/[a-f0-9]{20}/", p) for p in requests if p.endswith(".json"))
        assert not any(re.search(r"/(index|agencies|search|path-names|path-edges)\.json$|/g/|/r/", p) for p in requests), requests
        payload_report(initial)
        # Shareable filters, a complete CSV (not just the visible page), table back navigation.
        page.goto(base + "#/agencies?state=CA&q=care")
        wait_table(page)
        assert page.locator("#table-state").input_value() == "CA"
        assert page.locator("#table-q").input_value() == "care"
        assert page.evaluate("() => tableFiltered.every(n => n.state === 'CA')")
        with page.expect_download() as download:
            page.click("#table-csv")
        assert download.value.suggested_filename == "caregraph-agencies.csv"
        origin = page.evaluate("location.hash")
        page.locator("[data-open-agency]").first.click()
        page.wait_for_function("() => G && network && network.nodes.some(n => n.highlighted)")
        wait_panel(page)
        assert all(page.locator("#infobody").get_by_text(s, exact=True).count() for s in ("Summary", "Timeline", "Sources"))
        page.click("#tableback"); wait_table(page)
        assert page.evaluate("location.hash") == origin
        page.goto(base + "#/addresses"); wait_table(page)
        page.locator("[data-address]").first.click()
        page.wait_for_selector("[data-address-detail] [data-open-agency]")
        page.goto(base + "#/changes"); wait_table(page)
        assert page.get_by_text("A change between files may be a filing correction.", exact=True).count()
        with page.expect_download() as download:
            page.click("#table-csv")
        assert download.value.suggested_filename == "caregraph-changes.csv"
        print("tables, filters, CSV, address expansion and table back: OK")
        # Network rendering and deferred row URLs. No records requested just to draw a graph.
        for gid in ids:
            page.goto("about:blank"); requests.clear()
            t0 = time.time(); page.goto(f"{base}#{gid}")
            page.wait_for_function("gid => current === gid && G && network && network.nodes.length > 0", arg=gid, timeout=30000)
            assert not any("/r/" in path for path in requests)
            renderer = page.evaluate("""() => { const gl = network.gl, ext = gl.getExtension('WEBGL_debug_renderer_info');
              return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER); }""")
            assert not any(token in renderer.lower() for token in ("swiftshader", "llvmpipe", "softpipe", "software rasterizer")), renderer
            assert renderer and renderer != "WebKit WebGL", "Cannot verify real GPU renderer"
            ov = page.evaluate(OVERLAPS)
            assert ov["overlaps"] == 0, (gid, ov)
            page.evaluate("() => select(network.nodes.find(n => !n.hidden && isEnr(n)))")
            wait_panel(page)
            node_sources = page.locator('#infobody a[href^="http"]').count()
            assert node_sources > 0
            page.evaluate("() => select(null, network.edges.find(e => !e.hidden))")
            wait_panel(page)
            edge_sources = page.locator('#infobody a[href*="data-api"]').count()
            assert edge_sources > 0
            print(f"#{gid}: {ov['visible']} dots, no overlaps; {node_sources} node / {edge_sources} edge sources; {time.time() - t0:.2f}s; GPU {renderer}")
        # A hidden officer / one-link node must be revealed by a deep link.
        node = page.evaluate("() => network.nodes.find(n => n.hidden)?.id || network.nodes.find(n => n.kind === 'person').id")
        page.goto("about:blank"); page.goto(f"{base}#{ids[-1]}/{quote(node, safe='')}")
        page.wait_for_function("id => network && network.nodes.some(n => n.id === id && n.highlighted && !n.hidden)", arg=node)
        wait_panel(page)
        assert not page.locator("#legendwrap").evaluate("el => el.open")
        assert not page.locator("#advanced").evaluate("el => el.open")
        # Fail a record download once, then use the visible Retry.
        page.goto("about:blank")
        page.route("**/r/*.json", lambda r: r.fulfill(status=503, body="unavailable"))
        page.goto(f"{base}#{ids[-1]}/{quote(node, safe='')}")
        page.wait_for_selector("#recordretry")
        assert page.locator('#infobody a[href*="data-api"]').count() == 0
        page.unroute("**/r/*.json")
        page.click("#recordretry"); wait_panel(page)
        # Hold search until the box has a query: no premature no-match result.
        page.goto("about:blank")
        page.route("**/search.json", lambda r: r.fulfill(status=503, body="unavailable"))
        page.goto(base + "#/networks")
        page.wait_for_selector(".grp")
        page.fill("#q", "care")
        page.wait_for_selector("#searchretry")
        page.unroute("**/search.json"); page.click("#searchretry")
        page.wait_for_function("() => searchData && !document.getElementById('list').textContent.includes('Loading search')")
        # Path names load on the first keystroke; the edges wait until Find.
        page.goto("about:blank"); requests.clear(); page.goto(base + "#/networks")
        page.wait_for_selector(".grp"); page.locator("#connection summary").click()
        page.fill("#pathfrom", "c")
        page.wait_for_function("() => !!pathsData")
        assert not any("path-edges.json" in path for path in requests)
        page.click("#pathfind")
        page.wait_for_function("() => pathsData && !!pathsData.edges")
        print("hidden-node deep links, deferred records/search/path data and retry: OK")
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(base + "#/agencies"); wait_table(page)
        page.locator("[data-open-agency]").first.click()
        page.wait_for_function("() => G && network && network.nodes.some(n => n.highlighted)")
        wait_panel(page)
        assert page.locator("#tableback").is_visible()
        page.click("#tableback"); wait_table(page)
        assert page.locator("#tableview").is_visible()
        page.goto(base + "#/networks"); page.wait_for_selector(".grp")
        page.locator(".grp").first.focus(); page.keyboard.press("Enter")
        page.wait_for_function("() => G && document.body.dataset.view === 'map'")
        assert page.locator("#fit").is_visible()
        print("phone tables, back navigation and keyboard network access: OK")
        assert not external, external
        assert not errors, errors
        browser.close()
        print("site_smoke: passed")
finally:
    server.shutdown()
