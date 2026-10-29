"""Quote PDF with WeasyPrint. Fonts come from the local frontend build, never from a CDN."""

from html import escape

from .config import get_settings


def _eur(n: float) -> str:
    return f"€{n:,.0f}"


def quote_pdf(data: dict, org_name: str, sender_name: str) -> bytes:
    from weasyprint import HTML

    fonts = get_settings().frontend_dist.parent / "public" / "fonts"
    rows = "".join(
        f"<tr><td>{escape(l['origin'])} → {escape(l['destination'])}{' <span class=new>new</span>' if l.get('new') else ''}</td>"
        f"<td class=num>{l['loads']}</td><td class=num>{_eur(l['rate'])}</td><td class=num>{_eur(l['loads'] * l['rate'])}</td></tr>"
        for l in data["lines"]
    )
    loads = sum(l["loads"] for l in data["lines"])
    # The agent's note (own trucks vs. subcontractor) is internal and stays out of the customer document.
    html = f"""<!doctype html><html><head><meta charset=utf-8><style>
@font-face {{ font-family: Hanken; src: url('file://{fonts}/hanken-grotesk-latin.woff2'); }}
@font-face {{ font-family: Bricolage; src: url('file://{fonts}/bricolage-grotesque-latin.woff2'); }}
@page {{ size: A4; margin: 22mm 20mm; @bottom-left {{ content: "{escape(org_name)}"; font: 9pt Hanken, sans-serif; color: #5B6773; }} }}
body {{ font: 10.5pt/1.5 Hanken, sans-serif; color: #1C2430; }}
h1 {{ font-family: Bricolage, sans-serif; font-size: 22pt; margin: 0 0 4pt; letter-spacing: -.01em; }}
.sub {{ color: #5B6773; margin: 0 0 18pt; }}
table {{ width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }}
th {{ text-align: left; font-size: 9pt; color: #5B6773; font-weight: 600; padding: 4pt 6pt; }}
td {{ padding: 6pt; border-top: 1px solid #C8D0CC; }}
.num {{ text-align: right; white-space: nowrap; }}
tfoot td {{ font-weight: 700; border-top: 1.5px solid #1C2430; }}
.new {{ color: #0E6B63; font-size: 8.5pt; font-weight: 700; margin-left: 4pt; }}
.note {{ margin-top: 14pt; padding: 8pt 10pt; background: #F2F5F3; border-radius: 4pt; }}
.from {{ margin-top: 26pt; color: #5B6773; }}
</style></head><body>
<h1>Quote {data['year']}</h1>
<p class=sub>{escape(org_name)} for {escape(data['customer'])}</p>
<table><thead><tr><th>Route</th><th class=num>Loads a month</th><th class=num>Price per load</th><th class=num>A month</th></tr></thead>
<tbody>{rows}</tbody>
<tfoot><tr><td>Per month</td><td class=num>{loads}</td><td></td><td class=num>{_eur(data['total_per_month'])}</td></tr></tfoot></table>
<p class=from>{escape(sender_name)}, {escape(org_name)}</p>
</body></html>"""
    return HTML(string=html).write_pdf()
