#!/usr/bin/env python3
"""Справка ЖДуши → красивый PDF (оформление как у Ави), без отправки. Отправляет потом send.py.

  ~/pw/bin/python ~/railway-monitor/zreport.py saved/2026-10-16_ПГК.md      → saved/2026-10-16_ПГК.pdf

Разметка (.md), всё необязательно:
  {{класс:D}}            цветная плашка класса риска (A–E)
  ```cards               карточки цифр: «Выручка | 116,9 млрд ₽ | ▼ −15% к 2024»; риск — начать изменение с ⚠ (красное),
  ```                    хорошее — с ✓ (зелёное)
  ```chart               столбики: «Выручка, млрд ₽ | 2023: 117 | 2024: 137 | 2025: 117»
  ```risks              риски-светофор: «высокий | Отрицательный капитал группы −12,1 млрд ₽» (высокий/средний/низкий)
  ```plus               сильные стороны: по одной на строку
  > **Что делать:** …    итоговая рекомендация — выделенная рамка
"""
import html as H
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.environ.get("AVI_DIR", str(Path.home() / "aviation-monitor")))
import share as S  # noqa: E402  — те же плашка, карточки, графики и печать в PDF, что у Ави

CSS = """.card .d.ok{color:#1e8e3e}.risks{margin:6pt 0}.risk{display:flex;gap:8pt;align-items:flex-start;padding:4pt 0;
border-bottom:1px solid #eef1f4;break-inside:avoid}.lvl{flex:0 0 62pt;text-align:center;border-radius:9pt;color:#fff;
font-size:8.5pt;font-weight:bold;padding:2pt 0}.lvl.h{background:#c62828}.lvl.m{background:#f9a825}.lvl.l{background:#1e8e3e}
.plus{margin:6pt 0;padding:0;list-style:none}.plus li{padding:2pt 0 2pt 16pt;position:relative}
.plus li:before{content:'✓';color:#1e8e3e;font-weight:bold;position:absolute;left:0}
.badge{font-size:14pt;padding:4pt 16pt}h1+p{margin-top:2pt}
blockquote{border-left:4px solid #0b62c4;background:#eef5fd;font-size:11pt}
.pb{break-after:page}"""

LEVEL = {"высокий": "h", "средний": "m", "низкий": "l"}


def extra(md):
    def risks(m):
        rows = []
        for line in m.group(1).strip().splitlines():
            lvl, _, text = (x.strip() for x in line.partition("|"))
            cls = LEVEL.get(lvl.lower(), "m")
            rows.append(f'<div class="risk"><span class="lvl {cls}">{H.escape(lvl.lower())}</span>'
                        f'<span>{H.escape(text)}</span></div>')
        return '\n<div class="risks">' + "".join(rows) + "</div>\n"
    md = re.sub(r"```risks\s*\n(.*?)```", risks, md, flags=re.S)

    def plus(m):
        items = "".join(f"<li>{H.escape(x.strip())}</li>" for x in m.group(1).strip().splitlines() if x.strip())
        return f'\n<ul class="plus">{items}</ul>\n'
    md = re.sub(r"```plus\s*\n(.*?)```", plus, md, flags=re.S)
    return md.replace("<!-- новая страница -->", '<div class="pb"></div>')


def build(src):
    src = Path(src).expanduser().resolve()
    pdf, html, tmp = src.with_suffix(".pdf"), src.with_suffix(".html"), src.with_name(src.stem + "_tmp.md")
    md = S._rich(extra(src.read_text(encoding="utf-8")))
    md = re.sub(r'class="d ">(✓)', r'class="d ok">\1', md)  # карточка с ✓ — зелёным
    tmp.write_text(md, encoding="utf-8")
    try:
        subprocess.run(["pandoc", str(tmp), "-f", "markdown+raw_html", "-s", "--metadata", f"pagetitle={src.stem}",
                        "-o", str(html)], check=True)
    finally:
        tmp.unlink(missing_ok=True)
    html.write_text(html.read_text(encoding="utf-8").replace("</head>", f"<style>{S.CSS}{CSS}</style></head>"),
                    encoding="utf-8")
    if os.environ.get("ZREPORT_HTML_ONLY"):
        print(f"HTML: {html}")
        return html
    S._pdf(html, pdf, src.stem)
    html.unlink(missing_ok=True)
    print(f"PDF: {pdf}")
    return pdf


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    build(sys.argv[1])
