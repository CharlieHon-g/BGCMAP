from __future__ import annotations

import json
from pathlib import Path
from scripts.pg_script_helper import open_db, pg_query, pg_query_one

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web"
COLORS = ["#3b6fb2", "#5c8a8f", "#9b7ea6", "#c4a06a", "#2c5f8a", "#7a9eb1", "#8d8fb5", "#6da38a"]
INK = "#42586b"
W, H = 600, 280


def svg(inner):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" height="100%" style="background:#fbfdff;font-family:system-ui,sans-serif">{inner}</svg>'


def bar_chart(data, max_bar_h=130, bar_w=62, gap=28):
    max_v = max(d[1] for d in data) or 1
    cx, cy = 50, H - 38
    n = len(data)
    tw = n * bar_w + (n - 1) * gap
    ox = (W - tw) // 2
    bars = f'<line x1="{ox-10}" y1="{cy}" x2="{ox+tw+10}" y2="{cy}" stroke="#d4dfef" stroke-width="2"/>\n'
    for i, (label, cnt) in enumerate(data):
        bh = max(cnt / max_v * max_bar_h, 3)
        x = ox + i * (bar_w + gap)
        y = cy - bh
        bars += f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bh}" rx="5" fill="{COLORS[i%len(COLORS)]}" opacity="0.85"/>\n'
        bars += f'<text x="{x+bar_w/2}" y="{y-8}" text-anchor="middle" font-size="12" fill="{INK}" font-weight="700">{cnt:,}</text>\n'
        bars += f'<text x="{x+bar_w/2}" y="{cy+16}" text-anchor="middle" font-size="11" fill="#667b8f">{label}</text>\n'
    return svg(bars)


def hbar_chart(data, bar_h=30, gap=10, max_w=340):
    max_v = max(d[1] for d in data) or 1
    cy = 28
    bars = ""
    for i, (label, cnt) in enumerate(data):
        bw = max(cnt / max_v * max_w, 5)
        y = cy + i * (bar_h + gap)
        bars += f'<text x="12" y="{y+bar_h/2+4}" font-size="12" fill="{INK}">{label}</text>\n'
        bars += f'<rect x="175" y="{y}" width="{bw}" height="{bar_h}" rx="5" fill="{COLORS[i%len(COLORS)]}" opacity="0.85"/>\n'
        bars += f'<text x="{175+bw+8}" y="{y+bar_h/2+4}" font-size="12" fill="{INK}" font-weight="700">{cnt:,}</text>\n'
    return svg(bars)


def pie_chart(rows):
    total = sum(r[1] for r in rows)
    cx, cy, r = 150, 135, 100
    sofar, slices = 0, ""
    for i, (label, cnt) in enumerate(rows):
        pct = cnt / total
        sweep = pct * 360
        start = sofar / total * 360
        sofar += cnt
        start_rad = start * 3.14159 / 180
        slices += f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{COLORS[i]}" stroke-width="56" stroke-dasharray="{sweep/360*2*3.14159*r} {2*3.14159*r}" stroke-dashoffset="{-start_rad*r}" transform="rotate(-90 {cx} {cy})" opacity="0.92"/>\n'
    legend = ""
    for i, (label, cnt) in enumerate(rows):
        y = 34 + i * 30
        legend += f'<rect x="310" y="{y}" width="12" height="12" rx="3" fill="{COLORS[i]}"/>\n'
        legend += f'<text x="328" y="{y+11}" font-size="11" fill="{INK}">{label[:24]}</text>\n'
        legend += f'<text x="328" y="{y+24}" font-size="10" fill="#889aaa">{cnt:,}</text>\n'
    return svg(slices + legend)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    conn = open_db()

    bins = [("1970-1999", 1970, 1999), ("2000-2004", 2000, 2004), ("2005-2009", 2005, 2009),
            ("2010-2014", 2010, 2014), ("2015-2019", 2015, 2019), ("2020-2025", 2020, 2025)]
    
    # Extract earliest year from raw date (matching filter logic)
    start_year_expr = """
        CASE 
            WHEN collection_date_raw ~ '^\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2}' THEN SUBSTR(collection_date_raw, 1, 4)::int
            WHEN collection_date_raw ~ '^\d{4}-\d{2}/\d{4}-\d{2}' THEN SUBSTR(collection_date_raw, 1, 4)::int
            WHEN collection_date_raw ~ '^\d{4}-\d{2}-\d{2}' THEN SUBSTR(collection_date_raw, 1, 4)::int
            WHEN collection_date_raw ~ '^\d{4}/\d{4}' THEN SUBSTR(collection_date_raw, 1, 4)::int
            WHEN collection_date_raw ~ '^\d{4}-\d{2}-\d{4}-\d{2}' THEN SUBSTR(collection_date_raw, 1, 4)::int
            WHEN collection_date_raw ~ '^\d{4}-\d{4}' THEN SUBSTR(collection_date_raw, 1, 4)::int
            WHEN collection_date_raw ~ '^\d{2}/\d{2}/\d{4}' THEN SUBSTR(collection_date_raw, 7, 4)::int
            WHEN collection_date_raw ~ '^\d{4}-\d{2}' THEN SUBSTR(collection_date_raw, 1, 4)::int
            WHEN collection_date_raw ~ '^\d{4}' THEN collection_date_raw::int
            ELSE NULL
        END
    """
    
    year_data = []
    for label, s, e in bins:
        cnt = pg_query_one(conn, f"SELECT COUNT(*) AS cnt FROM sample WHERE {start_year_expr} BETWEEN %s AND %s", (s, e))["cnt"]
        year_data.append((label, cnt))
    
    unknown = pg_query_one(conn, f"SELECT COUNT(*) AS cnt FROM sample WHERE {start_year_expr} IS NULL")["cnt"]
    year_data.append(("Unknown", unknown))
    
    (OUT / "stats_collection_year.svg").write_text(bar_chart(year_data))

    biome_rows = pg_query(conn, "SELECT biome1 AS g, COUNT(*) AS c FROM sample WHERE biome1 IS NOT NULL AND biome1<>'' GROUP BY 1 ORDER BY c DESC")
    biome_data = [(r["g"].replace(" Environment", ""), r["c"]) for r in biome_rows]
    (OUT / "stats_biome.svg").write_text(hbar_chart(biome_data))

    bgc_rows = pg_query(conn, "SELECT category_primary AS g, COUNT(*) AS c FROM bgc WHERE category_primary IS NOT NULL AND category_primary<>'' GROUP BY 1 ORDER BY c DESC LIMIT 8")
    (OUT / "stats_bgc_type.svg").write_text(pie_chart([(r["g"], r["c"]) for r in bgc_rows]))

    row = pg_query_one(conn, """
        SELECT SUM(CASE WHEN bgc_count=1 THEN 1 ELSE 0 END) AS c1, SUM(CASE WHEN bgc_count BETWEEN 2 AND 4 THEN 1 ELSE 0 END) AS c2_4,
               SUM(CASE WHEN bgc_count BETWEEN 5 AND 8 THEN 1 ELSE 0 END) AS c5_8, SUM(CASE WHEN bgc_count BETWEEN 9 AND 30 THEN 1 ELSE 0 END) AS c9_30,
               SUM(CASE WHEN bgc_count BETWEEN 31 AND 50 THEN 1 ELSE 0 END) AS c31_50, SUM(CASE WHEN bgc_count>50 THEN 1 ELSE 0 END) AS c50p
        FROM mv_gcf_page
    """)
    (OUT / "stats_gcf_size.svg").write_text(bar_chart([("1", row["c1"]), ("2-4", row["c2_4"]), ("5-8", row["c5_8"]), ("9-30", row["c9_30"]), ("31-50", row["c31_50"]), (">50", row["c50p"])]))

    conn.close()
    print("Stats charts generated")


if __name__ == "__main__":
    main()
