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

from .content import Block, build_blocks, REVISION
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
AVAILABLE = PAGE_H - 2 * MARGIN - FOOTER_H    # 948
CAPACITY = 900                                 # below available (Lesson 5 buffer)

CSS = f"""
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: Helvetica, Arial, sans-serif; color: #1a1a1a; }}
.page {{
  width: {PAGE_W}px; height: {PAGE_H}px; padding: {MARGIN}px;
  display: flex; flex-direction: column; overflow: hidden;
  page-break-after: always; position: relative; background: #fff;
}}
.content {{ flex: 1; overflow: hidden; }}
.footer {{ margin-top: auto; height: {FOOTER_H}px; border-top: 1px solid #ccc;
  font-size: 10px; color: #666; display: flex; justify-content: space-between;
  align-items: flex-end; padding-top: 6px; }}
h1.doctitle {{ font-size: 30px; margin: 4px 0; }}
.subtitle {{ color: #555; font-size: 14px; margin-bottom: 14px; }}
h2.section {{ font-size: 16px; border-bottom: 2px solid #1a1a1a; padding-bottom: 3px;
  margin: 8px 0 8px; }}
p {{ font-size: 12.5px; line-height: 1.5; margin: 6px 0; }}
table.grid {{ width: 100%; border-collapse: collapse; font-size: 11.5px; margin: 6px 0; }}
table.grid th {{ background: #1a1a1a; color: #fff; text-align: left; padding: 5px 7px; }}
table.grid td {{ border: 1px solid #ddd; padding: 5px 7px; vertical-align: top; }}
table.grid td.cb {{ text-align: center; width: 20px; }}
.fig {{ border: 1px solid #e2e2e2; border-radius: 4px; padding: 8px; margin: 8px 0; background:#fff; }}
.figcap {{ font-size: 10.5px; color: #555; margin-top: 4px; }}
.figcap .stage {{ color:#111; font-weight:bold; }}
.step {{ border: 1px solid #ddd; border-left: 4px solid #1a1a1a; border-radius: 3px;
  padding: 8px 10px; margin: 7px 0; background: #fafafa; }}
.stephead {{ display: flex; align-items: baseline; gap: 8px; }}
.stepn {{ background:#1a1a1a; color:#fff; border-radius:50%; width:22px; height:22px;
  display:inline-flex; align-items:center; justify-content:center; font-size:11px; flex:0 0 auto; }}
.stepphase {{ font-size:10px; text-transform:uppercase; letter-spacing:.5px; color:#888; }}
.steptitle {{ font-weight:bold; font-size:13px; }}
.stepdetail {{ font-size:12px; margin:5px 0; line-height:1.45; }}
.chips {{ margin: 4px 0; }}
.chip {{ display:inline-block; font-size:10px; padding:2px 6px; margin:2px 3px 2px 0;
  border-radius:10px; }}
.chip.tool {{ background:#e7eef7; }} .chip.mat {{ background:#eef3e7; }} .chip.fast {{ background:#f7ede7; }}
.steptol {{ font-size:11px; color:#333; }}
.stepsign {{ font-size:11px; margin-top:4px; }} .stepsign .ts {{ float:right; color:#999; }}
.cover .revtag {{ position:absolute; top:{MARGIN}px; right:{MARGIN}px; background:#1a1a1a;
  color:#fff; font-size:11px; padding:3px 10px; border-radius:3px; }}
.specsummary {{ display:grid; grid-template-columns:1fr 1fr; gap:6px 24px; margin:12px 0; }}
.specsummary .k {{ color:#888; font-size:11px; display:inline-block; width:100px; }}
.specsummary .v {{ font-weight:bold; font-size:13px; }}
svg {{ display:block; width:100%; height:auto; }}
.fig svg {{ width:100%; height:auto; max-height:780px; }}
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


def _paginate(blocks: list[Block], heights: dict[str, float]) -> list[list[Block]]:
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
        if used + h > CAPACITY and cur:
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


def _render_pages(pages: list[list[Block]]) -> str:
    total = len(pages)
    out = [f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}',
           "@page { size: letter; margin: 0; }</style></head><body>"]
    for i, page in enumerate(pages, 1):
        body = "\n".join(b.html for b in page)
        out.append(
            f'<div class="page"><div class="content">{body}</div>'
            f'<div class="footer"><span>Coffee table &middot; Rev {REVISION}</span>'
            f'<span>{i:02d} / {total:02d}</span></div></div>'
        )
    out.append("</body></html>")
    return "\n".join(out)


def build_document(geo: Geometry, plan: NestingPlan, out_name: str = "coffee_table") -> dict:
    """Full two-pass build. Returns paths and pagination metadata."""
    blocks = build_blocks(geo, plan)
    heights = _measure(blocks)                       # pass 1
    pages = _paginate(blocks, heights)               # pass 2
    html = _render_pages(pages)                       # totals resolved here
    os.makedirs("out", exist_ok=True)
    html_path = os.path.join("out", f"{out_name}.html")
    with open(html_path, "w") as fh:
        fh.write(html)
    return {"html_path": html_path, "html": html, "pages": pages,
            "page_count": len(pages), "heights": heights, "blocks": blocks}


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
