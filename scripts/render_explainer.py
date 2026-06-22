#!/usr/bin/env python3
"""Render a docs/*.md decision writeup to a readable standalone HTML page in output/.

These docs are the HUMAN decision layer, kept OUTSIDE the data-only report (CLAUDE.md
rule 2). This is just a reader-friendly view of the markdown — no model math here.

Usage: uv run python scripts/render_explainer.py docs/decision-framework-explained.md
"""

import html as _html
import pathlib
import re
import sys

import markdown

STYLE = """
  :root { --ink:#1a1a1a; --muted:#5a5f66; --rule:#e6e8eb; --accent:#2a5db0; --quote-bg:#f6f8fb; }
  * { box-sizing:border-box; }
  html { -webkit-text-size-adjust:100%; }
  body { margin:0; background:#fbfbfc; color:var(--ink);
         font:18px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
  .wrap { max-width:760px; margin:0 auto; padding:56px 24px 120px; }
  h1 { font-size:2.05rem; line-height:1.2; margin:0 0 .15em; letter-spacing:-.01em; }
  h2 { font-size:1.5rem; margin:2em 0 .6em; padding-top:1.4em; border-top:1px solid var(--rule); letter-spacing:-.01em; }
  h3 { font-size:1.18rem; margin:1.7em 0 .4em; color:#222; }
  p { margin:.85em 0; }
  em { color:#333; } strong { color:#000; } a { color:var(--accent); }
  hr { border:0; border-top:1px solid var(--rule); margin:2em 0; }
  blockquote { margin:1.4em 0; padding:14px 20px; background:var(--quote-bg); border-left:4px solid var(--accent); border-radius:0 8px 8px 0; font-size:1.05rem; }
  blockquote p:first-child { margin-top:0; } blockquote p:last-child { margin-bottom:0; }
  blockquote strong { color:var(--accent); }
  ul,ol { padding-left:1.4em; margin:.85em 0; } li { margin:.4em 0; }
  code { background:#eef0f3; padding:.1em .4em; border-radius:4px; font:.92em/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; }
  table { border-collapse:collapse; width:100%; margin:1.4em 0; font-size:.96rem; }
  th,td { text-align:left; padding:10px 14px; border-bottom:1px solid var(--rule); vertical-align:top; }
  thead th { border-bottom:2px solid #d3d7dd; background:#f3f5f8; }
  tbody tr:nth-child(even) { background:#fafbfc; }
  .wrap > p:first-of-type { margin-top:.2em; color:var(--muted); font-size:1.05rem; }
  .wrap > p:first-of-type em { color:var(--muted); }
  @media (max-width:560px){ body{font-size:17px;} .wrap{padding:32px 18px 80px;} table{font-size:.9rem;} th,td{padding:8px 10px;} }
"""


def render(md_path: pathlib.Path) -> pathlib.Path:
    src = md_path.read_text()
    title = next((ln[2:].strip() for ln in src.splitlines() if ln.startswith("# ")), md_path.stem)
    body = markdown.markdown(src, extensions=["tables", "sane_lists", "smarty"])
    # Each <h2> draws its own top rule; a literal `---` right before one would stack a second
    # line with a gap. Drop those redundant <hr>s so section breaks are a single line.
    body = re.sub(r"<hr\s*/?>\s*(?=<h2)", "", body)
    page = (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_html.escape(title)}</title><style>{STYLE}</style></head>\n"
        f'<body><main class="wrap">\n{body}\n</main></body></html>\n'
    )
    out = pathlib.Path("output") / (md_path.stem + ".html")
    out.parent.mkdir(exist_ok=True)
    out.write_text(page)
    return out


if __name__ == "__main__":
    targets = sys.argv[1:] or ["docs/decision-framework-explained.md"]
    for t in targets:
        out = render(pathlib.Path(t))
        print(f"[wrote {out} from {t}]")
