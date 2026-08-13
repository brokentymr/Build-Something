"""Document engine — Part 5.2.

HTML with inline SVG, rendered to PDF by headless Chromium. Two-pass layout is
*mandatory infrastructure*, not an optimisation (Lesson 5):

* **Pass 1** renders every block into a measurement harness at exact print width
  and records its rendered height (via Chromium — never estimated).
* **Pass 2** packs blocks into fixed-height pages against the measured heights.

Packer rules (Part 5.2): never end a page on a section header; never split a step
block; capacity is set below raw content height to absorb header and
margin-collapse variance. Page total is resolved **after** pagination.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile

from .content import Block, REVISION
from ..core.model import Geometry
from ..nesting.plan import NestingPlan

CHROME = os.environ.get(
    "CHROME_BIN", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
)

# Letter @ 96dpi.
PAGE_W = 816
PAGE_H = 1056
MARGIN = 40
FOOTER_H = 28
CONTENT_W = PAGE_W - 2 * MARGIN               # 736 — body pinned to printable area
# What a page actually gives a block, measured in the browser rather than derived
# on paper: the run-head and the footer are flex children of the page, so they eat
# their own height before .content gets any. The old arithmetic here read 948 and
# was wrong by 41px, which made every capacity argument built on it wrong too.
AVAILABLE = 907
# Pack close to that, then check. The margin below AVAILABLE is insurance against
# a Gate 2 failure, which blocks release outright — so rather than pick a buffer
# and hope, verified_pages packs tight and re-packs looser only when a rendered
# page genuinely overflows. A guess becomes a measurement.
CAPACITY = 900
CAPACITY_FLOOR = 830                           # give up tightening below this
CAPACITY_STEP = 22

CSS = f"""
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: "Helvetica Neue", Arial, sans-serif; color: #17150f;
  -webkit-font-smoothing: antialiased; }}
.page {{
  width: {PAGE_W}px; height: {PAGE_H}px; padding: {MARGIN}px {MARGIN}px {int(FOOTER_H)+18}px;
  display: flex; flex-direction: column; overflow: hidden;
  page-break-after: always; position: relative; background: #fff;
}}
.content {{ flex: 1; overflow: hidden; }}
/* running header band on interior pages */
.runhead {{ display:flex; justify-content:space-between; font-family:"SF Mono",Menlo,monospace;
  font-size:8.5px; letter-spacing:1.2px; color:#9a948a; text-transform:uppercase;
  padding-bottom:8px; margin-bottom:16px; border-bottom:1px solid #ece7dd; }}
.footer {{ margin-top: auto; height: {FOOTER_H}px; border-top: 2px solid #17150f;
  font-family:"SF Mono",Menlo,monospace; font-size: 9px; letter-spacing:1px; color: #b3ada2;
  text-transform:uppercase; display: flex; justify-content: space-between;
  align-items: flex-end; padding-top: 7px; }}

/* editorial type */
h1.doctitle {{ font-size: 44px; line-height:1.02; letter-spacing:-1px; margin: 4px 0 10px;
  font-weight:800; }}
.subtitle {{ color: #4a463d; font-size: 13.5px; line-height:1.55; margin-bottom: 14px; max-width:62%; }}
h2.section {{ font-size: 19px; letter-spacing:-0.3px; font-weight:800; margin: 4px 0 12px;
  padding-bottom:8px; border-bottom:2px solid #17150f; display:flex;
  justify-content:space-between; align-items:baseline; }}
h2.section .kicker {{ font-family:"SF Mono",Menlo,monospace; font-size:9.5px; letter-spacing:1.5px;
  color:#a4632e; font-weight:600; text-transform:uppercase; }}
p {{ font-size: 12px; line-height: 1.62; margin: 7px 0; color:#2c281f; }}
b {{ color:#17150f; }}

/* tables — mono uppercase headers, hairline rules */
table.grid {{ width: 100%; border-collapse: collapse; font-size: 11px; margin: 8px 0 4px; }}
table.grid th {{ text-align: left; padding: 6px 8px; font-family:"SF Mono",Menlo,monospace;
  font-size:8.5px; letter-spacing:1px; text-transform:uppercase; color:#8b857a;
  border-bottom:1.5px solid #17150f; }}
table.grid td {{ border-bottom: 1px solid #ece7dd; padding: 6px 8px; vertical-align: top; }}
table.grid td.cb {{ text-align: center; width: 20px; }}
table.grid tr:last-child td {{ border-bottom:none; }}
table.grid.strong td:last-child {{ font-weight:700; }}
.nowrap {{ white-space: nowrap; }}

/* figures */
.fig {{ border: 1px solid #ece7dd; border-radius: 3px; padding: 14px; margin: 10px 0;
  background:#fcfbf8; }}
.figcap {{ font-family:"SF Mono",Menlo,monospace; font-size: 8.5px; letter-spacing:.8px;
  color: #a29b8f; margin-top: 8px; text-transform:uppercase; }}
.figcap .stage {{ color:#17150f; font-weight:bold; }}

/* build steps */
.step {{ border-top: 1.5px solid #17150f; padding: 10px 0 12px; margin: 0; }}
.stephead {{ display: flex; align-items: baseline; gap: 10px; }}
.stepn {{ font-family:"SF Mono",Menlo,monospace; font-size:22px; font-weight:800; color:#d8d1c4;
  line-height:1; flex:0 0 auto; min-width:30px; }}
.stepphase {{ font-family:"SF Mono",Menlo,monospace; font-size:8px; text-transform:uppercase;
  letter-spacing:1px; color:#a4632e; }}
.steptitle {{ font-weight:800; font-size:14px; letter-spacing:-0.2px; }}
.stepdetail {{ font-size:11.5px; margin:6px 0 6px 40px; line-height:1.55; color:#2c281f; }}
.chips {{ margin: 4px 0 4px 40px; }}
.chip {{ display:inline-block; font-family:"SF Mono",Menlo,monospace; font-size:8.5px;
  padding:3px 8px; margin:2px 4px 2px 0; border-radius:2px; letter-spacing:.4px;
  text-transform:uppercase; }}
.chip.tool {{ background:#eef2f6; color:#3a5a78; }}
.chip.mat {{ background:#eef3e9; color:#4a6b3a; }}
.chip.fast {{ background:#f6ede6; color:#8a5a34; }}
.steptol {{ font-size:10.5px; color:#4a463d; margin-left:40px; }}
.stepsign {{ font-size:10.5px; margin:5px 0 0 40px; color:#6a655b; }}
.stepsign .ts {{ float:right; color:#c3bdb2; font-family:"SF Mono",Menlo,monospace; }}

/* cover */
.cover .revtag {{ position:absolute; top:{MARGIN}px; right:{MARGIN}px;
  font-family:"SF Mono",Menlo,monospace; font-size:9px; letter-spacing:1.5px; color:#8b857a;
  text-transform:uppercase; }}
/* the rule clears the revision tag rather than striking through it */
.cover .toprule {{ border-top:5px solid #17150f; margin-top:16px; margin-bottom:22px; }}
.cover .eyebrow {{ font-family:"SF Mono",Menlo,monospace; font-size:10px; letter-spacing:3px;
  color:#8b857a; text-transform:uppercase; margin-bottom:6px; }}
.coverwrap {{ display:flex; gap:24px; }}
.cover .lead {{ flex:1; }}
/* spec chips column */
.specchips {{ width:210px; flex:0 0 auto; }}
.specchips .row {{ display:flex; justify-content:space-between; gap:10px; padding:7px 0;
  border-bottom:1px solid #ece7dd; }}
.specchips .k {{ font-family:"SF Mono",Menlo,monospace; font-size:8.5px; letter-spacing:1px;
  color:#a29b8f; text-transform:uppercase; padding-top:2px; }}
.specchips .v {{ font-family:"SF Mono",Menlo,monospace; font-size:11px; font-weight:600;
  text-align:right; color:#17150f; }}
.specsummary {{ display:grid; grid-template-columns:1fr 1fr; gap:6px 24px; margin:12px 0; }}
.specsummary .k {{ color:#a29b8f; font-size:10px; font-family:"SF Mono",Menlo,monospace;
  letter-spacing:.5px; text-transform:uppercase; display:inline-block; width:96px; }}
.specsummary .v {{ font-weight:700; font-size:12.5px; }}

/* callout boxes */
.callouts {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:18px; margin-top:20px;
  border-top:2px solid #17150f; padding-top:16px; }}
.callout .ct {{ display:block; font-weight:800; font-size:13px; letter-spacing:-0.2px; margin-bottom:5px; }}
.callout p {{ font-size:10.5px; line-height:1.5; margin:0; color:#4a463d; }}
.callout.crit .ct {{ color:#a4632e; }}
.callout.box {{ padding:12px 14px; border-radius:3px; }}
.callout.warn {{ background:#fbf1ea; border-left:3px solid #c0642e; }}
.callout.warn .ct {{ color:#a4632e; }}
.callout.info {{ background:#eef2f5; border-left:3px solid #3a6187; }}
.callout.info .ct {{ color:#33587c; }}
.notice ul.tight {{ margin:6px 0 0; padding-left:16px; }}
.notice ul.tight li {{ font-size:11px; line-height:1.45; margin:3px 0; }}
.notice .ct {{ display:block; font-weight:800; font-size:12px; margin-bottom:2px; }}
.notice {{ background:#fbf1ea; border-left:3px solid #c0642e; border-radius:3px;
  padding:12px 14px; font-size:11px; color:#8a5a34; margin:10px 0; }}
.twocol {{ display:grid; grid-template-columns:1fr 1fr; gap:22px; align-items:start; }}

svg {{ display:block; width:100%; height:auto; }}
.fig svg {{ width:100%; height:auto; max-height:760px; }}
.cover .fig {{ margin:8px 0; padding:8px; }}
.cover .fig svg {{ max-height:392px; }}
.cover .toprule {{ margin-bottom:16px; }}
"""


def _run_chrome(args: list[str], timeout: int = 90) -> None:
    subprocess.run([CHROME, "--headless", "--no-sandbox", "--disable-gpu",
                    "--hide-scrollbars", *args],
                   check=True, capture_output=True, timeout=timeout)


def _dump_dom(html: str, timeout: int = 90) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, dir="out") as fh:
        fh.write(html)
        path = fh.name
    try:
        out = subprocess.run(
            [CHROME, "--headless", "--no-sandbox", "--disable-gpu",
             "--virtual-time-budget=4000", "--dump-dom", f"file://{path}"],
            check=True, capture_output=True, timeout=timeout, text=True,
        )
        return out.stdout
    finally:
        os.unlink(path)


def _measure(blocks: list[Block]) -> dict[str, float]:
    """Pass 1: rendered height of each block at exact print width (never estimated)."""
    items = "\n".join(
        f'<div class="measure" data-id="{b.id}" style="width:{CONTENT_W}px">{b.html}</div>'
        for b in blocks
    )
    harness = f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}
    .measure {{ margin-bottom: 0; }}</style></head><body>{items}
    <script>window.addEventListener('load',function(){{
      var out={{}};
      document.querySelectorAll('.measure').forEach(function(el){{
        // Measure the block's OWN margin-box: getBoundingClientRect() is the
        // border-box and excludes the block's vertical margins, which collapse
        // out of the zero-padding wrapper. Ignoring them is the systematic
        // undercount behind Lesson 5. Add them back (over-counting collapse is the
        // safe direction — it breaks pages early, never late).
        var c=el.firstElementChild||el;
        var cs=getComputedStyle(c);
        out[el.dataset.id]=c.getBoundingClientRect().height
          +parseFloat(cs.marginTop)+parseFloat(cs.marginBottom);}});
      var d=document.createElement('div');d.id='MEAS';
      d.textContent=JSON.stringify(out);document.body.appendChild(d);}});
    </script></body></html>"""
    dom = _dump_dom(harness)
    m = re.search(r'id="MEAS">([^<]*)<', dom)
    if not m:
        raise RuntimeError("measurement harness produced no heights")
    return {k: float(v) for k, v in json.loads(m.group(1)).items()}


def _overflowing_pages(html: str) -> list[int]:
    """Which pages the browser says do not fit — the same question Gate 2 asks."""
    probe = html.replace(
        "</body>",
        """<script>window.addEventListener('load',function(){
          var out=[];
          document.querySelectorAll('.page').forEach(function(p,i){
            var c=p.querySelector('.content');
            if(c.scrollHeight-c.clientHeight>2) out.push(i+1);});
          var d=document.createElement('div');d.id='OVF';
          d.textContent=JSON.stringify(out);document.body.appendChild(d);});</script></body>""")
    m = re.search(r'id="OVF">([^<]*)<', _dump_dom(probe))
    return json.loads(m.group(1)) if m else []


def verified_pages(blocks: list[Block], heights: dict[str, float], render) -> list[list[Block]]:
    """Pack tight, then ask the browser whether it fits; loosen only if it does not.

    Packing to a flat 90% of the page was insurance against a Gate 2 failure — an
    overflowing page blocks release — and it cost that 10% on every page of every
    document whether or not any page was near the edge. The browser can settle it:
    lay the pages out, measure them, and step the capacity back only when a page
    genuinely overflows. Most documents never take the second pass.
    """
    cap = CAPACITY
    while True:
        pages = _paginate(blocks, heights, cap)
        over = _overflowing_pages(render(pages))
        if not over or cap <= CAPACITY_FLOOR:
            return pages
        cap -= CAPACITY_STEP


def _paginate(blocks: list[Block], heights: dict[str, float],
              capacity: float = CAPACITY) -> list[list[Block]]:
    """Pass 2: pack blocks into fixed-height pages against measured heights."""
    pages: list[list[Block]] = []
    cur: list[Block] = []
    used = 0.0
    for b in blocks:
        h = heights[b.id]
        if b.kind == "cover":                       # cover owns its page
            if cur:
                pages.append(cur)
            pages.append([b])
            cur, used = [], 0.0
            continue
        if used + h > capacity and cur:
            pages.append(cur)
            cur, used = [], 0.0
        cur.append(b)
        used += h
    if cur:
        pages.append(cur)

    # Rule: never end a page on a section header — push a trailing header forward.
    fixed: list[list[Block]] = []
    carry: list[Block] = []
    for page in pages:
        page = carry + page
        carry = []
        while len(page) > 1 and page[-1].kind == "header":
            carry.insert(0, page.pop())
        fixed.append(page)
    if carry:
        fixed.append(carry)
    return fixed


def _render_pages(pages: list[list[Block]], runhead: str = "", footer_left: str = "") -> str:
    total = len(pages)
    fl = footer_left or "Build packet &middot; Rev A"
    out = [f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}',
           "@page { size: letter; margin: 0; }</style></head><body>"]
    for i, page in enumerate(pages, 1):
        is_cover = any(b.kind == "cover" for b in page)
        rh = "" if is_cover else f'<div class="runhead"><span>{runhead}</span>' \
                                 f'<span>Build packet Rev {REVISION}</span></div>'
        body = "\n".join(b.html for b in page)
        out.append(
            f'<div class="page">{rh}<div class="content">{body}</div>'
            f'<div class="footer"><span>{fl}</span>'
            f'<span>{i:02d} / {total:02d}</span></div></div>'
        )
    out.append("</body></html>")
    return "\n".join(out)


def render_pdf(html_path: str, pdf_path: str) -> str:
    _run_chrome([f"--print-to-pdf={pdf_path}", "--no-pdf-header-footer",
                 f"file://{os.path.abspath(html_path)}"])
    return pdf_path


def render_cover(html_path: str, png_path: str) -> str:
    """Rasterize just the first page (a reliable, mobile-friendly preview image)."""
    _run_chrome([f"--screenshot={png_path}", f"--window-size={PAGE_W},{PAGE_H}",
                 "--force-device-scale-factor=2",
                 f"file://{os.path.abspath(html_path)}"])
    return png_path


def render_page_pngs(html_path: str, out_dir: str, page_count: int) -> list[str]:
    """Rasterize the whole document to a tall PNG, for the visual gate."""
    png = os.path.join(out_dir, "document_full.png")
    _run_chrome([f"--screenshot={png}", f"--window-size={PAGE_W},{PAGE_H*page_count}",
                 f"file://{os.path.abspath(html_path)}"])
    return [png]
