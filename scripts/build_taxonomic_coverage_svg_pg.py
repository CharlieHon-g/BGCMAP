from __future__ import annotations

from pathlib import Path
from scripts.pg_script_helper import open_db, pg_query, pg_query_one


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "stats" / "taxonomic_coverage.svg"

RANKS = [
    ("Domain", "domain"),
    ("Phylum", "phylum"),
    ("Class", "class_name"),
    ("Order", "order_name"),
    ("Family", "family"),
    ("Genus", "genus"),
    ("Species", "species"),
]


def query_rows():
    conn = open_db()
    total = pg_query_one(conn, "select count(*) from mag")[0]
    rows = []
    for label, col in RANKS:
        q = (
            f"select count(*) from mag "
            f"where {col} is not null and trim({col})<>'' "
            f"and lower(trim({col})) not in ('na','nan','none','null','unclassified','unassigned')"
        )
        annotated = pg_query_one(conn, q)[0]
        missing = total - annotated
        pct = annotated * 100.0 / total if total else 0.0
        rows.append((label, annotated, missing, pct))
    conn.close()
    return total, rows


def fmt(n: int) -> str:
    return f"{n:,}"


def build():
    total, rows = query_rows()
    width = 1800
    row_h = 110
    top = 130
    height = top + len(rows) * row_h + 70

    label_x = 70
    bar_x = 250
    bar_w = 720
    stat_x = 1020

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" height="100%">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#f8fbfd"/>',
        '<text x="70" y="54" font-size="34" font-weight="800" fill="#223548" font-family="Segoe UI, Helvetica Neue, Arial, sans-serif">Taxonomic coverage</text>',
        f'<text x="70" y="84" font-size="17" font-weight="500" fill="#617487" font-family="Segoe UI, Helvetica Neue, Arial, sans-serif">Availability of taxonomic annotations across {fmt(total)} MAG records, from domain to species.</text>',
    ]

    for idx, (label, annotated, missing, pct) in enumerate(rows):
        y = top + idx * row_h
        bar_y = y + 28
        fill_w = bar_w * pct / 100.0
        svg.append(f'<text x="{label_x}" y="{y+46}" font-size="24" font-weight="700" fill="#223548" font-family="Segoe UI, Helvetica Neue, Arial, sans-serif">{label}</text>')
        svg.append(f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="28" rx="14" fill="#e7edf2"/>')
        svg.append(f'<rect x="{bar_x}" y="{bar_y}" width="{fill_w:.1f}" height="28" rx="14" fill="#2b6e9c"/>')
        for t in range(0, int(bar_w), 44):
            x = bar_x + t
            svg.append(f'<line x1="{x}" y1="{bar_y+5}" x2="{x+14}" y2="{bar_y+23}" stroke="#d6dee6" stroke-width="2" opacity="0.7"/>')
        text = f"{fmt(annotated)} annotated | {fmt(missing)} NA | {pct:.1f}%"
        svg.append(f'<text x="{stat_x}" y="{y+47}" font-size="22" font-weight="600" fill="#2b3f52" font-family="Segoe UI, Helvetica Neue, Arial, sans-serif">{text}</text>')

    svg.append('<text x="70" y="{}" font-size="16" font-weight="500" fill="#6d7f8f" font-family="Segoe UI, Helvetica Neue, Arial, sans-serif">NA indicates MAG records without confident assignment at the corresponding taxonomic rank.</text>'.format(height - 26))
    svg.append("</svg>")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(svg), encoding="utf-8")


if __name__ == "__main__":
    build()
