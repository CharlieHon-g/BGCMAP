from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from scripts.pg_script_helper import open_db, pg_query, pg_query_one


ROOT = Path(__file__).resolve().parents[1]
SPIRE_FULL = ROOT / "spire_full_scape_env.tsv"
COUNTRIES_GEOJSON = ROOT / "assets" / "maps" / "countries_named.geojson"
OUTPUT_DIR = ROOT / "outputs" / "maps"
HTML_OUT = OUTPUT_DIR / "sample_global_distribution_multilevel.html"
SUMMARY_TSV = OUTPUT_DIR / "sample_global_distribution_multilevel_summary.tsv"
FILTERS_JSON = OUTPUT_DIR / "sample_global_distribution_filters.json"

REGION_COLORS = {
    "North America": "#d55d3e",
    "South America": "#e8923e",
    "Europe": "#4f7d39",
    "Africa": "#d2a72e",
    "Asia": "#a64d79",
    "Oceania": "#7a4cc2",
    "Antarctica": "#b0c4d8",
    "Pacific Ocean": "#2d6cdf",
    "Atlantic Ocean": "#1d9a8a",
    "Indian Ocean": "#0f8c5a",
    "Arctic Ocean": "#7b8fd1",
    "Unknown": "#9aa0a6",
}

REGION_ORDER = [
    "North America",
    "South America",
    "Europe",
    "Africa",
    "Asia",
    "Oceania",
    "Antarctica",
    "Pacific Ocean",
    "Atlantic Ocean",
    "Indian Ocean",
    "Arctic Ocean",
]

BOARD_CENTERS = {
    "North America": (-100, 42),
    "South America": (-58, -14),
    "Europe": (16, 52),
    "Africa": (20, 4),
    "Asia": (96, 34),
    "Oceania": (135, -24),
    "Antarctica": (0, -82),
    "Pacific Ocean": (-150, 4),
    "Atlantic Ocean": (-32, 8),
    "Indian Ocean": (82, -18),
    "Arctic Ocean": (0, 76),
}

MARINE_KEYWORDS = (
    "marine",
    "ocean",
    "sea",
    "seawater",
    "coastal",
    "pelagic",
    "reef",
    "coral",
    "estuary",
    "hydrothermal",
)


def parse_float(raw: str) -> Optional[float]:
    text = (raw or "").strip()
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def clean_text(raw: str) -> Optional[str]:
    text = (raw or "").strip()
    return text or None


def is_marine(group3: Optional[str]) -> bool:
    if not group3:
        return False
    lowered = group3.lower()
    return any(token in lowered for token in MARINE_KEYWORDS)


def classify_ocean(lat: float, lon: float) -> str:
    if lat >= 66:
        return "Arctic Ocean"
    if 20 <= lon < 147 and -50 < lat < 30:
        return "Indian Ocean"
    if -100 <= lon < 60 and -60 < lat < 66:
        return "Atlantic Ocean"
    return "Pacific Ocean"


def classify_continent(lat: float, lon: float) -> str:
    if lat < -60:
        return "Antarctica"
    if lon <= -30:
        return "North America" if lat > 8 else "South America"
    if lon <= 45 and lat >= 35:
        return "Europe"
    if -20 <= lon < 55 and -35 <= lat < 35:
        return "Africa"
    if lon >= 110 and lat <= 10:
        return "Oceania"
    return "Asia"


def build_sample_records() -> List[dict]:
    conn = open_db()
    rows = pg_query(conn, """
        SELECT sample_id, latitude, longitude, biome3
        FROM sample
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
    """)
    conn.close()
    return [
        {
            "sample_id": row["sample_id"],
            "lat": row["latitude"],
            "lon": row["longitude"],
            "group3": row["biome3"],
            "species": None,
            "marine_hint": is_marine(row["biome3"]),
        }
        for row in rows
    ]


def ring_contains(point: Tuple[float, float], ring: List[List[float]]) -> bool:
    x, y = point
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def polygon_contains(point: Tuple[float, float], polygon: List[List[List[float]]]) -> bool:
    if not polygon:
        return False
    if not ring_contains(point, polygon[0]):
        return False
    for hole in polygon[1:]:
        if ring_contains(point, hole):
            return False
    return True


def ring_signed_area(ring: List[List[float]]) -> float:
    if len(ring) < 3:
        return 0.0
    area = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def ring_centroid(ring: List[List[float]]) -> List[float]:
    if len(ring) < 3:
        return ring[0] if ring else [0.0, 0.0]
    area_factor = 0.0
    cx = 0.0
    cy = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        cross = x1 * y2 - x2 * y1
        area_factor += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(area_factor) < 1e-12:
        xs = [pt[0] for pt in ring]
        ys = [pt[1] for pt in ring]
        return [sum(xs) / len(xs), sum(ys) / len(ys)]
    return [cx / (3.0 * area_factor), cy / (3.0 * area_factor)]


def representative_point_for_polygon(polygon: List[List[List[float]]]) -> List[float]:
    if not polygon or not polygon[0]:
        return [0.0, 0.0]
    outer = polygon[0]
    centroid = ring_centroid(outer)
    if polygon_contains((centroid[0], centroid[1]), polygon):
        return centroid
    bbox = bbox_of_polygon(polygon)
    min_lon, min_lat = bbox[0]
    max_lon, max_lat = bbox[1]
    steps = 24
    best = None
    center_lon = (min_lon + max_lon) / 2
    center_lat = (min_lat + max_lat) / 2
    for i in range(steps + 1):
        lon = min_lon + (max_lon - min_lon) * i / steps
        for j in range(steps + 1):
            lat = min_lat + (max_lat - min_lat) * j / steps
            if not polygon_contains((lon, lat), polygon):
                continue
            score = (lon - center_lon) ** 2 + (lat - center_lat) ** 2
            if best is None or score < best[0]:
                best = (score, [lon, lat])
    if best:
        return best[1]
    return outer[0]


def bbox_of_polygon(polygon: List[List[List[float]]]) -> List[List[float]]:
    xs = []
    ys = []
    for ring in polygon:
        for lon, lat in ring:
            xs.append(lon)
            ys.append(lat)
    return [[min(xs), min(ys)], [max(xs), max(ys)]]


def build_country_index(countries_geojson: dict) -> List[dict]:
    country_index: List[dict] = []
    for feature in countries_geojson["features"]:
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates") or []
        geom_type = geometry.get("type")
        polygons = coords if geom_type == "MultiPolygon" else [coords]
        bboxes = [bbox_of_polygon(poly) for poly in polygons if poly]
        props = feature.get("properties") or {}
        if bboxes:
            min_lon = min(b[0][0] for b in bboxes)
            min_lat = min(b[0][1] for b in bboxes)
            max_lon = max(b[1][0] for b in bboxes)
            max_lat = max(b[1][1] for b in bboxes)
            largest_polygon = max(polygons, key=lambda poly: abs(ring_signed_area(poly[0])) if poly and poly[0] else 0.0)
            centroid_ll = representative_point_for_polygon(largest_polygon)
        else:
            centroid_ll = [0, 0]
        inferred_continent = "Asia" if props.get("name") == "Israel" else classify_continent(centroid_ll[1], centroid_ll[0])
        country_index.append(
            {
                "name": props.get("name"),
                "continent": inferred_continent,
                "centroid_ll": centroid_ll,
                "polygons": polygons,
                "bboxes": bboxes,
            }
        )
    return country_index


def point_in_bbox(point: Tuple[float, float], bbox: List[List[float]]) -> bool:
    lon, lat = point
    return bbox[0][0] <= lon <= bbox[1][0] and bbox[0][1] <= lat <= bbox[1][1]


def assign_country(point: Tuple[float, float], country_index: List[dict]) -> Optional[dict]:
    for country in country_index:
        for bbox, polygon in zip(country["bboxes"], country["polygons"]):
            if not point_in_bbox(point, bbox):
                continue
            if polygon_contains(point, polygon):
                return country
    return None


def enrich_samples(samples: List[dict], country_index: List[dict]) -> List[dict]:
    enriched = []
    for row in samples:
        lat = row["lat"]
        lon = row["lon"]
        if lat is None or lon is None:
            continue
        point = (lon, lat)
        country = assign_country(point, country_index)
        marine = bool(row["marine_hint"] and country is None)
        country_continent = (
            "Asia" if country and country["name"] == "Israel"
            else country["continent"] if country and country.get("continent")
            else None
        )
        board = classify_ocean(lat, lon) if marine else (country_continent or classify_continent(lat, lon))
        if board not in REGION_ORDER:
            board = classify_ocean(lat, lon) if marine else classify_continent(lat, lon)
        enriched.append(
            {
                **row,
                "marine": marine,
                "country": country["name"] if country else None,
                "continent": "Asia" if country and country["name"] == "Israel" else (country["continent"] if country else (None if marine else classify_continent(lat, lon))),
                "country_centroid_ll": country["centroid_ll"] if country else None,
                "board": board,
            }
        )
    return enriched


def build_board_summary(samples: List[dict]) -> Counter:
    region_counter = Counter()
    for row in samples:
        region_counter[row["board"]] += 1
    return region_counter


def build_filter_payload(samples: List[dict]) -> dict:
    payload: Dict[str, dict] = {}
    board_bucket: Dict[str, List[str]] = {}
    country_bucket: Dict[str, List[str]] = {}
    ocean_bucket: Dict[str, List[str]] = {}
    ocean_range_bucket: Dict[str, List[str]] = {}
    for row in samples:
        board_bucket.setdefault(row["board"], []).append(row["sample_id"])
        if row["marine"]:
            ocean_bucket.setdefault(row["board"], []).append(row["sample_id"])
            lat_bin = math_floor_bin(row["lat"], 10)
            lon_bin = math_floor_bin(row["lon"], 10)
            ocean_range_bucket.setdefault(
                f"ocean-range::{row['board']}::{lat_bin}::{lat_bin + 10}::{lon_bin}::{lon_bin + 10}",
                [],
            ).append(row["sample_id"])
        elif row["country"]:
            country_bucket.setdefault(row["country"], []).append(row["sample_id"])

    for board, sample_ids in board_bucket.items():
        payload[f"board::{board}"] = {"label": board, "kind": "board", "sample_ids": sample_ids}
    for country, sample_ids in country_bucket.items():
        payload[f"country::{country}"] = {"label": country, "kind": "country", "sample_ids": sample_ids}
    for ocean, sample_ids in ocean_bucket.items():
        payload[f"ocean::{ocean}"] = {"label": ocean, "kind": "ocean", "sample_ids": sample_ids}
    for ocean_range, sample_ids in ocean_range_bucket.items():
        payload[ocean_range] = {"label": ocean_range, "kind": "ocean-range", "sample_ids": sample_ids}
    return payload


def math_floor_bin(value: float, step: int) -> int:
    return int(value // step) * step


def write_summary(total_samples: int, geocoded_samples: int, board_counts: Counter) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with SUMMARY_TSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(["metric", "value"])
        writer.writerow(["total_unique_samples", total_samples])
        writer.writerow(["geocoded_samples", geocoded_samples])
        writer.writerow(["samples_missing_coordinates", total_samples - geocoded_samples])
        for region in REGION_ORDER:
            writer.writerow([region, board_counts.get(region, 0)])


def build_html(samples: List[dict], board_counts: Counter, countries_geojson: dict) -> str:
    geocoded = sum(1 for row in samples if row["lat"] is not None and row["lon"] is not None)
    board_cards = []
    for region in REGION_ORDER:
        board_cards.append(
            f"""
            <article class="board-card">
              <div class="board-label">{region}</div>
              <div class="board-value">{board_counts.get(region, 0):,}</div>
            </article>
            """
        )

    lightweight_samples = [
        {
            "sample_id": row["sample_id"],
            "lat": row["lat"],
            "lon": row["lon"],
            "group3": row["group3"],
            "species": row["species"],
            "marine": row["marine"],
            "board": row["board"],
            "country": row["country"],
            "continent": row["continent"],
            "country_centroid_ll": row["country_centroid_ll"],
        }
        for row in samples
    ]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Global Sample Distribution Map</title>
  <script src="/static/assets/maps/d3.min.js"></script>
  <style>
    :root {{
      --bg: #f4f1ea;
      --panel: rgba(252, 250, 246, 0.94);
      --ink: #233242;
      --muted: #64748b;
      --line: #d7d3c7;
      --land: #eadfc8;
      --ocean: #d6e8f1;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      color: var(--ink);
      background: linear-gradient(180deg, #f6f3ed 0%, #eef4f7 100%);
    }}
    .page {{
      max-width: 1540px;
      margin: 0 auto;
      padding: 26px;
    }}
    .hero {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 30px;
      padding: 26px 28px;
      box-shadow: 0 20px 55px rgba(35, 50, 66, 0.08);
    }}
    .eyebrow {{
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      color: var(--muted);
      margin-bottom: 10px;
    }}
    h1 {{
      margin: 0 0 10px;
      font-size: 40px;
      line-height: 1.04;
    }}
    .lede {{
      max-width: 1060px;
      margin: 0;
      font-size: 18px;
      line-height: 1.65;
      color: #334155;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
      margin-top: 20px;
    }}
    .stat-card, .board-card {{
      background: rgba(255,255,255,0.62);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 16px 18px;
    }}
    .stat-label, .board-label {{
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.11em;
      color: var(--muted);
    }}
    .stat-value, .board-value {{
      margin-top: 10px;
      font-size: 28px;
      font-weight: 700;
    }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 2.3fr) minmax(330px, 1fr);
      gap: 18px;
      margin-top: 18px;
    }}
    .map-panel, .side-panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 30px;
      padding: 18px 18px 22px;
      box-shadow: 0 20px 55px rgba(35, 50, 66, 0.08);
    }}
    .map-panel h2, .side-panel h2 {{
      margin: 0 0 8px;
      font-size: 22px;
    }}
    .map-panel p, .side-panel p {{
      margin: 0 0 14px;
      line-height: 1.58;
      color: #475569;
    }}
    #map-root {{
      position: relative;
      min-height: 760px;
      border: 1px solid var(--line);
      border-radius: 24px;
      overflow: hidden;
      background: linear-gradient(180deg, #d8ebf2 0%, #d1e5ee 100%);
    }}
    .map-controls {{
      position: absolute;
      top: 16px;
      right: 16px;
      z-index: 5;
      display: inline-flex;
      gap: 8px;
      padding: 10px;
      background: rgba(249,248,244,0.92);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: 0 12px 30px rgba(35, 50, 66, 0.12);
      backdrop-filter: blur(8px);
    }}
    .map-controls button {{
      border: 1px solid #c7c0b1;
      background: #ffffff;
      color: var(--ink);
      border-radius: 12px;
      min-width: 40px;
      height: 40px;
      font-size: 18px;
      font-weight: 700;
      cursor: pointer;
    }}
    .map-controls button:hover {{
      background: #f3efe6;
    }}
    .map-guide {{
      position: absolute;
      top: 18px;
      left: 18px;
      z-index: 4;
      max-width: 390px;
      padding: 12px 14px;
      background: rgba(249,248,244,0.92);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: 0 12px 30px rgba(35, 50, 66, 0.10);
      color: #334155;
      font-size: 13px;
      line-height: 1.5;
      backdrop-filter: blur(8px);
    }}
    svg {{
      display: block;
      width: 100%;
      height: auto;
    }}
    .tooltip {{
      position: absolute;
      left: 18px;
      bottom: 18px;
      width: min(390px, calc(100% - 36px));
      padding: 16px 18px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(249,248,244,0.96);
      box-shadow: 0 15px 40px rgba(35, 50, 66, 0.16);
      display: none;
      backdrop-filter: blur(8px);
    }}
    .tooltip.is-visible {{ display: block; }}
    .tooltip h3 {{
      margin: 0 0 8px;
      font-size: 18px;
    }}
    .tooltip p {{
      margin: 6px 0;
      font-size: 14px;
      line-height: 1.5;
      color: #334155;
    }}
    .boards {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-top: 14px;
    }}
    .board-section {{
      margin-top: 18px;
      padding-top: 14px;
      border-top: 1px dashed var(--line);
    }}
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 16px;
      margin-top: 14px;
      color: #334155;
      font-size: 13px;
    }}
    .legend-item {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }}
    .legend-swatch {{
      width: 12px;
      height: 12px;
      border-radius: 999px;
      display: inline-block;
    }}
    @media (max-width: 1140px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 720px) {{
      .page {{ padding: 16px; }}
      h1 {{ font-size: 30px; }}
      .stats, .boards {{ grid-template-columns: 1fr; }}
      #map-root {{ min-height: 560px; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <div class="eyebrow">Global Sample Map</div>
      <h1>Multi-level global distribution of GEM-BGC samples</h1>
      <p class="lede">This map follows a strict hierarchical display strategy. At the world view, all samples are merged into five continental boards and four oceanic boards. After zooming in, land samples transition directly to country-level nodes, while the four ocean boards remain visible as stable marine anchors. Sample counts remain available in the tooltip instead of driving node size.</p>
      <div class="stats">
        <article class="stat-card">
          <div class="stat-label">Unique samples</div>
          <div class="stat-value">{len(samples):,}</div>
        </article>
        <article class="stat-card">
          <div class="stat-label">Geocoded samples</div>
          <div class="stat-value">{geocoded:,}</div>
        </article>
        <article class="stat-card">
          <div class="stat-label">Missing coordinates</div>
          <div class="stat-value">{len(samples) - geocoded:,}</div>
        </article>
      </div>
    </section>

    <section class="layout">
      <article class="map-panel">
        <h2>Zoomable board-to-country view</h2>
        <p>World view now shows exactly nine macro-boards. Zoom in to inspect countries on land, while the four ocean points remain visible and fixed in marine space. Country-level aggregation is the deepest land display layer, preventing repeated coordinate nodes from overwhelming the map. Hover or click any node to inspect sample counts, habitats, and representative taxa.</p>
        <div id="map-root">
          <div class="map-guide">Use the mouse wheel or the <strong>+</strong>/<strong>-</strong> buttons to zoom. Drag to pan. Click any node to zoom, then use the tooltip action to open the filtered Sample module.</div>
          <div class="map-controls">
            <button id="zoom-in" type="button" aria-label="Zoom in">+</button>
            <button id="zoom-out" type="button" aria-label="Zoom out">-</button>
            <button id="zoom-reset" type="button" aria-label="Reset zoom">⟳</button>
          </div>
          <div id="tooltip" class="tooltip"></div>
        </div>
        <div class="legend">
          <span class="legend-item"><span class="legend-swatch" style="background:#5971b2"></span>Land-associated samples</span>
          <span class="legend-item"><span class="legend-swatch" style="background:#2f7fa3"></span>Marine-associated samples</span>
          <span class="legend-item">Node size is fixed within each zoom layer</span>
        </div>
      </article>

      <aside class="side-panel">
        <h2>Board summary</h2>
        <p>Boards are fixed entry regions for the home-page map. Countries are inferred from coordinates using world country polygons, and all land samples are merged to a single country-level node in the deepest view. Marine samples remain grouped at the ocean level to avoid misleading overlaps near coastlines or continents, and ocean points stay visible after zooming.</p>
        <div class="boards">
          {''.join(board_cards)}
        </div>
        <div class="board-section">
          <h2>Zoom logic</h2>
          <p><strong>World view:</strong> five continents and four oceans</p>
          <p><strong>Zoomed view:</strong> countries on land, four oceans at sea</p>
          <p><strong>Deepest layer:</strong> still country-level on land to avoid repeated coordinate points</p>
        </div>
      </aside>
    </section>
  </div>

  <script id="countries-data" type="application/json">{json.dumps(countries_geojson, ensure_ascii=False, separators=(',', ':'))}</script>
  <script id="samples-data" type="application/json">{json.dumps(lightweight_samples, ensure_ascii=False, separators=(',', ':'))}</script>
  <script>
    const REGION_COLORS = {json.dumps(REGION_COLORS, ensure_ascii=False)};
    const REGION_ORDER = {json.dumps(REGION_ORDER, ensure_ascii=False)};
    const BOARD_CENTERS = {json.dumps(BOARD_CENTERS, ensure_ascii=False)};
    const countriesGeo = JSON.parse(document.getElementById('countries-data').textContent);
    const samples = JSON.parse(document.getElementById('samples-data').textContent);
    const root = document.getElementById('map-root');
    const tooltip = document.getElementById('tooltip');
    const zoomInButton = document.getElementById('zoom-in');
    const zoomOutButton = document.getElementById('zoom-out');
    const zoomResetButton = document.getElementById('zoom-reset');

    const width = root.clientWidth || 980;
    const height = Math.max(560, Math.round(width * 0.58));

    const svg = d3.select('#map-root')
      .append('svg')
      .attr('viewBox', `0 0 ${{width}} ${{height}}`)
      .attr('preserveAspectRatio', 'xMidYMid meet');

    svg.append('rect')
      .attr('x', 0)
      .attr('y', 0)
      .attr('width', width)
      .attr('height', height)
      .attr('fill', '#d8ebf2');

    const baseLayer = svg.append('g');
    const pointLayer = svg.append('g');

    const projection = d3.geoNaturalEarth1()
      .fitExtent([[18, 18], [width - 18, height - 18]], countriesGeo);
    const path = d3.geoPath(projection);

    const countryFeatures = countriesGeo.features.map((feature) => {{
      const bounds = d3.geoBounds(feature);
      const centroid = projection(d3.geoCentroid(feature));
      const name = feature.properties.name;
      let continent = 'Asia';
      const c0 = centroid ? centroid[0] : 0;
      const c1 = centroid ? centroid[1] : 0;
      const center = projection.invert([c0, c1]);
      const lon = center ? center[0] : 0;
      const lat = center ? center[1] : 0;
      if (lon < -25) continent = 'Americas';
      else if (lon < 45 && lat >= 35) continent = 'Europe';
      else if (lon < 55 && lat >= -35 && lat < 35) continent = 'Africa';
      else if (lon >= 110 && lat <= 10) continent = 'Oceania';
      return {{
        ...feature,
        properties: {{
          ...feature.properties,
          continent,
          centroid: centroid || [width / 2, height / 2],
          bounds
        }}
      }};
    }});

    const enrichedSamples = samples.map(sample => ({{
      ...sample,
      countryCentroid: sample.country_centroid_ll ? projection(sample.country_centroid_ll) : null,
    }}));

    function lonBetween(lon, minLon, maxLon) {{
      if (minLon <= maxLon) return lon >= minLon && lon <= maxLon;
      return lon >= minLon || lon <= maxLon;
    }}

    function inferMarineSubregion(board, lat, lon) {{
      if (board === 'Atlantic Ocean') {{
        if (lonBetween(lon, 8, 32) && lat >= 53 && lat <= 66) return 'Baltic Sea';
        if (lonBetween(lon, -5, 10) && lat >= 48 && lat <= 63) return 'North Sea';
        if (lonBetween(lon, -15, 20) && lat >= 62 && lat <= 80) return 'Norwegian Sea';
        if (lonBetween(lon, -6, 37) && lat >= 30 && lat <= 46) return 'Mediterranean Sea';
        if (lonBetween(lon, -99, -79) && lat >= 18 && lat <= 31) return 'Gulf of Mexico';
        if (lonBetween(lon, -88, -58) && lat >= 8 && lat <= 28) return 'Caribbean Sea';
        if (lonBetween(lon, -80, 15) && lat >= 35 && lat < 62) return 'North Atlantic';
        if (lonBetween(lon, -55, 20) && lat >= -5 && lat < 15) return 'Equatorial Atlantic';
        if (lonBetween(lon, -70, 25) && lat < -5) return 'South Atlantic';
        return 'Atlantic Ocean board';
      }}
      if (board === 'Pacific Ocean') {{
        if (lonBetween(lon, 103, 122) && lat >= -2 && lat <= 24) return 'South China Sea';
        if (lonBetween(lon, 122, 131) && lat >= 24 && lat <= 33) return 'East China Sea';
        if (lonBetween(lon, 127, 142) && lat >= 33 && lat <= 52) return 'Sea of Japan';
        if (lonBetween(lon, 123, 150) && lat >= 5 && lat <= 30) return 'Philippine Sea';
        if (lonBetween(lon, 146, 166) && lat >= -30 && lat <= 0) return 'Coral Sea';
        if (lonBetween(lon, 145, 170) && lat >= -48 && lat < -28) return 'Tasman Sea';
        if (lonBetween(lon, 160, -157) && lat >= 50 && lat <= 68) return 'Bering Sea';
        if (lonBetween(lon, -170, -100) && lat >= 0 && lat <= 35) return 'Eastern North Pacific';
        if (lonBetween(lon, 135, -70) && lat >= 25) return 'North Pacific';
        if (lonBetween(lon, 140, -70) && lat < -5) return 'South Pacific';
        if (lonBetween(lon, 150, -90) && lat >= -5 && lat < 25) return 'Equatorial Pacific';
        return 'Pacific Ocean board';
      }}
      if (board === 'Indian Ocean') {{
        if (lonBetween(lon, 45, 78) && lat >= 5 && lat <= 28) return 'Arabian Sea';
        if (lonBetween(lon, 78, 100) && lat >= 5 && lat <= 24) return 'Bay of Bengal';
        if (lonBetween(lon, 92, 100) && lat >= 4 && lat <= 18) return 'Andaman Sea';
        if (lonBetween(lon, 95, 125) && lat >= -15 && lat <= 10) return 'Eastern Indian Ocean';
        if (lonBetween(lon, 20, 120) && lat < -20) return 'Southern Indian Ocean';
        if (lonBetween(lon, 45, 100) && lat >= -20 && lat < 5) return 'Central Indian Ocean';
        return 'Indian Ocean board';
      }}
      if (board === 'Arctic Ocean') {{
        if (lonBetween(lon, 15, 70) && lat >= 68) return 'Barents Sea';
        if (lonBetween(lon, -25, 15) && lat >= 68) return 'Greenland Sea';
        if (lonBetween(lon, 70, 110) && lat >= 68) return 'Kara Sea';
        return 'Arctic Ocean';
      }}
      return board;
    }}

    function aggregateBoard(samples) {{
      const bucket = new Map();
      for (const s of samples) {{
        const key = s.board;
        if (!bucket.has(key)) {{
          bucket.set(key, {{ key, region: s.board, count: 0, samples: [], lats: [], lons: [], species: new Map(), habitats: new Map() }});
        }}
        const item = bucket.get(key);
        item.count += 1;
        item.samples.push(s.sample_id);
        item.lats.push(s.lat);
        item.lons.push(s.lon);
        if (s.species) item.species.set(s.species, (item.species.get(s.species) || 0) + 1);
        if (s.group3) item.habitats.set(s.group3, (item.habitats.get(s.group3) || 0) + 1);
      }}
      return REGION_ORDER.map(region => {{
        const item = bucket.get(region) || {{ count: 0, samples: [], species: new Map(), habitats: new Map() }};
        const center = BOARD_CENTERS[region] || [0, 0];
        return {{
          kind: 'board',
          region,
          label: region,
          count: item.count,
          lat: center[1],
          lon: center[0],
          radius: 13,
          color: REGION_COLORS[region] || REGION_COLORS.Unknown,
          filterId: `board::${{region}}`,
          sampleUrl: `/sample.html?map_filter=${{encodeURIComponent(`board::${{region}}`)}}`,
          rangeLatMin: item.lats.length ? d3.min(item.lats) : null,
          rangeLatMax: item.lats.length ? d3.max(item.lats) : null,
          rangeLonMin: item.lons.length ? d3.min(item.lons) : null,
          rangeLonMax: item.lons.length ? d3.max(item.lons) : null,
          topSpecies: Array.from(item.species.entries()).sort((a,b) => b[1]-a[1]).slice(0,3).map(d => d[0]),
          topHabitats: Array.from(item.habitats.entries()).sort((a,b) => b[1]-a[1]).slice(0,3).map(d => d[0]),
          preview: item.samples.slice(0,6)
        }};
      }});
    }}

    function aggregateCountryAndOceanRanges(samples) {{
      const bucket = new Map();
      for (const s of samples) {{
        let key, lat, lon, label, region;
        if (s.marine) {{
          const latBin = Math.floor(s.lat / 8) * 8;
          const lonBin = Math.floor(s.lon / 8) * 8;
          key = `ocean-range|${{s.board}}|${{latBin}}|${{lonBin}}`;
          lon = s.lon;
          lat = s.lat;
          const subregion = inferMarineSubregion(s.board, s.lat, s.lon);
          label = `${{subregion}} (${{s.board}} board; ${{latBin}} to ${{latBin + 8}}, ${{lonBin}} to ${{lonBin + 8}})`;
          region = s.board;
        }} else {{
          key = `country|${{s.country || 'Unassigned'}}`;
          const centroid = s.countryCentroid || projection([s.lon, s.lat]);
          const ll = projection.invert(centroid);
          lat = ll[1];
          lon = ll[0];
          label = s.country || 'Unassigned country';
          region = s.continent || 'Unknown';
        }}
        if (!bucket.has(key)) {{
          bucket.set(key, {{ key, label, region, lat, lon, count: 0, samples: [], lats: [], lons: [], species: new Map(), habitats: new Map() }});
        }}
        const item = bucket.get(key);
        item.count += 1;
        item.samples.push(s.sample_id);
        item.lats.push(s.lat);
        item.lons.push(s.lon);
        if (s.species) item.species.set(s.species, (item.species.get(s.species) || 0) + 1);
        if (s.group3) item.habitats.set(s.group3, (item.habitats.get(s.group3) || 0) + 1);
      }}
      return Array.from(bucket.values()).map(item => {{
        const isCountry = item.key.startsWith('country|');
        const rangeLatMin = item.lats.length ? d3.min(item.lats) : null;
        const rangeLatMax = item.lats.length ? d3.max(item.lats) : null;
        const rangeLonMin = item.lons.length ? d3.min(item.lons) : null;
        const rangeLonMax = item.lons.length ? d3.max(item.lons) : null;
        let lat = item.lat;
        let lon = item.lon;
        if (!isCountry && item.lats.length) {{
          const meanLat = d3.mean(item.lats);
          const meanLon = d3.mean(item.lons);
          let bestIdx = 0;
          let bestScore = Number.POSITIVE_INFINITY;
          item.lats.forEach((sampleLat, idx) => {{
            const sampleLon = item.lons[idx];
            const score = Math.pow(sampleLat - meanLat, 2) + Math.pow(sampleLon - meanLon, 2);
            if (score < bestScore) {{
              bestScore = score;
              bestIdx = idx;
            }}
          }});
          lat = item.lats[bestIdx];
          lon = item.lons[bestIdx];
        }}
        return {{
          kind: isCountry ? 'country' : 'ocean-range',
          label: item.label,
          region: item.region,
          count: item.count,
          lat,
          lon,
          radius: isCountry ? 4.2 : 3.8,
          color: REGION_COLORS[item.region] || REGION_COLORS.Unknown,
          filterId: isCountry
            ? `country::${{item.label}}`
            : `ocean-range::${{item.region}}::${{rangeLatMin.toFixed(3)}}::${{rangeLatMax.toFixed(3)}}::${{rangeLonMin.toFixed(3)}}::${{rangeLonMax.toFixed(3)}}`,
          sampleUrl: isCountry
            ? `/sample.html?map_filter=${{encodeURIComponent(`country::${{item.label}}`)}}`
            : `/sample.html?map_filter=${{encodeURIComponent(`ocean::${{item.region}}`)}}`,
          rangeLatMin,
          rangeLatMax,
          rangeLonMin,
          rangeLonMax,
          topSpecies: Array.from(item.species.entries()).sort((a,b) => b[1]-a[1]).slice(0,3).map(d => d[0]),
          topHabitats: Array.from(item.habitats.entries()).sort((a,b) => b[1]-a[1]).slice(0,3).map(d => d[0]),
          preview: item.samples.slice(0,6)
        }};
      }});
    }}

    const boardNodes = aggregateBoard(enrichedSamples);
    const countryNodes = aggregateCountryAndOceanRanges(enrichedSamples);
    const persistentOceanNodes = boardNodes
      .filter(d => d.region.includes('Ocean'))
      .map(d => ({{
        ...d,
        kind: 'ocean-board',
        radius: 5.8
      }}));

    function currentNodes(k) {{
      if (k < 2.1) return boardNodes;
      return persistentOceanNodes.concat(countryNodes);
    }}

    baseLayer.selectAll('path')
      .data(countryFeatures)
      .join('path')
      .attr('d', path)
      .attr('fill', '#eadfc8')
      .attr('stroke', '#c6baa2')
      .attr('stroke-width', 0.7);

    function showTooltip(d) {{
      const habitats = d.topHabitats.length ? d.topHabitats.join(', ') : 'NA';
      const species = d.topSpecies.length ? d.topSpecies.join(', ') : 'NA';
      const preview = d.preview.length ? d.preview.join(', ') : 'NA';
      const nodeScope = d.kind === 'board'
        ? 'Board'
        : (d.kind === 'country' ? 'Country' : (d.kind === 'ocean-board' ? 'Ocean' : 'Ocean range'));
      const coordinateText = `${{Number(d.lat).toFixed(3)}}, ${{Number(d.lon).toFixed(3)}}`;
      const rangeText = (d.rangeLatMin == null || d.rangeLonMin == null)
        ? 'NA'
        : `lat ${{Number(d.rangeLatMin).toFixed(3)}} to ${{Number(d.rangeLatMax).toFixed(3)}}; lon ${{Number(d.rangeLonMin).toFixed(3)}} to ${{Number(d.rangeLonMax).toFixed(3)}}`;
      tooltip.innerHTML = `
        <h3>${{d.label}}</h3>
        <p><strong>Level:</strong> ${{nodeScope}}</p>
        <p><strong>Region:</strong> ${{d.region}}</p>
        <p><strong>Representative coordinate:</strong> ${{coordinateText}}</p>
        <p><strong>Merged coordinate range:</strong> ${{rangeText}}</p>
        <p><strong>Sample count:</strong> ${{d.count.toLocaleString()}}</p>
        <p><strong>Top habitats:</strong> ${{habitats}}</p>
        <p><strong>Representative taxa:</strong> ${{species}}</p>
        <p><strong>Sample preview:</strong> ${{preview}}</p>
        <p><a href="${{d.sampleUrl}}" style="display:inline-block;margin-top:6px;padding:8px 12px;border-radius:10px;border:1px solid #c7c0b1;background:#fff3; text-decoration:none;color:#233242;font-weight:600;">Open filtered samples</a></p>
      `;
      tooltip.classList.add('is-visible');
    }}

    function zoomToNode(event, d) {{
      const targetScale = d.kind === 'board'
        ? 3.2
        : 6.2;
      const [x, y] = projection([d.lon, d.lat]);
      const transform = d3.zoomIdentity
        .translate(width / 2, height / 2)
        .scale(targetScale)
        .translate(-x, -y);
      svg.transition().duration(500).call(zoom.transform, transform);
      showTooltip(d);
    }}

    function renderNodes(k) {{
      const fillColor = (d) => d.color || REGION_COLORS[d.region] || REGION_COLORS.Unknown;
      const displayRadius = (d) => {{
        if (d.kind === 'board') return d.radius;
        if (d.kind === 'ocean-board') return Math.max(3.8, d.radius / Math.sqrt(Math.max(k, 1)));
        const floor = d.kind === 'ocean-range' ? 2.8 : 2.1;
        return Math.max(floor, d.radius / Math.sqrt(Math.max(k, 1)));
      }};
      const nodes = currentNodes(k).map(d => ({{
        ...d,
        xy: projection([d.lon, d.lat])
      }})).sort((a, b) => {{
        const weight = (node) => node.kind === 'ocean-board' ? 0 : (node.kind === 'ocean-range' ? 1 : (node.kind === 'country' ? 2 : 3));
        return weight(a) - weight(b);
      }});

      if (k >= 2.1) {{
        const landNodes = nodes.filter(d => d.kind === 'country');
        for (let pass = 0; pass < 20; pass += 1) {{
          for (let i = 0; i < landNodes.length; i += 1) {{
            for (let j = i + 1; j < landNodes.length; j += 1) {{
              const a = landNodes[i];
              const b = landNodes[j];
              const dx = b.xy[0] - a.xy[0];
              const dy = b.xy[1] - a.xy[1];
              const dist = Math.hypot(dx, dy) || 0.001;
              const minDist = displayRadius(a) + displayRadius(b) + 1.6;
              if (dist >= minDist) continue;
              const push = (minDist - dist) / 2;
              const ux = dx / dist;
              const uy = dy / dist;
              a.xy[0] -= ux * push;
              a.xy[1] -= uy * push;
              b.xy[0] += ux * push;
              b.xy[1] += uy * push;
            }}
          }}
        }}
      }}

      pointLayer.selectAll('circle')
        .data(nodes, d => d.filterId || `${{d.kind}}|${{d.label}}|${{d.lon}}|${{d.lat}}`)
        .join(
          enter => enter.append('circle')
            .attr('cx', d => d.xy[0])
            .attr('cy', d => d.xy[1])
            .attr('r', d => displayRadius(d))
            .attr('fill', d => fillColor(d))
            .style('fill', d => fillColor(d))
            .attr('fill-opacity', d => (d.kind === 'ocean-range' || d.kind === 'ocean-board') ? 0.95 : 0.92)
            .attr('stroke', '#ffffff')
            .attr('stroke-width', d => (d.kind === 'ocean-range' || d.kind === 'ocean-board') ? 1.1 : 0.85)
            .style('vector-effect', 'non-scaling-stroke')
            .on('mouseenter', (_, d) => showTooltip(d))
            .on('mouseleave', () => tooltip.classList.remove('is-visible'))
            .on('click', zoomToNode),
          update => update
            .on('click', zoomToNode)
            .attr('cx', d => d.xy[0])
            .attr('cy', d => d.xy[1])
            .attr('r', d => displayRadius(d))
            .attr('fill', d => fillColor(d))
            .style('fill', d => fillColor(d))
            .attr('fill-opacity', d => (d.kind === 'ocean-range' || d.kind === 'ocean-board') ? 0.95 : 0.92)
            .attr('stroke-width', d => (d.kind === 'ocean-range' || d.kind === 'ocean-board') ? 1.1 : 0.85)
            .style('vector-effect', 'non-scaling-stroke'),
          exit => exit.remove()
        );
    }}

    renderNodes(1);

    const zoom = d3.zoom()
      .scaleExtent([1, 10])
      .on('zoom', (event) => {{
        const transform = event.transform;
        baseLayer.attr('transform', transform);
        pointLayer.attr('transform', transform);
        renderNodes(transform.k);
      }});

    svg.call(zoom);
    zoomInButton.addEventListener('click', () => {{
      svg.transition().duration(250).call(zoom.scaleBy, 1.5);
    }});
    zoomOutButton.addEventListener('click', () => {{
      svg.transition().duration(250).call(zoom.scaleBy, 1 / 1.5);
    }});
    zoomResetButton.addEventListener('click', () => {{
      svg.transition().duration(350).call(zoom.transform, d3.zoomIdentity);
      tooltip.classList.remove('is-visible');
    }});
  </script>
</body>
</html>
"""


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    countries_geojson = json.loads(COUNTRIES_GEOJSON.read_text(encoding="utf-8"))
    country_index = build_country_index(countries_geojson)
    raw_samples = build_sample_records()
    samples = enrich_samples(raw_samples, country_index)
    board_counts = build_board_summary(samples)
    write_summary(len(raw_samples), len(samples), board_counts)
    FILTERS_JSON.write_text(
        json.dumps(build_filter_payload(samples), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    HTML_OUT.write_text(build_html(samples, board_counts, countries_geojson), encoding="utf-8")
    print(f"wrote {HTML_OUT}")
    print(f"wrote {SUMMARY_TSV}")
    print(f"wrote {FILTERS_JSON}")


if __name__ == "__main__":
    main()
