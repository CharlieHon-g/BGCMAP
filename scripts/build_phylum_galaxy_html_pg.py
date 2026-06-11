from __future__ import annotations

import json
import math
from pathlib import Path
from scripts.pg_script_helper import open_db, pg_query, pg_query_one


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_HTML = ROOT / "web" / "phylum_galaxy.html"

TOP_N = 12
PALETTE = [
    "#d55d3e",
    "#4f7d39",
    "#a64d79",
    "#7a4cc2",
    "#d2a72e",
    "#1d9a8a",
    "#2d6cdf",
    "#c86b32",
    "#5571b9",
    "#8d5db3",
    "#2f9d6f",
    "#b74f60",
    "#6d8f2e",
]


def fetch_phylum_stats() -> list[dict]:
    conn = open_db()
    rows = pg_query(
        conn,
        """
        SELECT
          COALESCE(NULLIF(m.phylum, ''), 'Unclassified') AS phylum,
          COUNT(DISTINCT m.mag_pk) AS mag_count,
          COUNT(b.bgc_pk) AS bgc_count,
          COUNT(DISTINCT m.sample_pk) AS sample_count,
          COUNT(DISTINCT NULLIF(m.species, '')) AS species_count,
          ROUND(AVG(m.completeness), 2) AS avg_completeness,
          ROUND(AVG(m.contamination), 2) AS avg_contamination
        FROM mag m
        LEFT JOIN bgc b ON b.mag_pk = m.mag_pk
        GROUP BY 1
        ORDER BY mag_count DESC
        """
    )
    conn.close()

    items = [dict(row) for row in rows]
    top = items[:TOP_N]
    rest = items[TOP_N:]
    if rest:
        top.append(
            {
                "phylum": "Other phyla",
                "mag_count": sum(item["mag_count"] for item in rest),
                "bgc_count": sum(item["bgc_count"] for item in rest),
                "sample_count": sum(item["sample_count"] for item in rest),
                "species_count": sum(item["species_count"] for item in rest),
                "avg_completeness": round(
                    sum((item["avg_completeness"] or 0) * item["mag_count"] for item in rest)
                    / max(1, sum(item["mag_count"] for item in rest)),
                    2,
                ),
                "avg_contamination": round(
                    sum((item["avg_contamination"] or 0) * item["mag_count"] for item in rest)
                    / max(1, sum(item["mag_count"] for item in rest)),
                    2,
                ),
                "grouped": True,
            }
        )
    return top


def build_html(stats: list[dict]) -> str:
    total_mags = sum(item["mag_count"] for item in stats)
    max_mags = max(item["mag_count"] for item in stats)
    enriched = []
    for idx, item in enumerate(stats):
        phylum = item["phylum"]
        grouped = item.get("grouped", False)
        item = {
            **item,
            "color": PALETTE[idx % len(PALETTE)],
            "share": round(item["mag_count"] / total_mags * 100, 2),
            "dot_count": max(18, min(105, round(18 + 78 * math.sqrt(item["mag_count"] / max_mags)))),
            "target_url": "/mag.html" if grouped else f"/mag.html?phylum={phylum}",
        }
        enriched.append(item)

    data_json = json.dumps(enriched, ensure_ascii=False, separators=(",", ":"))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Phylum Galaxy</title>
  <style>
    :root {{
      --bg: #f5f1e8;
      --ink: #233242;
      --muted: #5e6d7a;
      --line: #d9d1c3;
      --panel: rgba(250, 248, 243, 0.94);
      --center: #ffffff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(circle at top, rgba(232,244,248,0.92), transparent 38%),
        linear-gradient(180deg, #f7f2e8 0%, #edf5f7 100%);
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      color: var(--ink);
    }}
    .page {{
      width: min(1500px, 100vw);
      margin: 0 auto;
      padding: 28px 24px 30px;
    }}
    .hero {{
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 18px;
      margin-bottom: 18px;
    }}
    .hero h1 {{
      margin: 0;
      font-size: clamp(34px, 4vw, 58px);
      line-height: 1.03;
      letter-spacing: -0.03em;
    }}
    .hero p {{
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 15px;
      line-height: 1.6;
      max-width: 760px;
    }}
    .hero .meta {{
      flex: 0 0 auto;
      padding: 12px 16px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: var(--panel);
      box-shadow: 0 14px 32px rgba(35, 50, 66, 0.08);
      text-align: right;
    }}
    .hero .meta strong {{
      display: block;
      font-size: 13px;
      color: var(--muted);
      font-weight: 600;
      margin-bottom: 3px;
    }}
    .hero .meta span {{
      display: block;
      font-size: 24px;
      font-weight: 700;
    }}
    .viz-wrap {{
      position: relative;
      border: 1px solid var(--line);
      border-radius: 32px;
      background: linear-gradient(180deg, rgba(255,255,255,0.72), rgba(252,248,241,0.94));
      box-shadow: 0 24px 60px rgba(35, 50, 66, 0.12);
      overflow: hidden;
    }}
    #viz {{
      display: block;
      width: 100%;
      height: auto;
    }}
    .tooltip {{
      position: absolute;
      right: 20px;
      bottom: 20px;
      width: min(360px, calc(100% - 40px));
      display: none;
      padding: 16px 18px;
      border-radius: 20px;
      border: 1px solid var(--line);
      background: rgba(250,248,243,0.97);
      box-shadow: 0 14px 36px rgba(35, 50, 66, 0.14);
      backdrop-filter: blur(8px);
    }}
    .tooltip.visible {{ display: block; }}
    .tooltip h3 {{
      margin: 0 0 8px;
      font-size: 20px;
    }}
    .tooltip p {{
      margin: 5px 0;
      font-size: 14px;
      line-height: 1.5;
      color: #334155;
    }}
    .tooltip a {{
      display: inline-block;
      margin-top: 8px;
      padding: 9px 12px;
      border-radius: 10px;
      border: 1px solid #c9c2b5;
      text-decoration: none;
      color: var(--ink);
      font-weight: 700;
      background: white;
    }}
    .legend {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px 14px;
      margin-top: 14px;
      padding: 14px 16px;
      border-radius: 22px;
      border: 1px solid var(--line);
      background: var(--panel);
      box-shadow: 0 12px 28px rgba(35, 50, 66, 0.08);
    }}
    .legend-item {{
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      font-size: 12px;
      color: #344457;
    }}
    .legend-swatch {{
      width: 11px;
      height: 11px;
      border-radius: 999px;
      flex: 0 0 auto;
    }}
    .legend-label {{
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    @media (max-width: 980px) {{
      .page {{ padding: 18px 16px 22px; }}
      .hero {{
        display: block;
      }}
      .hero .meta {{
        display: inline-block;
        margin-top: 12px;
        text-align: left;
      }}
      .legend {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="hero">
      <div>
        <h1>Phylum Galaxy</h1>
        <p>A phylum-centered entry map for the MAG catalog. Click a phylum sector or point cloud to open the corresponding MAG view.</p>
      </div>
      <div class="meta">
        <strong>MAGs represented</strong>
        <span>{sum(item["mag_count"] for item in enriched):,}</span>
      </div>
    </div>

    <div class="viz-wrap">
      <svg id="viz" viewBox="0 0 1400 980" aria-label="Phylum galaxy"></svg>
      <div id="tooltip" class="tooltip"></div>
    </div>

    <div class="legend">
      {"".join(f'<div class="legend-item"><span class="legend-swatch" style="background:{item["color"]}"></span><span class="legend-label">{item["phylum"]}</span></div>' for item in enriched)}
    </div>
  </div>

  <script id="phylum-data" type="application/json">{data_json}</script>
  <script>
    const data = JSON.parse(document.getElementById('phylum-data').textContent);
    const svg = document.getElementById('viz');
    const tooltip = document.getElementById('tooltip');
    const NS = "http://www.w3.org/2000/svg";
    const width = 1400;
    const height = 980;
    const cx = width / 2;
    const cy = height / 2 + 18;
    const innerR = 148;
    const outerR = 372;
    const pointInnerR = 208;
    const pointOuterR = 340;
    const total = data.reduce((sum, d) => sum + d.mag_count, 0);

    function polar(cx, cy, r, angle) {{
      return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)];
    }}

    function ringSectorPath(cx, cy, r0, r1, a0, a1) {{
      const large = (a1 - a0) > Math.PI ? 1 : 0;
      const [x0, y0] = polar(cx, cy, r1, a0);
      const [x1, y1] = polar(cx, cy, r1, a1);
      const [x2, y2] = polar(cx, cy, r0, a1);
      const [x3, y3] = polar(cx, cy, r0, a0);
      return [
        `M ${{x0.toFixed(2)}} ${{y0.toFixed(2)}}`,
        `A ${{r1}} ${{r1}} 0 ${{large}} 1 ${{x1.toFixed(2)}} ${{y1.toFixed(2)}}`,
        `L ${{x2.toFixed(2)}} ${{y2.toFixed(2)}}`,
        `A ${{r0}} ${{r0}} 0 ${{large}} 0 ${{x3.toFixed(2)}} ${{y3.toFixed(2)}}`,
        "Z"
      ].join(" ");
    }}

    function hashString(str) {{
      let h = 2166136261;
      for (let i = 0; i < str.length; i += 1) {{
        h ^= str.charCodeAt(i);
        h = Math.imul(h, 16777619);
      }}
      return h >>> 0;
    }}

    function mulberry32(a) {{
      return function() {{
        let t = a += 0x6D2B79F5;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
      }}
    }}

    function showTooltip(item) {{
      tooltip.innerHTML = `
        <h3>${{item.phylum}}</h3>
        <p><strong>MAG count:</strong> ${{item.mag_count.toLocaleString()}}</p>
        <p><strong>BGC count:</strong> ${{item.bgc_count.toLocaleString()}}</p>
        <p><strong>Sample count:</strong> ${{item.sample_count.toLocaleString()}}</p>
        <p><strong>Annotated species:</strong> ${{item.species_count.toLocaleString()}}</p>
        <p><strong>Average completeness:</strong> ${{item.avg_completeness ?? "NA"}}%</p>
        <p><strong>Average contamination:</strong> ${{item.avg_contamination ?? "NA"}}%</p>
        <p><strong>Share of MAGs:</strong> ${{item.share.toFixed(2)}}%</p>
        <a href="${{item.target_url}}">Open MAG view</a>
      `;
      tooltip.classList.add("visible");
    }}

    function clearTooltip() {{
      tooltip.classList.remove("visible");
    }}

    const bg = document.createElementNS(NS, "rect");
    bg.setAttribute("x", "0");
    bg.setAttribute("y", "0");
    bg.setAttribute("width", width);
    bg.setAttribute("height", height);
    bg.setAttribute("fill", "transparent");
    svg.appendChild(bg);

    const halo = document.createElementNS(NS, "circle");
    halo.setAttribute("cx", cx);
    halo.setAttribute("cy", cy);
    halo.setAttribute("r", 430);
    halo.setAttribute("fill", "rgba(237,245,247,0.9)");
    svg.appendChild(halo);

    const orbits = [190, 250, 310, 370];
    for (const r of orbits) {{
      const c = document.createElementNS(NS, "circle");
      c.setAttribute("cx", cx);
      c.setAttribute("cy", cy);
      c.setAttribute("r", r);
      c.setAttribute("fill", "none");
      c.setAttribute("stroke", "#ddd6c8");
      c.setAttribute("stroke-width", "1");
      c.setAttribute("stroke-dasharray", "4 6");
      c.setAttribute("opacity", "0.65");
      svg.appendChild(c);
    }}

    const totalAngle = Math.PI * 2;
    const gap = 0.018;
    let cursor = -Math.PI / 2;

    data.forEach((item) => {{
      const span = (item.mag_count / total) * totalAngle;
      const a0 = cursor + gap / 2;
      const a1 = cursor + span - gap / 2;
      const mid = (a0 + a1) / 2;
      item._angles = {{ a0, a1, mid }};
      cursor += span;

      const sector = document.createElementNS(NS, "path");
      sector.setAttribute("d", ringSectorPath(cx, cy, innerR, outerR, a0, a1));
      sector.setAttribute("fill", item.color);
      sector.setAttribute("fill-opacity", "0.13");
      sector.setAttribute("stroke", item.color);
      sector.setAttribute("stroke-width", "1.3");
      sector.setAttribute("cursor", "pointer");
      sector.addEventListener("mouseenter", () => showTooltip(item));
      sector.addEventListener("mouseleave", clearTooltip);
      sector.addEventListener("click", () => window.location.href = item.target_url);
      svg.appendChild(sector);

      const rng = mulberry32(hashString(item.phylum));
      for (let i = 0; i < item.dot_count; i += 1) {{
        const angle = a0 + (a1 - a0) * rng();
        const radius = pointInnerR + (pointOuterR - pointInnerR) * Math.sqrt(rng());
        const [x, y] = polar(cx, cy, radius, angle);
        const dot = document.createElementNS(NS, "circle");
        dot.setAttribute("cx", x.toFixed(2));
        dot.setAttribute("cy", y.toFixed(2));
        dot.setAttribute("r", "4.4");
        dot.setAttribute("fill", item.color);
        dot.setAttribute("fill-opacity", "0.95");
        dot.setAttribute("stroke", "#ffffff");
        dot.setAttribute("stroke-width", "1.05");
        dot.setAttribute("cursor", "pointer");
        dot.addEventListener("mouseenter", () => showTooltip(item));
        dot.addEventListener("mouseleave", clearTooltip);
        dot.addEventListener("click", () => window.location.href = item.target_url);
        svg.appendChild(dot);
      }}

      const [lx, ly] = polar(cx, cy, outerR + 54, mid);
      const label = document.createElementNS(NS, "text");
      label.setAttribute("x", lx.toFixed(2));
      label.setAttribute("y", ly.toFixed(2));
      label.setAttribute("fill", "#223245");
      label.setAttribute("font-size", "16");
      label.setAttribute("font-weight", "700");
      label.setAttribute("letter-spacing", "0.01em");
      label.setAttribute("text-anchor", Math.cos(mid) >= 0 ? "start" : "end");
      label.setAttribute("alignment-baseline", "middle");
      label.setAttribute("cursor", "pointer");
      label.textContent = item.phylum;
      label.addEventListener("mouseenter", () => showTooltip(item));
      label.addEventListener("mouseleave", clearTooltip);
      label.addEventListener("click", () => window.location.href = item.target_url);
      svg.appendChild(label);
    }});

    const centerOuter = document.createElementNS(NS, "circle");
    centerOuter.setAttribute("cx", cx);
    centerOuter.setAttribute("cy", cy);
    centerOuter.setAttribute("r", "120");
    centerOuter.setAttribute("fill", "rgba(255,255,255,0.92)");
    centerOuter.setAttribute("stroke", "#d7d0c4");
    centerOuter.setAttribute("stroke-width", "1.4");
    svg.appendChild(centerOuter);

    const centerTitle = document.createElementNS(NS, "text");
    centerTitle.setAttribute("x", cx);
    centerTitle.setAttribute("y", cy - 10);
    centerTitle.setAttribute("text-anchor", "middle");
    centerTitle.setAttribute("font-size", "42");
    centerTitle.setAttribute("font-weight", "800");
    centerTitle.setAttribute("fill", "#233242");
    centerTitle.textContent = "Taxon";
    svg.appendChild(centerTitle);

    const centerArrow = document.createElementNS(NS, "text");
    centerArrow.setAttribute("x", cx);
    centerArrow.setAttribute("y", cy + 26);
    centerArrow.setAttribute("text-anchor", "middle");
    centerArrow.setAttribute("font-size", "24");
    centerArrow.setAttribute("font-weight", "700");
    centerArrow.setAttribute("fill", "#607181");
    centerArrow.textContent = "→ MAG";
    svg.appendChild(centerArrow);

    const centerSub = document.createElementNS(NS, "text");
    centerSub.setAttribute("x", cx);
    centerSub.setAttribute("y", cy + 56);
    centerSub.setAttribute("text-anchor", "middle");
    centerSub.setAttribute("font-size", "14");
    centerSub.setAttribute("fill", "#6a7885");
    centerSub.textContent = "Phylum-centered entry";
    svg.appendChild(centerSub);
  </script>
</body>
</html>
"""


def main() -> None:
    stats = fetch_phylum_stats()
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(build_html(stats), encoding="utf-8")
    print(f"wrote {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
