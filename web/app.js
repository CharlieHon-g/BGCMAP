const qs = (selector, root = document) => root.querySelector(selector);
const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];
let params = new URLSearchParams(window.location.search);
const taxExpandedRows = new Set();
let taxExpandAll = false;

function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "NA";
  if (typeof value === "number") return value.toLocaleString();
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toLocaleString() : value;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setActiveNav() {
  const page = document.body.dataset.page;
  qsa(".top-nav a").forEach((link) => {
    if (link.dataset.page === page) link.classList.add("is-active");
  });
}

async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function initHomeCarousel() {
  const shell = qs("#home-carousel-shell");
  const track = qs("#home-carousel-track");
  const slides = qsa(".carousel-slide", shell || document);
  const dotsRoot = qs("#home-carousel-dots");
  const prev = qs("#carousel-prev");
  const next = qs("#carousel-next");
  if (!shell || !track || !slides.length || !prev || !next) return;

  let active = 0;
  let autoplay;
  let resumeTimeout;

  const render = (index) => {
    active = (index + slides.length) % slides.length;
    const prevIdx = (active - 1 + slides.length) % slides.length;
    const nextIdx = (active + 1) % slides.length;

    slides.forEach((slide, i) => {
      slide.classList.remove("is-prev", "is-active", "is-next");
      if (i === active) slide.classList.add("is-active");
      else if (i === prevIdx) slide.classList.add("is-prev");
      else if (i === nextIdx) slide.classList.add("is-next");
    });

    if (dotsRoot) {
      qsa("button", dotsRoot).forEach((dot, dotIndex) => {
        dot.classList.toggle("is-active", dotIndex === active);
      });
    }
  };

  const clearTimers = () => {
    clearInterval(autoplay);
    clearTimeout(resumeTimeout);
  };

  const startAutoplay = () => {
    clearTimers();
    autoplay = setInterval(() => render(active + 1), 5000);
  };

  const pauseAutoplay = () => {
    clearTimers();
  };

  const scheduleResume = () => {
    clearTimers();
    resumeTimeout = setTimeout(startAutoplay, 5000);
  };

  const userInteract = () => {
    pauseAutoplay();
    scheduleResume();
  };

  if (dotsRoot) {
    dotsRoot.innerHTML = slides
      .map((_, index) => `<button type="button" aria-label="Go to slide ${index + 1}" data-slide="${index}"></button>`)
      .join("");
    qsa("button", dotsRoot).forEach((dot) => {
      dot.addEventListener("click", () => {
        render(Number(dot.dataset.slide || 0));
        userInteract();
      });
    });
  }
  prev.addEventListener("click", () => {
    render(active - 1);
    userInteract();
  });
  next.addEventListener("click", () => {
    render(active + 1);
    userInteract();
  });
  shell.addEventListener("mouseover", (e) => {
    if (e.target.closest(".carousel-slide")) pauseAutoplay();
  });
  shell.addEventListener("mouseout", (e) => {
    if (!e.target.closest(".carousel-slide")) scheduleResume();
  });

  render(0);
  startAutoplay();
}

function buildPager(meta, onNavigate) {
  const pager = document.createElement("div");
  pager.className = "pager";
  pager.innerHTML = `
    <div class="table-meta">Showing ${meta.start} to ${meta.end} of ${formatNumber(meta.total)} entries</div>
    <div class="pager-controls">
      <button class="secondary" ${meta.has_prev ? "" : "disabled"}>Previous</button>
      <span>Page ${meta.page}</span>
      <button ${meta.has_next ? "" : "disabled"}>Next</button>
    </div>
  `;
  const [prev, next] = qsa("button", pager);
  prev.addEventListener("click", () => meta.has_prev && onNavigate(meta.page - 1));
  next.addEventListener("click", () => meta.has_next && onNavigate(meta.page + 1));
  return pager;
}

function renderTable(target, columns, rows, rowBuilder, options = {}) {
  const table = document.createElement("table");
  if (options.tableClass) table.className = options.tableClass;
  const headerHtml = columns
    .map((col) => {
      if (typeof col === "string") return `<th>${escapeHtml(col)}</th>`;
      const label = escapeHtml(col.label || "");
      if (!col.sortKey) return `<th>${label}</th>`;
      const active = options.sortState?.field === col.sortKey;
      const dir = active ? options.sortState?.dir : "";
      const arrow = active ? (dir === "desc" ? "▼" : "▲") : "▾";
      return `
        <th>
          <button type="button" class="sort-header${active ? " is-active" : ""}" data-sort-key="${escapeHtml(col.sortKey)}" data-sort-dir="${escapeHtml(dir || "none")}">
            <span>${label}</span>
            <span class="sort-arrow">${arrow}</span>
          </button>
        </th>
      `;
    })
    .join("");
  table.innerHTML = `
    ${Array.isArray(options.columnWidths) && options.columnWidths.length
      ? `<colgroup>${options.columnWidths.map((width) => `<col style="width:${width}">`).join("")}</colgroup>`
      : ""}
    <thead>
      <tr>${headerHtml}</tr>
    </thead>
    <tbody></tbody>
  `;
  const tbody = qs("tbody", table);
  rows.forEach((row) => {
    const built = rowBuilder(row);
    const tr = document.createElement("tr");
    if (typeof built === "string") {
      tr.innerHTML = built;
      tbody.appendChild(tr);
      return;
    }
    tr.innerHTML = built.cells || "";
    tbody.appendChild(tr);
    if (built.detail) {
      const tpl = document.createElement("template");
      tpl.innerHTML = built.detail.trim();
      const detailNode = tpl.content.firstElementChild;
      if (detailNode) tbody.appendChild(detailNode);
    }
  });
  target.innerHTML = "";
  target.appendChild(table);
  if (typeof options.onSort === "function") {
    qsa(".sort-header", table).forEach((button) => {
      button.addEventListener("click", () => {
        const key = button.dataset.sortKey || "";
        const currentDir = button.dataset.sortDir || "none";
        const nextDir = currentDir === "asc" ? "desc" : "asc";
        options.onSort(key, nextDir);
      });
    });
  }
}

function updateEntriesLabel(meta, node) {
  node.textContent = `Showing ${meta.start} to ${meta.end} of ${formatNumber(meta.total)} entries`;
}
function showLoading(node) {
  node.innerHTML = '<span class="loading-indicator">Loading<span class="loading-dots">...</span></span>';
}

function makeExternalLink(href, label) {
  return href ? `<a href="${href}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>` : `<span class="subtle">${escapeHtml(label)}</span>`;
}

function makeLocalLink(href, label) {
  return href ? `<a href="${href}">${escapeHtml(label)}</a>` : `<span class="subtle">${escapeHtml(label)}</span>`;
}

function sortRowsByNullableNumber(rows, field, dir, tieKey) {
  const present = [];
  const missing = [];
  rows.forEach((row) => {
    const raw = row?.[field];
    const number = raw === null || raw === undefined || raw === "" ? null : Number(raw);
    if (number === null || Number.isNaN(number)) missing.push(row);
    else present.push({ row, number });
  });
  present.sort((a, b) => String(a.row?.[tieKey] || "").localeCompare(String(b.row?.[tieKey] || "")));
  present.sort((a, b) => (dir === "desc" ? b.number - a.number : a.number - b.number));
  missing.sort((a, b) => String(a?.[tieKey] || "").localeCompare(String(b?.[tieKey] || "")));
  return [...present.map((item) => item.row), ...missing];
}

function ellipsisText(value, fallback = "NA") {
  const text = value === null || value === undefined || value === "" ? fallback : String(value);
  return `<span class="cell-ellipsis" title="${escapeHtml(text)}">${escapeHtml(text)}</span>`;
}

function ellipsisLink(href, label, fallback = "NA") {
  const text = label === null || label === undefined || label === "" ? fallback : String(label);
  if (!href) return `<span class="cell-ellipsis subtle" title="${escapeHtml(text)}">${escapeHtml(text)}</span>`;
  const ext = href.startsWith("http") ? ' target="_blank" rel="noreferrer"' : "";
  return `<a class="cell-ellipsis cell-ellipsis-link" href="${href}"${ext} title="${escapeHtml(text)}">${escapeHtml(text)}</a>`;
}

function normalizeNumericIdLabel(value) {
  if (value === null || value === undefined || value === "") return "NA";
  const text = String(value).trim();
  const prefixed = text.match(/(?:^|_)(\d+)$/);
  if (prefixed) return String(Number(prefixed[1]));
  if (/^\d+$/.test(text)) return String(Number(text));
  return text;
}

function buildTaxonomyTitle(row) {
  const parts = [
    ["Domain", row.domain],
    ["Phylum", row.phylum],
    ["Class", row.class_name],
    ["Order", row.order_name],
    ["Family", row.family],
    ["Genus", row.genus],
    ["Species", row.species_lineage || row.species],
  ];
  return parts
    .map(([label, value]) => `${label}: ${value || "NA"}`)
    .join("\n");
}

function buildTaxonomyEntries(row) {
  return [
    ["Domain", row.domain],
    ["Phylum", row.phylum],
    ["Class", row.class_name],
    ["Order", row.order_name],
    ["Family", row.family],
    ["Genus", row.genus],
    ["Species", row.species_lineage || row.species],
  ];
}

function buildTaxonomyInline(row) {
  return buildTaxonomyEntries(row)
    .map(
      ([rank, value]) => `
        <span class="taxonomy-inline-segment">
          <span class="taxonomy-inline-rank">${escapeHtml(rank)}:</span>
          <span class="taxonomy-inline-value">${escapeHtml(value || "NA")}</span>
        </span>
      `
    )
    .join('<span class="taxonomy-inline-sep">·</span>');
}

function renderTaxonomyDisclosure(row, label, target) {
  const rowKey = row.bgc_name || row.genome_id || `${row.sample_id || "sample"}-${label}`;
  const expanded = taxExpandAll || taxExpandedRows.has(rowKey);
  const chipText = `<span class="taxon-chip-text" title="${escapeHtml(label)}">${escapeHtml(label)}</span>`;
  const chip = target
    ? `<a class="taxon-chip" href="${target}" target="_blank" rel="noreferrer">${chipText}</a>`
    : `<span class="taxon-chip">${chipText}</span>`;
  return `
    <div class="taxon-disclosure ${expanded ? "is-open" : ""}" data-tax-row="${escapeHtml(rowKey)}">
      <div class="taxon-head">
        <button type="button" class="taxonomy-toggle ${expanded ? "is-open" : ""}" data-tax-toggle="${escapeHtml(rowKey)}" aria-expanded="${expanded ? "true" : "false"}" aria-label="${expanded ? "Collapse taxonomy" : "Expand taxonomy"}"><span class="toggle-caret">▸</span></button>
        ${chip}
      </div>
    </div>
  `;
}

function renderTaxonomyDetailRow(row, label, colspan) {
  const rowKey = row.bgc_name || row.genome_id || `${row.sample_id || "sample"}-${label}`;
  const expanded = taxExpandAll || taxExpandedRows.has(rowKey);
  return `
    <tr class="taxonomy-detail-row"${expanded ? "" : " hidden"} data-tax-detail-row="${escapeHtml(rowKey)}">
      <td colspan="${colspan}">
        <div class="taxonomy-detail-inline">${buildTaxonomyInline(row)}</div>
      </td>
    </tr>
  `;
}

function syncTaxonomyDisclosureState() {
  qsa(".taxon-disclosure").forEach((node) => {
    const rowKey = node.dataset.taxRow || "";
    const expanded = taxExpandAll || taxExpandedRows.has(rowKey);
    node.classList.toggle("is-open", expanded);
    const button = qs(".taxonomy-toggle", node);
    if (button) {
      button.classList.toggle("is-open", expanded);
      button.setAttribute("aria-expanded", expanded ? "true" : "false");
      button.setAttribute("aria-label", expanded ? "Collapse taxonomy" : "Expand taxonomy");
    }
  });
  qsa(".taxonomy-detail-row").forEach((node) => {
    const rowKey = node.dataset.taxDetailRow || "";
    const expanded = taxExpandAll || taxExpandedRows.has(rowKey);
    node.hidden = !expanded;
  });
  const toggle = qs("#tax-expand-toggle");
  if (toggle) {
    toggle.classList.toggle("is-open", taxExpandAll);
    toggle.querySelector(".toggle-label")?.replaceChildren(document.createTextNode(taxExpandAll ? "Collapse all lineages" : "Expand all lineages"));
  }
}

function collapseAllTaxonomyPanels() {
  taxExpandAll = false;
  taxExpandedRows.clear();
  syncTaxonomyDisclosureState();
}

function bindTaxonomyDisclosureControls() {
  const globalToggle = qs("#tax-expand-toggle");
  if (globalToggle) {
    globalToggle.onclick = (event) => {
      event.preventDefault();
      event.stopPropagation();
      taxExpandAll = !taxExpandAll;
      if (!taxExpandAll) taxExpandedRows.clear();
      syncTaxonomyDisclosureState();
    };
  }

  qsa(".taxonomy-toggle").forEach((button) => {
    button.onclick = (event) => {
      event.preventDefault();
      event.stopPropagation();
      const rowKey = button.dataset.taxToggle || "";
      if (taxExpandAll) {
        taxExpandAll = false;
        taxExpandedRows.clear();
        qsa(".taxonomy-toggle").forEach((btn) => {
          const key = btn.dataset.taxToggle;
          if (key) taxExpandedRows.add(key);
        });
      }
      if (taxExpandedRows.has(rowKey)) taxExpandedRows.delete(rowKey);
      else taxExpandedRows.add(rowKey);
      syncTaxonomyDisclosureState();
    };
  });
  syncTaxonomyDisclosureState();
}

function bestTaxonLabel(row) {
  return row.species_lineage || row.species || row.genus || row.phylum || "Unclassified";
}

function normalizeContigEdge(contigEdge) {
  if (contigEdge === 1 || contigEdge === "1" || contigEdge === true) return 1;
  if (contigEdge === 0 || contigEdge === "0" || contigEdge === false) return 0;
  return null;
}

function membershipDisplay(value, contigEdge, fallbackStatus = "") {
  const numeric = value === null || value === undefined || value === "" ? null : Number(value);
  const edge = normalizeContigEdge(contigEdge);
  let label = fallbackStatus || "unassigned";
  let klass = "good";

  if (numeric !== null && !Number.isNaN(numeric)) {
    if (numeric >= 0.4) {
      label = "peripheral";
      klass = "warn";
    } else if (edge === 0) {
      label = "core";
      klass = "good";
    } else if (edge === 1) {
      label = "assigned";
      klass = "info";
    } else if (fallbackStatus) {
      label = fallbackStatus;
      klass = fallbackStatus.toLowerCase().includes("peripheral") ? "warn" : fallbackStatus.toLowerCase().includes("assigned") ? "info" : "good";
    }
  }

  const text = numeric === null || Number.isNaN(numeric) ? label : `${label}: ${numeric.toFixed(4)}`;
  return { label, klass, text };
}

function makeMembershipBadge(value, contigEdge, fallbackStatus = "") {
  const display = membershipDisplay(value, contigEdge, fallbackStatus);
  const klass = `badge ${display.klass}`;
  const text = display.text;
  return `<span class="${klass}">${escapeHtml(text)}</span>`;
}

function percent(part, whole) {
  const p = Number(part) || 0;
  const w = Number(whole) || 0;
  if (!w) return "0.0";
  return ((p / w) * 100).toFixed(1);
}

function renderListBars(node, rows, valueKey = "value", labelKey = "label") {
  if (!node) return;
  const max = Math.max(...rows.map((row) => Number(row[valueKey]) || 0), 1);
  node.innerHTML = rows
    .map(
      (row) => `
        <div class="list-bar">
          <div class="list-bar-head">
            <span>${escapeHtml(row[labelKey])}</span>
            <strong>${formatNumber(row[valueKey])}</strong>
          </div>
          <div class="list-bar-track"><span style="width:${Math.max(4, ((Number(row[valueKey]) || 0) / max) * 100)}%"></span></div>
        </div>
      `
    )
    .join("");
}

function renderSparkBars(node, rows) {
  if (!node) return;
  const max = Math.max(...rows.map((row) => Number(row.value) || 0), 1);
  node.innerHTML = rows
    .map(
      (row) => `
        <div class="spark-col">
          <div class="spark-value">${formatNumber(row.value)}</div>
          <div class="spark-bar" style="height:${Math.max(12, ((Number(row.value) || 0) / max) * 180)}px"></div>
          <div class="spark-label">${escapeHtml(row.label)}</div>
        </div>
      `
    )
    .join("");
}

const GROUP_LABELS = {
  A: "aquatic environment",
  A1: "marine/saline water environment",
  A2: "fresh water environment",
  A3: "groundwater environment",
  A4: "special aquatic environment",
  B: "terrestrial environment",
  B1: "natural terrestrial environment",
  B2: "soil environment",
  B3: "cave/subterranean environment",
  C: "artificial/engineered environment",
  C1: "agriculture/aquaculture environment",
  C2: "industrial/treatment facilities",
  C3: "building/urban environment",
  C4: "other artificial environment",
  D: "host-associated environment",
  D1: "animal host (internal/surface)",
  D2: "plant-associated environment",
  D3: "microbe-associated environment",
  D4: "food/feed environment",
  E: "special/extreme environment",
  E1: "high temperature/geothermal environment",
  E2: "contaminated/degraded environment",
  E3: "artificial simulation environment",
  F: "other environment",
  F1: "mixed/composite environment",
  F2: "developmental stage",
  F3: "process environment",
};

function canonicalizeGroupLabel(value) {
  return String(value || "")
    .trim()
    .replaceAll("_", " ")
    .replace(/\s*\/\s*/g, "/")
    .replace(/\s+/g, " ")
    .toLowerCase();
}

const GROUP_LABELS_REVERSE = Object.fromEntries(
  Object.entries(GROUP_LABELS).map(([code, label]) => [canonicalizeGroupLabel(label), code])
);

function normalizeGroupInput(value) {
  return String(value || "").trim();
}

function displayGroupLabel(label) {
  if (!label) return "NA";
  return String(label).replaceAll("_", " ");
}

const BIOME_DROPDOWN_OPERATORS = new Set(["equals"]);
const GEO_DROPDOWN_OPERATORS = new Set(["equals"]);
const GEO_ALL_OPERATORS = new Set(["equals", "not_equals", "is_null", "is_not_null"]);
const TAXON_DROPDOWN_OPERATORS = new Set(["equals"]);
const TAXON_LEVELS = [
  { key: "domain", label: "Domain" },
  { key: "phylum", label: "Phylum" },
  { key: "class_name", label: "Class" },
  { key: "order_name", label: "Order" },
  { key: "genus", label: "Genus" },
  { key: "species", label: "Species" },
];
const TAXON_DESCENDANTS = {
  domain: ["phylum", "class_name", "order_name", "genus", "species"],
  phylum: ["class_name", "order_name", "genus", "species"],
  class_name: ["order_name", "genus", "species"],
  order_name: ["genus", "species"],
  genus: ["species"],
  species: [],
};
let biomeOptionsCache = {
  biome1: [],
  biome2_all: [],
  biome3_all: [],
  biome2_by_biome1: {},
  biome3_by_biome1: {},
  biome3_by_biome2: {},
};
let biomeOptionsPromise = null;
let taxonOptionsCache = {
  domain_all: [],
  phylum_all: [],
  class_all: [],
  order_all: [],
  genus_all: [],
  species_all: [],
  phylum_by_domain: {},
  class_by_domain: {},
  class_by_phylum: {},
  order_by_domain: {},
  order_by_phylum: {},
  order_by_class_name: {},
  genus_by_domain: {},
  genus_by_phylum: {},
  genus_by_class_name: {},
  genus_by_order_name: {},
  species_by_domain: {},
  species_by_phylum: {},
  species_by_class_name: {},
  species_by_order_name: {},
  species_by_genus: {},
};
let taxonOptionsPromise = null;
let taxonOptionsLoaded = false;

async function ensureBiomeOptions() {
  if (biomeOptionsPromise) return biomeOptionsPromise;
  biomeOptionsPromise = getJSON("/api/biome-options")
    .then((payload) => {
      biomeOptionsCache = {
        biome1: payload?.biome1 || [],
        biome2_all: payload?.biome2_all || [],
        biome3_all: payload?.biome3_all || [],
        biome2_by_biome1: payload?.biome2_by_biome1 || {},
        biome3_by_biome1: payload?.biome3_by_biome1 || {},
        biome3_by_biome2: payload?.biome3_by_biome2 || {},
      };
      return biomeOptionsCache;
    })
    .catch(() => biomeOptionsCache);
  return biomeOptionsPromise;
}

function isBiomeField(fieldKey) {
  return fieldKey === "biome1" || fieldKey === "biome2" || fieldKey === "biome3";
}

let categoryOptionsCache = [];
let categoryOptionsPromise = null;
function ensureCategoryOptions() {
  if (categoryOptionsPromise) return categoryOptionsPromise;
  categoryOptionsPromise = getJSON("/api/category-options")
    .then((data) => { categoryOptionsCache = data.categories || []; return categoryOptionsCache; })
    .catch(() => categoryOptionsCache);
  return categoryOptionsPromise;
}
function isCategoryField(fieldKey) { return fieldKey === "category"; }

function isGeoField(fieldKey) {
  return fieldKey === "geo_region";
}

let geoOptionsCache = { boards: [], countries_by_board: {} };
let geoOptionsPromise = null;

async function ensureGeoOptions() {
  if (geoOptionsPromise) return geoOptionsPromise;
  geoOptionsPromise = getJSON("/api/geo-options")
    .then((payload) => {
      geoOptionsCache = {
        boards: payload?.boards || [],
        countries_by_board: payload?.countries_by_board || {},
      };
      return geoOptionsCache;
    })
    .catch(() => geoOptionsCache);
  return geoOptionsPromise;
}

async function ensureTaxonOptions() {
  if (taxonOptionsPromise) return taxonOptionsPromise;
  taxonOptionsPromise = getJSON("/api/taxon-options")
    .then((payload) => {
      taxonOptionsCache = {
        domain_all: payload?.domain_all || [],
        phylum_all: payload?.phylum_all || [],
        class_all: payload?.class_all || [],
        order_all: payload?.order_all || [],
        genus_all: payload?.genus_all || [],
        species_all: payload?.species_all || [],
        phylum_by_domain: payload?.phylum_by_domain || {},
        class_by_domain: payload?.class_by_domain || {},
        class_by_phylum: payload?.class_by_phylum || {},
        order_by_domain: payload?.order_by_domain || {},
        order_by_phylum: payload?.order_by_phylum || {},
        order_by_class_name: payload?.order_by_class_name || {},
        genus_by_domain: payload?.genus_by_domain || {},
        genus_by_phylum: payload?.genus_by_phylum || {},
        genus_by_class_name: payload?.genus_by_class_name || {},
        genus_by_order_name: payload?.genus_by_order_name || {},
        species_by_domain: payload?.species_by_domain || {},
        species_by_phylum: payload?.species_by_phylum || {},
        species_by_class_name: payload?.species_by_class_name || {},
        species_by_order_name: payload?.species_by_order_name || {},
        species_by_genus: payload?.species_by_genus || {},
      };
      taxonOptionsLoaded = true;
      return taxonOptionsCache;
    })
    .catch(() => taxonOptionsCache);
  return taxonOptionsPromise;
}

function isTaxonField(fieldKey) {
  return fieldKey === "taxon";
}

function makeTaxonValue(raw = {}) {
  return {
    domain: raw?.domain || "",
    phylum: raw?.phylum || "",
    class_name: raw?.class_name || "",
    order_name: raw?.order_name || "",
    genus: raw?.genus || "",
    species: raw?.species || "",
  };
}

function taxonValueHasSelection(taxonValue) {
  const taxon = makeTaxonValue(taxonValue);
  return TAXON_LEVELS.some((level) => String(taxon[level.key] || "").trim());
}

function resolveTaxonRawValue(inputValue, options) {
  const term = String(inputValue || "").trim().toLowerCase();
  if (!term) return null;
  for (const option of options || []) {
    const raw = String(option || "").trim();
    if (term === raw.toLowerCase()) return raw;
  }
  return null;
}

function taxonAllOptions(rankKey) {
  if (rankKey === "domain") return taxonOptionsCache.domain_all || [];
  if (rankKey === "phylum") return taxonOptionsCache.phylum_all || [];
  if (rankKey === "class_name") return taxonOptionsCache.class_all || [];
  if (rankKey === "order_name") return taxonOptionsCache.order_all || [];
  if (rankKey === "genus") return taxonOptionsCache.genus_all || [];
  return taxonOptionsCache.species_all || [];
}

function resolvedTaxonSelections(taxonValue) {
  const taxon = makeTaxonValue(taxonValue);
  const domain = resolveTaxonRawValue(taxon.domain, taxonOptionsCache.domain_all);
  const phylumPool = domain ? (taxonOptionsCache.phylum_by_domain?.[domain] || []) : taxonOptionsCache.phylum_all || [];
  const phylum = resolveTaxonRawValue(taxon.phylum, phylumPool.length ? phylumPool : taxonOptionsCache.phylum_all);
  const classPool = phylum
    ? (taxonOptionsCache.class_by_phylum?.[phylum] || [])
    : domain
      ? (taxonOptionsCache.class_by_domain?.[domain] || [])
      : (taxonOptionsCache.class_all || []);
  const className = resolveTaxonRawValue(taxon.class_name, classPool.length ? classPool : taxonOptionsCache.class_all);
  const orderPool = className
    ? (taxonOptionsCache.order_by_class_name?.[className] || [])
    : phylum
      ? (taxonOptionsCache.order_by_phylum?.[phylum] || [])
      : domain
        ? (taxonOptionsCache.order_by_domain?.[domain] || [])
        : (taxonOptionsCache.order_all || []);
  const orderName = resolveTaxonRawValue(taxon.order_name, orderPool.length ? orderPool : taxonOptionsCache.order_all);
  const genusPool = orderName
    ? (taxonOptionsCache.genus_by_order_name?.[orderName] || [])
    : className
      ? (taxonOptionsCache.genus_by_class_name?.[className] || [])
      : phylum
        ? (taxonOptionsCache.genus_by_phylum?.[phylum] || [])
        : domain
          ? (taxonOptionsCache.genus_by_domain?.[domain] || [])
          : (taxonOptionsCache.genus_all || []);
  const genus = resolveTaxonRawValue(taxon.genus, genusPool.length ? genusPool : taxonOptionsCache.genus_all);
  const speciesPool = genus
    ? (taxonOptionsCache.species_by_genus?.[genus] || [])
    : orderName
      ? (taxonOptionsCache.species_by_order_name?.[orderName] || [])
      : className
        ? (taxonOptionsCache.species_by_class_name?.[className] || [])
        : phylum
          ? (taxonOptionsCache.species_by_phylum?.[phylum] || [])
          : domain
            ? (taxonOptionsCache.species_by_domain?.[domain] || [])
            : (taxonOptionsCache.species_all || []);
  const species = resolveTaxonRawValue(taxon.species, speciesPool.length ? speciesPool : taxonOptionsCache.species_all);
  return { domain, phylum, class_name: className, order_name: orderName, genus, species };
}

function getTaxonDropdownOptions(taxonValue, rankKey) {
  const resolved = resolvedTaxonSelections(taxonValue);
  if (rankKey === "domain") return taxonOptionsCache.domain_all || [];
  if (rankKey === "phylum") {
    if (resolved.domain) return taxonOptionsCache.phylum_by_domain?.[resolved.domain] || [];
    return taxonOptionsCache.phylum_all || [];
  }
  if (rankKey === "class_name") {
    if (resolved.phylum) return taxonOptionsCache.class_by_phylum?.[resolved.phylum] || [];
    if (resolved.domain) return taxonOptionsCache.class_by_domain?.[resolved.domain] || [];
    return taxonOptionsCache.class_all || [];
  }
  if (rankKey === "order_name") {
    if (resolved.class_name) return taxonOptionsCache.order_by_class_name?.[resolved.class_name] || [];
    if (resolved.phylum) return taxonOptionsCache.order_by_phylum?.[resolved.phylum] || [];
    if (resolved.domain) return taxonOptionsCache.order_by_domain?.[resolved.domain] || [];
    return taxonOptionsCache.order_all || [];
  }
  if (rankKey === "genus") {
    if (resolved.order_name) return taxonOptionsCache.genus_by_order_name?.[resolved.order_name] || [];
    if (resolved.class_name) return taxonOptionsCache.genus_by_class_name?.[resolved.class_name] || [];
    if (resolved.phylum) return taxonOptionsCache.genus_by_phylum?.[resolved.phylum] || [];
    if (resolved.domain) return taxonOptionsCache.genus_by_domain?.[resolved.domain] || [];
    return taxonOptionsCache.genus_all || [];
  }
  if (resolved.genus) return taxonOptionsCache.species_by_genus?.[resolved.genus] || [];
  if (resolved.order_name) return taxonOptionsCache.species_by_order_name?.[resolved.order_name] || [];
  if (resolved.class_name) return taxonOptionsCache.species_by_class_name?.[resolved.class_name] || [];
  if (resolved.phylum) return taxonOptionsCache.species_by_phylum?.[resolved.phylum] || [];
  if (resolved.domain) return taxonOptionsCache.species_by_domain?.[resolved.domain] || [];
  return taxonOptionsCache.species_all || [];
}

function taxonOptionIsSelected(option, currentValue) {
  const term = String(currentValue || "").trim().toLowerCase();
  if (!term) return false;
  return term === String(option || "").trim().toLowerCase();
}

function clearTaxonDescendants(rule, rankKey) {
  const next = makeTaxonValue(rule.taxon);
  for (const key of TAXON_DESCENDANTS[rankKey] || []) {
    next[key] = "";
  }
  rule.taxon = next;
}

function biomeOptionLabel(value) {
  return displayGroupLabel(value);
}

function resolveBiomeRawValue(inputValue, options) {
  const term = String(inputValue || "").trim().toLowerCase();
  if (!term) return null;
  for (const option of options || []) {
    const raw = String(option || "").trim();
    const pretty = biomeOptionLabel(option).trim();
    if (term === raw.toLowerCase() || term === pretty.toLowerCase()) return raw;
  }
  return null;
}

function collectBiomeSelections(node, fieldKey, bucket) {
  if (!node || typeof node !== "object") return;
  if (node.type === "rule") {
    if (node.field === fieldKey && BIOME_DROPDOWN_OPERATORS.has(node.operator) && String(node.value || "").trim()) {
      bucket.push(String(node.value || "").trim());
    }
    return;
  }
  for (const child of node.rules || []) collectBiomeSelections(child, fieldKey, bucket);
}

function getUniqueBiomeSelection(pageKey, fieldKey) {
  const state = getFilterState(pageKey);
  const rawSelections = [];
  collectBiomeSelections(state, fieldKey, rawSelections);
  const candidatePool =
    fieldKey === "biome1"
      ? biomeOptionsCache.biome1
      : fieldKey === "biome2"
        ? biomeOptionsCache.biome2_all
        : biomeOptionsCache.biome3_all;
  const resolved = [...new Set(rawSelections.map((value) => resolveBiomeRawValue(value, candidatePool)).filter(Boolean))];
  return resolved.length === 1 ? resolved[0] : null;
}

function getBiomeDropdownOptions(pageKey, rule) {
  if (!isBiomeField(rule.field)) return [];
  if (rule.field === "biome1") return biomeOptionsCache.biome1 || [];
  if (rule.field === "biome2") {
    const selectedBiome1 = getUniqueBiomeSelection(pageKey, "biome1");
    if (selectedBiome1) return biomeOptionsCache.biome2_by_biome1?.[selectedBiome1] || [];
    return biomeOptionsCache.biome2_all || [];
  }
  const selectedBiome2 = getUniqueBiomeSelection(pageKey, "biome2");
  if (selectedBiome2) return biomeOptionsCache.biome3_by_biome2?.[selectedBiome2] || [];
  const selectedBiome1 = getUniqueBiomeSelection(pageKey, "biome1");
  if (selectedBiome1) return biomeOptionsCache.biome3_by_biome1?.[selectedBiome1] || [];
  return biomeOptionsCache.biome3_all || [];
}

function biomeOptionIsSelected(option, currentValue) {
  const term = String(currentValue || "").trim().toLowerCase();
  if (!term) return false;
  return term === String(option || "").trim().toLowerCase() || term === biomeOptionLabel(option).trim().toLowerCase();
}

function shortenGroupLabel(label, maxLength = 26) {
  const value = displayGroupLabel(label);
  return value.length > maxLength ? `${value.slice(0, maxLength - 3)}...` : value;
}

function renderHierarchyCombined(node, hierarchy) {
  if (!node) return;
  const group1Rows = hierarchy.group1_rows || [];
  const group2Rows = hierarchy.group2_rows || [];
  const links12 = hierarchy.links_12 || [];
  const links23 = hierarchy.links_23 || [];
  const width = 1880;
  const leftX = 28;
  const midX = 430;
  const rightX = 812;
  const group1W = 270;
  const group2W = 270;
  const blockW = 1030;
  const headerY = 32;
  const topY = 72;
  const gap = 18;
  const maxLink12 = Math.max(...links12.map((item) => Number(item.value) || 0), 1);
  const maxG1 = Math.max(...group1Rows.map((item) => Number(item.value) || 0), 1);
  const groupPalette = {
    A: "#2b6e9c",
    B: "#537d37",
    C: "#a64d79",
    D: "#d0891d",
    E: "#7b5ea7",
    F: "#588a8a",
  };
  const parentMap = {};
  links12.forEach((link) => {
    if (!parentMap[link.target] || Number(link.value) > Number(parentMap[link.target].value)) {
      parentMap[link.target] = { source: link.source, value: Number(link.value) || 0 };
    }
  });

  const blockRows = group2Rows.map((row) => {
    const children = links23
      .filter((link) => link.source === row.label)
      .sort((a, b) => (Number(b.value) || 0) - (Number(a.value) || 0));
    const labelLines = wrapLabelWords(row.label, 24);
    const nodeH = Math.max(56, 18 + labelLines.length * 12 + 14);
    const n = Math.max(children.length, 1);
    const childAreaH = Math.max(96, n * 24 + 10);
    const blockH = 28 + childAreaH + 8;
    const parent = parentMap[row.label]?.source || "F";
    return {
      ...row,
      children,
      blockH,
      childAreaH,
      parent,
      color: groupPalette[parent] || "#5f6f7f",
      labelLines,
      nodeH,
    };
  });

  let cursorY = topY;
  blockRows.forEach((row) => {
    row.y = cursorY;
    row.nodeY = cursorY + Math.max(0, (row.blockH - row.nodeH) / 2);
    cursorY += row.blockH + gap;
  });
  const height = cursorY + 18;
  const group1Step = group1Rows.length > 1 ? (height - topY - 60) / (group1Rows.length - 1) : 0;

  const group1Nodes = group1Rows.map((row, index) => {
    const labelLines = wrapLabelWords(row.label, 22);
    return {
      ...row,
      x: leftX,
      y: topY + index * group1Step,
      width: group1W,
      height: Math.max(64, (Number(row.value) / maxG1) * 96, 18 + labelLines.length * 12 + 18),
      color: groupPalette[row.label] || "#5f6f7f",
      labelLines,
    };
  });

  const group2Nodes = blockRows.map((row) => ({
    ...row,
    x: midX,
    y: row.nodeY,
    width: group2W,
    height: row.nodeH,
  }));

  const g1Lookup = Object.fromEntries(group1Nodes.map((row) => [row.label, row]));
  const g2Lookup = Object.fromEntries(group2Nodes.map((row) => [row.label, row]));

  const svg = [
    `<svg viewBox="0 0 ${width} ${height}" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">`,
    `<rect x="0" y="0" width="${width}" height="${height}" fill="#f7fafc"/>`,
    `<text x="${leftX}" y="${headerY}" font-size="15" font-weight="800" fill="#223548">Group 1</text>`,
    `<text x="${midX}" y="${headerY}" font-size="15" font-weight="800" fill="#223548">Group 2</text>`,
    `<text x="${rightX}" y="${headerY}" font-size="15" font-weight="800" fill="#223548">Group 3 composition within each Group 2 block</text>`,
  ];

  links12.forEach((link) => {
    const source = g1Lookup[link.source];
    const target = g2Lookup[link.target];
    if (!source || !target) return;
    const x1 = source.x + source.width;
    const y1 = source.y + source.height / 2;
    const x2 = target.x;
    const y2 = target.y + target.height / 2;
    const stroke = Math.max(1.2, (Number(link.value) / maxLink12) * 12);
    svg.push(`<path d="M ${x1} ${y1} C ${x1 + 48} ${y1}, ${x2 - 48} ${y2}, ${x2} ${y2}" fill="none" stroke="rgba(43,110,156,0.22)" stroke-width="${stroke.toFixed(1)}"/>`);
  });

  group1Nodes.forEach((row) => {
    svg.push(`<rect x="${row.x}" y="${row.y}" width="${row.width}" height="${row.height}" rx="16" fill="${row.color}" fill-opacity="0.92"/>`);
    row.labelLines.forEach((line, idx) => {
      svg.push(`<text x="${row.x + 12}" y="${row.y + 18 + idx * 12}" font-size="10.8" font-weight="700" fill="#ffffff">${escapeHtml(line)}</text>`);
    });
    svg.push(`<text x="${row.x + 12}" y="${row.y + row.height - 10}" font-size="10.2" fill="rgba(255,255,255,0.90)">${formatNumber(row.value)}</text>`);
  });

  group2Nodes.forEach((row) => {
    svg.push(`<rect x="${row.x}" y="${row.y}" width="${row.width}" height="${row.height}" rx="16" fill="${row.color}" fill-opacity="0.92"/>`);
    row.labelLines.forEach((line, idx) => {
      svg.push(`<text x="${row.x + 12}" y="${row.y + 17 + idx * 12}" font-size="10.0" font-weight="700" fill="#ffffff">${escapeHtml(line)}</text>`);
    });
    svg.push(`<text x="${row.x + 12}" y="${row.y + row.height - 10}" font-size="10" fill="rgba(255,255,255,0.90)">${formatNumber(row.value)}</text>`);

    const lineX1 = row.x + row.width;
    const lineY = row.y + row.height / 2;
    const lineX2 = rightX;
    svg.push(`<path d="M ${lineX1} ${lineY} C ${lineX1 + 28} ${lineY}, ${lineX2 - 28} ${lineY}, ${lineX2} ${row.y + row.blockH / 2}" fill="none" stroke="${row.color}" stroke-opacity="0.34" stroke-width="2.2"/>`);
  });

  blockRows.forEach((row) => {
    const parentColor = row.color;
    svg.push(`<rect x="${rightX}" y="${row.y}" width="${blockW}" height="${row.blockH}" rx="16" fill="${parentColor}" fill-opacity="0.08" stroke="${parentColor}" stroke-opacity="0.24"/>`);
    svg.push(`<rect x="${rightX + 2}" y="${row.y + 2}" width="${blockW - 4}" height="28" rx="14" fill="${parentColor}" fill-opacity="0.92"/>`);
    svg.push(`<text x="${rightX + 12}" y="${row.y + 19}" font-size="11" font-weight="800" fill="#ffffff">${escapeHtml(displayGroupLabel(row.label))}</text>`);
    svg.push(`<text x="${rightX + blockW - 12}" y="${row.y + 19}" text-anchor="end" font-size="10.2" font-weight="700" fill="rgba(255,255,255,0.92)">${formatNumber(row.value)}</text>`);

    const childY0 = row.y + 34;
    const childX = rightX + 8;
    const childW = blockW - 16;
    const childMinH = 18;
    const total = row.children.reduce((sum, child) => sum + (Number(child.value) || 0), 0) || 1;
    const minTotal = row.children.length * childMinH;
    const extra = Math.max(0, row.childAreaH - minTotal);
    let childCursorY = childY0;
    row.children.forEach((child, childIdx) => {
      const childH = childMinH + ((Number(child.value) || 0) / total) * extra;
      const opacity = Math.max(0.22, 0.86 - childIdx * 0.05);
      svg.push(`<rect x="${childX}" y="${childCursorY.toFixed(1)}" width="${childW}" height="${Math.max(childH - 3, 3).toFixed(1)}" rx="10" fill="${parentColor}" fill-opacity="${opacity.toFixed(2)}"/>`);
      svg.push(`<text x="${childX + 10}" y="${(childCursorY + 13).toFixed(1)}" font-size="9.4" font-weight="700" fill="#ffffff">${escapeHtml(displayGroupLabel(child.target))}</text>`);
      svg.push(`<text x="${childX + childW - 10}" y="${(childCursorY + 13).toFixed(1)}" text-anchor="end" font-size="9.2" font-weight="700" fill="rgba(255,255,255,0.92)">${formatNumber(child.value)}</text>`);
      svg.push(`<title>${escapeHtml(displayGroupLabel(row.label))} -> ${escapeHtml(displayGroupLabel(child.target))}: ${formatNumber(child.value)}</title>`);
      childCursorY += childH;
    });
  });

  svg.push(`</svg>`);
  node.innerHTML = svg.join("");
}

function renderTimelineArea(node, rows) {
  if (!node) return;
  const width = 520;
  const height = 320;
  const padL = 36;
  const padR = 16;
  const padT = 16;
  const padB = 44;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;
  const max = Math.max(...rows.map((row) => Number(row.value) || 0), 1);
  const step = rows.length > 1 ? plotW / (rows.length - 1) : 0;
  const points = rows.map((row, idx) => ({
    ...row,
    x: padL + idx * step,
    y: padT + plotH - ((Number(row.value) || 0) / max) * plotH,
  }));
  const line = points.map((p, idx) => `${idx === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
  const area = `${line} L ${(padL + plotW).toFixed(1)} ${(padT + plotH).toFixed(1)} L ${padL.toFixed(1)} ${(padT + plotH).toFixed(1)} Z`;
  node.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
      <rect x="0" y="0" width="${width}" height="${height}" fill="#f7fafc"/>
      <path d="${area}" fill="rgba(43,110,156,0.18)"/>
      <path d="${line}" fill="none" stroke="#2b6e9c" stroke-width="3"/>
      ${points
        .map(
          (p) => `
            <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="4" fill="#2b6e9c"/>
            <text x="${p.x.toFixed(1)}" y="${(p.y - 10).toFixed(1)}" text-anchor="middle" font-size="10.6" font-weight="700" fill="#223548">${formatNumber(p.value)}</text>
            <text x="${p.x.toFixed(1)}" y="${(height - 18).toFixed(1)}" text-anchor="middle" font-size="11" fill="#5f6f7f">${escapeHtml(p.label)}</text>
          `
        )
        .join("")}
    </svg>
  `;
}

function renderPieChart(node, rows) {
  if (!node) return;
  if (!rows || !rows.length) {
    node.innerHTML = '<div class="subtle">No BGC type records available yet.</div>';
    return;
  }
  const colors = [
    "#2b6e9c",
    "#6f97c6",
    "#c68a5a",
    "#7ea35c",
    "#b96e9b",
    "#7f72c7",
    "#6e9f97",
    "#d0a23f",
    "#9a6a55",
  ];
  const total = rows.reduce((sum, row) => sum + (Number(row.value) || 0), 0) || 1;
  const size = 320;
  const cx = 160;
  const cy = 160;
  const radius = 118;
  const innerRadius = 52;
  let startAngle = -Math.PI / 2;

  const slices = rows.map((row, index) => {
    const value = Number(row.value) || 0;
    const angle = (value / total) * Math.PI * 2;
    const endAngle = startAngle + angle;
    const x1 = cx + radius * Math.cos(startAngle);
    const y1 = cy + radius * Math.sin(startAngle);
    const x2 = cx + radius * Math.cos(endAngle);
    const y2 = cy + radius * mathSin(endAngle);
    const x3 = cx + innerRadius * Math.cos(endAngle);
    const y3 = cy + innerRadius * mathSin(endAngle);
    const x4 = cx + innerRadius * Math.cos(startAngle);
    const y4 = cy + innerRadius * mathSin(startAngle);
    const largeArc = angle > Math.PI ? 1 : 0;
    const path = [
      `M ${x1.toFixed(1)} ${y1.toFixed(1)}`,
      `A ${radius} ${radius} 0 ${largeArc} 1 ${x2.toFixed(1)} ${y2.toFixed(1)}`,
      `L ${x3.toFixed(1)} ${y3.toFixed(1)}`,
      `A ${innerRadius} ${innerRadius} 0 ${largeArc} 0 ${x4.toFixed(1)} ${y4.toFixed(1)}`,
      "Z",
    ].join(" ");
    const fill = colors[index % colors.length];
    const pct = ((value / total) * 100).toFixed(1);
    startAngle = endAngle;
    return { path, fill, pct, label: row.label, value };
  });

  node.innerHTML = `
    <div class="pie-card">
      <svg class="pie-svg" viewBox="0 0 ${size} ${size}" xmlns="http://www.w3.org/2000/svg" aria-label="BGC type pie chart">
        <rect x="0" y="0" width="${size}" height="${size}" fill="#f7fafc"/>
        ${slices
          .map(
            (slice) => `
              <path d="${slice.path}" fill="${slice.fill}" stroke="#ffffff" stroke-width="2">
                <title>${escapeHtml(slice.label)}: ${formatNumber(slice.value)} (${slice.pct}%)</title>
              </path>
            `
          )
          .join("")}
        <circle cx="${cx}" cy="${cy}" r="${innerRadius - 2}" fill="#ffffff"/>
        <text x="${cx}" y="${cy - 6}" text-anchor="middle" font-size="16" font-weight="700" fill="#223548">bigscape</text>
        <text x="${cx}" y="${cy + 18}" text-anchor="middle" font-size="16" font-weight="700" fill="#223548">type</text>
      </svg>
      <div class="pie-legend">
        ${slices
          .map(
            (slice) => `
              <div class="pie-legend-row">
                <span class="pie-legend-dot" style="background:${slice.fill}"></span>
                <span class="pie-legend-label" title="${escapeHtml(slice.label)}">${escapeHtml(slice.label)}</span>
                <span class="pie-legend-value">${formatNumber(slice.value)} · ${slice.pct}%</span>
              </div>
            `
          )
          .join("")}
      </div>
    </div>
  `;
}

function mathSin(value) {
  return Math.sin(value);
}

function initHomeSearch() {
  const typeSelect = qs("#home-search-type");
  const input = qs("#home-search-input");
  const submitBtn = qs("#home-search-submit");
  const suggestBox = qs("#home-search-suggest");
  if (!typeSelect || !input || !submitBtn || !suggestBox) return;

  let suggestions = [];
  let activeIndex = -1;
  let fetchId = 0;

  const navigateMap = {
    project: (v) => `/sample.html?q=${encodeURIComponent(v)}`,
    sample_id: (v) => `/sample.html?sample_id=${encodeURIComponent(v)}`,
    bgc_category: (v) => `/bgc.html?bigscape_type=${encodeURIComponent(v)}`,
  };

  const placeholders = {
    project: "Enter BioProject accession (e.g. PRJNA123456)...",
    sample_id: "Enter sample ID (e.g. SAMN12345678)...",
    bgc_category: "Enter BGC category (e.g. PKSI, NRPS, RiPP)...",
  };

  function updatePlaceholder() {
    const type = typeSelect.value;
    input.placeholder = placeholders[type] || "Type to search...";
  }

  function clearSuggestions() {
    suggestions = [];
    activeIndex = -1;
    suggestBox.innerHTML = "";
    suggestBox.hidden = true;
  }

  function renderSuggestions(items) {
    suggestions = items;
    activeIndex = -1;
    if (!items.length) {
      suggestBox.innerHTML = '<div class="search-suggest-empty">No matches found</div>';
      suggestBox.hidden = false;
      return;
    }
    suggestBox.innerHTML = items
      .map(
        (item, idx) =>
          `<button type="button" class="search-suggest-item" data-index="${idx}">${escapeHtml(item.label)}</button>`
      )
      .join("");
    suggestBox.hidden = false;
  }

  function setActive(index) {
    qsa(".search-suggest-item", suggestBox).forEach((el) => el.classList.remove("is-active"));
    activeIndex = index;
    const target = qs(`[data-index="${index}"]`, suggestBox);
    if (target) {
      target.classList.add("is-active");
      target.scrollIntoView({ block: "nearest" });
    }
  }

  function navigate(value) {
    const type = typeSelect.value;
    const urlBuilder = navigateMap[type];
    if (urlBuilder && value) {
      window.location = urlBuilder(value);
    }
  }

  async function fetchSuggestions() {
    const q = input.value.trim();
    if (!q) {
      clearSuggestions();
      return;
    }
    const id = ++fetchId;
    try {
      const resp = await getJSON(
        `/api/search-suggest?type=${encodeURIComponent(typeSelect.value)}&q=${encodeURIComponent(q)}`
      );
      if (id !== fetchId) return;
      renderSuggestions(resp.suggestions || []);
    } catch {
      if (id === fetchId) clearSuggestions();
    }
  }

  let debounceTimer = null;
  input.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(fetchSuggestions, 200);
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (suggestions.length === 0) return;
      setActive((activeIndex + 1) % suggestions.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (suggestions.length === 0) return;
      setActive((activeIndex - 1 + suggestions.length) % suggestions.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (activeIndex >= 0 && activeIndex < suggestions.length) {
        navigate(suggestions[activeIndex].value);
      } else if (input.value.trim()) {
        navigate(input.value.trim());
      }
    } else if (e.key === "Escape") {
      clearSuggestions();
    }
  });

  suggestBox.addEventListener("click", (e) => {
    const btn = e.target.closest(".search-suggest-item");
    if (!btn) return;
    const idx = Number(btn.dataset.index);
    if (idx >= 0 && idx < suggestions.length) {
      navigate(suggestions[idx].value);
    }
  });

  submitBtn.addEventListener("click", () => {
    const value = input.value.trim();
    if (value) navigate(value);
  });

  typeSelect.addEventListener("change", () => {
    updatePlaceholder();
    input.value = "";
    clearSuggestions();
    input.focus();
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".home-search")) clearSuggestions();
  });

  updatePlaceholder();
}

async function loadHome() {
  const payload = await getJSON("/api/home");
  if (qs("#release-label")) qs("#release-label").textContent = payload.release.release_name || payload.release.release_label;
  if (qs("#release-date")) qs("#release-date").textContent = payload.release.released_on || "NA";
  if (qs("#hero-summary")) {
    qs("#hero-summary").textContent =
      "BGCMAP Resource is a hierarchical database for exploring biosynthetic gene clusters together with their genome-resolved, taxonomic, and ecological context. It links each BGC to its source metagenome-assembled genome (MAG), and further connects each MAG to sample provenance, collection habitat, and taxonomic annotation, enabling users to trace biosynthetic potential from globally collected samples to genomes, gene clusters, and clustered gene families (GCFs). Built upon SPIRE-derived MAGs and associated metagenomic datasets, BGCMAP predicts BGCs from MAGs using antiSMASH 8.0 and groups them into GCFs with BiG-SLiCE 2.0.";
  }
  initHomeCarousel();
  initHomeSearch();
}

async function loadStats() {
  const payload = await getJSON("/api/stats");
  const overview = payload.overview;
  const coverage = payload.coverage;
  const magQuality = payload.mag_quality;
  const gcfStats = payload.gcf_stats;
  const bgcTypes = payload.bgc_types;
  const sampleHierarchy = payload.sample_hierarchy;

  qs("#stats-release-label").textContent = payload.release.release_name || payload.release.release_label;
  qs("#stats-release-date").textContent = payload.release.released_on || "NA";

  const kpis = [
    ["Samples", overview.sample_count],
    ["MAGs", overview.mag_count],
    ["BGCs", overview.bgc_count],
    ["GCFs", overview.gcf_count],
  ];
  const maxKpi = Math.max(...kpis.map(([, value]) => Number(value) || 0), 1);
  qs("#stats-kpi-strip").innerHTML = kpis
    .map(
      ([label, value]) => `
        <article class="stat-card">
          <div class="stat-label">${escapeHtml(label)}</div>
          <div class="stat-value">${formatNumber(value)}</div>
          <div class="stat-bar"><span style="width:${Math.max(12, ((Number(value) || 0) / maxKpi) * 100)}%"></span></div>
        </article>
      `
    )
    .join("");

  const renderBarGrid = (node, rows, options = {}) => {
    if (!node) return;
    const max = Math.max(...rows.map((row) => Number(row.value) || 0), 1);
    node.innerHTML = rows
      .map((row, index) => {
        const ratio = (Number(row.value) || 0) / max;
        const height = Math.max(16, ratio * (options.maxHeight || 210));
        const klass = options.colorByGroup
          ? options.colorByGroup(row, index)
          : "";
        return `
          <div class="bar-col">
            <div class="bar-kicker">${escapeHtml(row.group || "")}</div>
            <div class="bar-number">${formatNumber(row.value)}</div>
            <div class="bar-block ${klass}" style="height:${height}px"></div>
            <div class="bar-label">${escapeHtml(row.label)}</div>
          </div>
        `;
      })
      .join("");
  };

  renderBarGrid(qs("#gcf-size-chart"), gcfStats.size_rows, {
    maxHeight: 220,
    colorByGroup: () => "",
  });

  renderTimelineArea(qs("#collection-year-chart"), coverage.collection_year_rows);

  renderListBars(
    qs("#biome-chart"),
    (sampleHierarchy.group1_rows || []).map((row) => ({
      label: displayGroupLabel(row.label),
      value: row.value,
    }))
  );

  renderBarGrid(qs("#mag-quality-chart"), magQuality.rows, {
    maxHeight: 210,
    colorByGroup: (row) => {
      if (row.group === "Contamination") return "warn";
      return "alt";
    },
  });

  renderPieChart(qs("#bgc-type-chart"), bgcTypes);

  qs("#stats-intro-text").textContent =
    "This statistics module summarizes the current BGCMAP release using real database- and source-derived measurements, arranged as paired panels for collection time and biome, MAG quality, BGC type abundance, and GCF size structure.";
}

function buildStandardControls(pageKey, placeholder) {
  if (qs("#page-size")) qs("#page-size").value = params.get("page_size") || "25";
}

const FILTER_FIELD_CONFIG = {
  sample: [
    { key: "sample_id", label: "Sample ID", type: "text" },
    { key: "project", label: "Project", type: "text" },
    { key: "collection_time", label: "Collection time", type: "date" },
    { key: "category", label: "BGC Category", type: "text" },
    { key: "biome1", label: "Biome1", type: "text" },
    { key: "biome2", label: "Biome2", type: "text" },
    { key: "biome3", label: "Biome3", type: "text" },
    { key: "geo_region", label: "Geographic Region", type: "geo" },
    { key: "lat", label: "Lat", type: "number" },
    { key: "lon", label: "Lon", type: "number" },
    { key: "mag_count", label: "MAG count", type: "number" },
    { key: "bgc_count", label: "BGC count", type: "number" },
  ],
  tax: [
    { key: "taxon", label: "Taxon", type: "taxon" },
    { key: "genome_id", label: "Genome ID", type: "text" },
    { key: "sample_id", label: "Sample ID", type: "text" },
    { key: "biome1", label: "Biome1", type: "text" },
    { key: "biome2", label: "Biome2", type: "text" },
    { key: "biome3", label: "Biome3", type: "text" },
    { key: "category", label: "BGC Category", type: "text" },
    { key: "bgc_count", label: "BGC count", type: "number" },
    { key: "completeness", label: "Completeness", type: "number" },
    { key: "contamination", label: "Contamination", type: "number" },
  ],
  bgc: [
    { key: "bgc_id", label: "BGC ID", type: "number" },
    { key: "genome_id", label: "Genome ID", type: "text" },
    { key: "sample_id", label: "Sample ID", type: "text" },
    { key: "gcf_id", label: "GCF ID", type: "number" },
    { key: "product", label: "Product", type: "text" },
    { key: "category", label: "Category", type: "text" },
    { key: "biome1", label: "Biome1", type: "text" },
    { key: "biome2", label: "Biome2", type: "text" },
    { key: "biome3", label: "Biome3", type: "text" },
    { key: "length", label: "Length", type: "number" },
    { key: "membership_value", label: "Membership value", type: "number" },
    { key: "contig_edge", label: "Contig Edge", type: "text" },
  ],
  nps: [
    { key: "bgc_id", label: "BGC ID", type: "number" },
    { key: "np_pathway", label: "NP Pathway", type: "text" },
    { key: "np_superclass", label: "NP Superclass", type: "text" },
    { key: "np_class", label: "NP Class", type: "text" },
    { key: "gcf_id", label: "GCF ID", type: "number" },
    { key: "membership_value", label: "Membership value", type: "number" },
  ],
};

const TEXT_OPERATORS = [
  { key: "equals", label: "= " },
  { key: "not_equals", label: "!=" },
  { key: "is_null", label: "Is null" },
  { key: "is_not_null", label: "Is not null" },
];

const NUMBER_OPERATORS = [
  { key: "equals", label: "= " },
  { key: "not_equals", label: "!=" },
  { key: "gt", label: ">" },
  { key: "gte", label: "≥" },
  { key: "lt", label: "<" },
  { key: "lte", label: "≤" },
  { key: "between", label: "Between" },
  { key: "is_null", label: "Is null" },
  { key: "is_not_null", label: "Is not null" },
];

let filterNodeSeed = 0;
const filterStates = {};

function nextFilterId(prefix) {
  filterNodeSeed += 1;
  return `${prefix}-${filterNodeSeed}`;
}

function defaultField(pageKey) {
  return FILTER_FIELD_CONFIG[pageKey]?.[0]?.key || "sample_id";
}

function getFieldMeta(pageKey, fieldKey) {
  return FILTER_FIELD_CONFIG[pageKey]?.find((field) => field.key === fieldKey) || FILTER_FIELD_CONFIG[pageKey]?.[0];
}

function defaultOperatorForField(pageKey, fieldKey) {
  const meta = getFieldMeta(pageKey, fieldKey);
  if (meta?.type === "number") {
    if (pageKey === "sample" && (fieldKey === "lat" || fieldKey === "lon")) return "between";
    return "equals";
  }
  if (meta?.type === "date") return "between";
  if (meta?.type === "geo") return "equals";
  return "equals";
}

function makeRule(pageKey) {
  const field = defaultField(pageKey);
  return {
    type: "rule",
    id: nextFilterId("rule"),
    field,
    operator: defaultOperatorForField(pageKey, field),
    value: "",
    value_secondary: "",
    taxon: makeTaxonValue(),
  };
}

function makeGroup(pageKey) {
  return {
    type: "group",
    id: nextFilterId("group"),
    combinator: "and",
    negated: false,
    rules: [makeRule(pageKey)],
  };
}

function makeCustomGroup(rules, combinator = "and", negated = false) {
  return {
    type: "group",
    id: nextFilterId("group"),
    combinator,
    negated,
    rules,
  };
}

function makeSingleRuleGroup(field, value = "", operator = "equals", taxon = {}, valueSecondary = "") {
  return makeCustomGroup([
    {
      type: "rule",
      id: nextFilterId("rule"),
      field,
      operator,
      value,
      value_secondary: valueSecondary,
      taxon: makeTaxonValue(taxon),
    },
  ]);
}

function seedFilterStateFromParams(pageKey) {
  if (pageKey === "sample") {
    const rules = [];
    const group1Raw = params.get("group1") || "";
    const mapFilter = params.get("map_filter") || "";
    const latMin = params.get("lat_min") || "";
    const latMax = params.get("lat_max") || "";
    const lonMin = params.get("lon_min") || "";
    const lonMax = params.get("lon_max") || "";
    const q = params.get("q") || "";
    const sampleId = params.get("sample_id") || "";

    if (mapFilter) {
      const mfParts = mapFilter.split("::");
      if (mfParts[0] === "ocean-range" && mfParts.length >= 6) {
        const [, region, olatMin, olatMax, olonMin, olonMax] = mfParts;
        rules.push({ type: "rule", id: nextFilterId("rule"), field: "geo_region", operator: "equals", value: region, taxon: makeTaxonValue() });
        rules.push({ type: "rule", id: nextFilterId("rule"), field: "lat", operator: "between", value: olatMin, value_secondary: olatMax, taxon: makeTaxonValue() });
        rules.push({ type: "rule", id: nextFilterId("rule"), field: "lon", operator: "between", value: olonMin, value_secondary: olonMax, taxon: makeTaxonValue() });
      } else if (mfParts[0] === "country" && mfParts.length >= 2) {
        rules.push({ type: "rule", id: nextFilterId("rule"), field: "geo_region", operator: "equals", value: mfParts[1], taxon: makeTaxonValue() });
      } else if (mfParts[0] === "board" && mfParts.length >= 2) {
        rules.push({ type: "rule", id: nextFilterId("rule"), field: "geo_region", operator: "equals", value: mfParts.slice(1).join("::"), taxon: makeTaxonValue() });
      }
    }
    if (latMin || latMax) {
      rules.push({ type: "rule", id: nextFilterId("rule"), field: "lat", operator: "between", value: latMin, value_secondary: latMax, taxon: makeTaxonValue() });
    }
    if (lonMin || lonMax) {
      rules.push({ type: "rule", id: nextFilterId("rule"), field: "lon", operator: "between", value: lonMin, value_secondary: lonMax, taxon: makeTaxonValue() });
    }
    if (group1Raw) {
      const groupCode = normalizeGroupInput(group1Raw);
      rules.push({ type: "rule", id: nextFilterId("rule"), field: "biome1", operator: "equals", value: displayGroupLabel(groupCode || group1Raw), taxon: makeTaxonValue() });
    }
    if (q) {
      rules.push({ type: "rule", id: nextFilterId("rule"), field: "project", operator: "contains", value: q, taxon: makeTaxonValue() });
    }
    if (sampleId) {
      rules.push({ type: "rule", id: nextFilterId("rule"), field: "sample_id", operator: "equals", value: sampleId, taxon: makeTaxonValue() });
    }
    if (rules.length) return makeCustomGroup(rules);
    return makeGroup(pageKey);
  }
  if (pageKey === "bgc") {
    const rules = [];
    const bigscapeType = params.get("bigscape_type") || "";
    const sampleId = params.get("sample_id") || "";
    const genomeId = params.get("genome_id") || "";
    const bgcName = params.get("bgc_name") || "";
    const bgcId = params.get("bgc_id") || "";
  let gcfId = params.get("gcf_id") || "";

    if (bigscapeType === "PKS") rules.push({ type: "rule", id: nextFilterId("rule"), field: "category", operator: "contains", value: "PKS", taxon: makeTaxonValue() });
    else if (bigscapeType === "Saccharide") rules.push({ type: "rule", id: nextFilterId("rule"), field: "category", operator: "contains", value: "Saccharide", taxon: makeTaxonValue() });
    else if (bigscapeType === "Other") rules.push({ type: "rule", id: nextFilterId("rule"), field: "category", operator: "equals", value: "Others", taxon: makeTaxonValue() });
    else if (bigscapeType) rules.push({ type: "rule", id: nextFilterId("rule"), field: "category", operator: "equals", value: bigscapeType, taxon: makeTaxonValue() });
    if (sampleId) rules.push({ type: "rule", id: nextFilterId("rule"), field: "sample_id", operator: "equals", value: sampleId, taxon: makeTaxonValue() });
    if (genomeId) rules.push({ type: "rule", id: nextFilterId("rule"), field: "genome_id", operator: "equals", value: genomeId, taxon: makeTaxonValue() });
    if (bgcName) rules.push({ type: "rule", id: nextFilterId("rule"), field: "bgc_id", operator: "equals", value: bgcName, taxon: makeTaxonValue() });
    if (bgcId) rules.push({ type: "rule", id: nextFilterId("rule"), field: "bgc_id", operator: "equals", value: bgcId, taxon: makeTaxonValue() });
    if (gcfId) rules.push({ type: "rule", id: nextFilterId("rule"), field: "gcf_id", operator: "equals", value: gcfId, taxon: makeTaxonValue() });
    if (rules.length) return makeCustomGroup(rules);
    return makeGroup(pageKey);
  }
  if (pageKey === "tax") {
    const rules = [];
    const taxon = {
      domain: params.get("domain") || "",
      phylum: params.get("phylum") || "",
      class_name: params.get("class_name") || "",
      order_name: params.get("order_name") || "",
      genus: params.get("genus") || "",
      species: params.get("species") || "",
    };
    const sampleId = params.get("sample_id") || "";
    const genomeId = params.get("genome_id") || "";

    if (taxonValueHasSelection(taxon)) rules.push({ type: "rule", id: nextFilterId("rule"), field: "taxon", operator: "equals", value: "", taxon });
    if (sampleId) rules.push({ type: "rule", id: nextFilterId("rule"), field: "sample_id", operator: "equals", value: sampleId, taxon: makeTaxonValue() });
    if (genomeId) rules.push({ type: "rule", id: nextFilterId("rule"), field: "genome_id", operator: "equals", value: genomeId, taxon: makeTaxonValue() });
    if (rules.length) return makeCustomGroup(rules);
    return makeGroup(pageKey);
  }
  return makeGroup(pageKey);
}

function hydrateFilterNode(pageKey, node) {
  if (!node || typeof node !== "object") return makeGroup(pageKey);
  if (node.type === "rule") {
    let field = node.field || defaultField(pageKey);
    let taxon = makeTaxonValue(node.taxon);
    if (
      pageKey === "tax" &&
      ["domain", "phylum", "class_name", "order_name", "genus", "species"].includes(field)
    ) {
      taxon = makeTaxonValue({ [field]: node.value || "" });
      field = "taxon";
    }
    return {
      type: "rule",
      id: node.id || nextFilterId("rule"),
      field,
      operator: node.operator || "contains",
      value: typeof node.value === "string" || typeof node.value === "number" ? String(node.value) : "",
      value_secondary: typeof node.value_secondary === "string" || typeof node.value_secondary === "number" ? String(node.value_secondary) : "",
      taxon,
    };
  }
  return {
    type: "group",
    id: node.id || nextFilterId("group"),
    combinator: node.combinator || "and",
    negated: !!node.negated,
    rules: Array.isArray(node.rules) && node.rules.length
      ? node.rules.map((child) => hydrateFilterNode(pageKey, child))
      : [makeRule(pageKey)],
  };
}

function getFilterState(pageKey) {
  if (!filterStates[pageKey]) {
    const raw = params.get("filters");
    if (raw) {
      try {
        filterStates[pageKey] = hydrateFilterNode(pageKey, JSON.parse(raw));
      } catch {
        filterStates[pageKey] = seedFilterStateFromParams(pageKey);
      }
    } else {
      filterStates[pageKey] = seedFilterStateFromParams(pageKey);
    }
  }
  return filterStates[pageKey];
}

function findFilterNode(root, id) {
  if (!root) return null;
  if (root.id === id) return root;
  if (root.type === "group") {
    for (const child of root.rules || []) {
      const hit = findFilterNode(child, id);
      if (hit) return hit;
    }
  }
  return null;
}

function removeFilterNode(root, id, pageKey) {
  if (!root || root.type !== "group") return false;
  const nextRules = [];
  let removed = false;
  for (const child of root.rules) {
    if (child.id === id) {
      removed = true;
      continue;
    }
    if (!removed && child.type === "group") {
      removed = removeFilterNode(child, id, pageKey) || removed;
    }
    nextRules.push(child);
  }
  root.rules = nextRules;
  return removed;
}

function serializeFilterState(pageKey) {
  const state = filterStates[pageKey];
  if (!state || !state.rules?.length) return "";
  const rules = state.rules || [];
  for (const rule of rules) {
    if (rule.type !== "rule") continue;
    if (rule.operator === "is_null" || rule.operator === "is_not_null") return JSON.stringify(state);
    if (String(rule.value || "").trim()) return JSON.stringify(state);
    if (rule.taxon && taxonValueHasSelection(rule.taxon)) return JSON.stringify(state);
  }
  return "";
}

function buildFilterSummary(node, pageKey) {
  if (!node) return "";
  if (node.type === "rule") {
    if (node.field === "taxon") {
      if (!taxonValueHasSelection(node.taxon) && !String(node.operator || "").startsWith("is_")) return "";
      const parts = TAXON_LEVELS
        .map((level) => {
          const value = String(node.taxon?.[level.key] || "").trim();
          return value ? `${level.label}=${value}` : "";
        })
        .filter(Boolean);
      const operator =
        [...TEXT_OPERATORS, ...NUMBER_OPERATORS].find((item) => item.key === node.operator)?.label || node.operator;
      return parts.length ? `Taxon ${operator} ${parts.join(" · ")}` : `Taxon ${operator}`;
    }
    if (node.operator === "between") {
      const lower = String(node.value || "").trim();
      const upper = String(node.value_secondary || "").trim();
      if (!lower && !upper) return "";
      const field = getFieldMeta(pageKey, node.field)?.label || node.field;
      if (lower && upper) return `${field} between ${lower} and ${upper}`;
      if (lower) return `${field} ≥ ${lower}`;
      return `${field} ≤ ${upper}`;
    }
    if (!String(node.value || "").trim() && !String(node.operator || "").startsWith("is_")) return "";
    const field = getFieldMeta(pageKey, node.field)?.label || node.field;
    const operator =
      [...TEXT_OPERATORS, ...NUMBER_OPERATORS].find((item) => item.key === node.operator)?.label || node.operator;
    return `${field} ${operator}${node.operator.startsWith("is_") ? "" : ` ${node.value || ""}`}`.trim();
  }
  const pieces = (node.rules || []).map((child) => buildFilterSummary(child, pageKey)).filter(Boolean);
  if (!pieces.length) return "";
  const glue = node.combinator === "or" ? " OR " : " AND ";
  const combined = pieces.join(glue);
  return node.negated ? `NOT (${combined})` : `(${combined})`;
}

function mountAdvancedFilters(pageKey, onApply) {
  const tableCard = qs(".table-card");
  if (!tableCard || qs("#advanced-filter-card")) return;
  const section = document.createElement("section");
  section.className = "card advanced-filter-card";
  section.id = "advanced-filter-card";
  section.innerHTML = `
    <div id="advanced-filter-root"></div>
    <div class="advanced-filter-query"><span>Query logic:</span> <code id="advanced-filter-query-text">None</code></div>
  `;
  tableCard.parentNode.insertBefore(section, tableCard);
  renderFilterBuilder(pageKey, onApply);
}

function renderFilterBuilder(pageKey, onApply) {
  const root = qs("#advanced-filter-root");
  if (!root) return;
  const state = getFilterState(pageKey);
  root.innerHTML = "";
  root.appendChild(renderFilterGroupNode(pageKey, state, 0, onApply));
  qs("#advanced-filter-apply")?.addEventListener("click", () => {
    if (!serializeFilterState(pageKey)) {
      filterStates[pageKey] = makeGroup(pageKey);
      syncParams({ q: null, sample_id: null, sample_accession: null, genome_id: null, gcf_id: null, bgc_name: null, group1: null, map_filter: null, phylum: null, class_name: null, genus: null, species: null, bigscape_type: null, filters: null, page: 1 });
    }
    onApply(1);
  });
  qs("#advanced-filter-reset")?.addEventListener("click", () => {
    filterStates[pageKey] = makeGroup(pageKey);
    syncParams({ q: null, sample_id: null, sample_accession: null, genome_id: null, bgc_name: null, gcf_id: null, bigscape_type: null, group1: null, map_filter: null, filters: null, order_by: null, order_dir: null, page: null, page_size: null });
    renderFilterBuilder(pageKey, onApply);
    onApply(1);
  });
  updateFilterSummary(pageKey);
}

function updateFilterSummary(pageKey) {
  const state = getFilterState(pageKey);
  const queryText = buildFilterSummary(state, pageKey) || "None";
  const queryNode = qs("#advanced-filter-query-text");
  if (queryNode) queryNode.textContent = queryText;
}

function describeMapFilter(rawValue) {
  const raw = String(rawValue || "").trim();
  if (!raw) return null;
  const parts = raw.split("::");
  if (parts[0] === "board" && parts[1]) {
    return { label: "Map region", value: parts.slice(1).join(" · ") };
  }
  if (parts[0] === "country" && parts[1]) {
    return { label: "Country", value: parts[1] };
  }
  if (parts[0] === "ocean-range" && parts.length >= 6) {
    const [, region, latMin, latMax, lonMin, lonMax] = parts;
    return {
      label: "Ocean window",
      value: `${region} · lat ${latMin} to ${latMax} · lon ${lonMin} to ${lonMax}`,
    };
  }
  return { label: "Map filter", value: raw };
}

function collectContextFilters(pageKey) {
  const entries = [];
  if (pageKey === "sample") {
    const group1 = params.get("group1") || "";
    const mapFilter = params.get("map_filter") || "";
    const latMin = params.get("lat_min") || "";
    const latMax = params.get("lat_max") || "";
    const lonMin = params.get("lon_min") || "";
    const lonMax = params.get("lon_max") || "";
    if (group1) entries.push({ label: "Biome1", value: displayGroupLabel(group1) });
    if (latMin || latMax) {
      entries.push({ label: "Lat", value: latMin && latMax ? `${latMin} to ${latMax}` : latMin ? `>= ${latMin}` : `<= ${latMax}` });
    }
    if (lonMin || lonMax) {
      entries.push({ label: "Lon", value: lonMin && lonMax ? `${lonMin} to ${lonMax}` : lonMin ? `>= ${lonMin}` : `<= ${lonMax}` });
    }
    const mapEntry = describeMapFilter(mapFilter);
    if (mapEntry) entries.push(mapEntry);
    return entries;
  }
  if (pageKey === "bgc") {
    const bigscapeType = params.get("bigscape_type") || "";
    if (bigscapeType) entries.push({ label: "Category", value: bigscapeType });
    return entries;
  }
  if (pageKey === "tax") {
    const summary = buildFilterSummary(getFilterState(pageKey), pageKey);
    if (summary && summary !== "None") {
      entries.push({ label: "Taxon selection", value: summary.replace(/^\((.*)\)$/, "$1") });
    }
    return entries;
  }
  return entries;
}

function mountContextFilterCard(pageKey) {
  const tableCard = qs(".table-card");
  if (!tableCard) return;
  const entries = collectContextFilters(pageKey);
  const existing = qs("#context-filter-card");
  if (!entries.length) {
    if (existing) existing.remove();
    return;
  }
  const section = existing || document.createElement("section");
  section.className = "card context-filter-card";
  section.id = "context-filter-card";
  section.innerHTML = `
    <div class="context-filter-head">
      <div>
        <h2>Active board filter</h2>
        <p>This page was opened from the home overview with the following preset scope.</p>
      </div>
    </div>
    <div class="context-filter-list">
      ${entries
        .map(
          (entry) => `
            <div class="context-chip">
              <span class="context-chip-label">${escapeHtml(entry.label)}</span>
              <span class="context-chip-value">${escapeHtml(entry.value)}</span>
            </div>
          `
        )
        .join("")}
    </div>
  `;
  if (!existing) tableCard.parentNode.insertBefore(section, tableCard);
}

function renderFilterGroupNode(pageKey, group, depth, onApply) {
  const wrapper = document.createElement("div");
  wrapper.className = `filter-group depth-${depth}`;
  const isRoot = depth === 0;
  wrapper.innerHTML = `
      <div class="filter-group-toolbar">
      <div class="filter-combinator" data-group-id="${group.id}">
        <button type="button" data-combinator="and" class="${group.combinator === "and" ? "is-active" : ""}">AND</button>
        <button type="button" data-combinator="or" class="${group.combinator === "or" ? "is-active" : ""}">OR</button>
        <button type="button" data-combinator="not" class="filter-not-toggle ${group.negated ? "is-active" : ""}">NOT</button>
      </div>
      <div class="filter-group-actions">
        <button type="button" class="secondary" data-action="add-rule" data-group-id="${group.id}">+ Rule</button>
        <button type="button" class="secondary" data-action="add-group" data-group-id="${group.id}">+ Group</button>
        ${isRoot ? "" : `<button type="button" class="ghost-danger" data-action="remove-group" data-group-id="${group.id}"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="trash-icon"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg></button>`}
      </div>
      ${isRoot ? `
      <div class="advanced-filter-actions">
        <button type="button" class="secondary" id="advanced-filter-reset">Reset</button>
        <button type="button" id="advanced-filter-apply">Apply filters</button>
      </div>` : ""}
    </div>
    <div class="filter-group-body"></div>
  `;
  const body = qs(".filter-group-body", wrapper);
  for (const child of group.rules) {
    body.appendChild(child.type === "group" ? renderFilterGroupNode(pageKey, child, depth + 1, onApply) : renderFilterRuleNode(pageKey, child, onApply));
  }
  qsa(".filter-combinator button", wrapper).forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.combinator === "not") {
        group.negated = !group.negated;
      } else {
        group.combinator = button.dataset.combinator || "and";
      }
      renderFilterBuilder(pageKey, onApply);
    });
  });
  qsa(".filter-group-actions button", wrapper).forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.dataset.action;
      if (action === "add-rule") group.rules.push(makeRule(pageKey));
      if (action === "add-group") group.rules.push(makeGroup(pageKey));
      if (action === "remove-group") {
        removeFilterNode(getFilterState(pageKey), group.id, pageKey);
      }
      renderFilterBuilder(pageKey, onApply);
    });
  });
  return wrapper;
}

function renderFilterRuleNode(pageKey, rule, onApply) {
  const wrapper = document.createElement("div");
  wrapper.className = "filter-rule";
  const fieldMeta = getFieldMeta(pageKey, rule.field);
  const isRangeType = fieldMeta?.type === "number" || fieldMeta?.type === "date";
  const equalsOnly = rule.field === "gcf_id" || rule.field === "bgc_id";
  const noNullNumber = isRangeType && fieldMeta?.type === "number" && !(pageKey === "sample" && (rule.field === "lat" || rule.field === "lon"));
  const noNullText = !isRangeType && !isGeoField(rule.field) && (rule.field === "sample_id" || rule.field === "genome_id");
  const operators = equalsOnly ? [TEXT_OPERATORS.find((o) => o.key === "equals") || NUMBER_OPERATORS.find((o) => o.key === "equals")] : (noNullNumber ? NUMBER_OPERATORS.filter((o) => o.key !== "is_null" && o.key !== "is_not_null") : (noNullText ? TEXT_OPERATORS.filter((o) => o.key !== "is_null" && o.key !== "is_not_null") : (isRangeType ? NUMBER_OPERATORS : (isGeoField(rule.field) ? TEXT_OPERATORS.filter((o) => GEO_ALL_OPERATORS.has(o.key)) : TEXT_OPERATORS))));
  const showRangeInputs = isRangeType && rule.operator === "between";
  const showBiomeDropdown = isBiomeField(rule.field) && BIOME_DROPDOWN_OPERATORS.has(rule.operator);
  const showCategoryDropdown = isCategoryField(rule.field) && BIOME_DROPDOWN_OPERATORS.has(rule.operator) && pageKey === "bgc";
  const showGeoDropdown = isGeoField(rule.field) && GEO_DROPDOWN_OPERATORS.has(rule.operator);
  const showTaxonGrid = isTaxonField(rule.field) && TAXON_DROPDOWN_OPERATORS.has(rule.operator);
  const biomeOptions = showBiomeDropdown ? getBiomeDropdownOptions(pageKey, rule) : [];
  const boards = geoOptionsCache.boards || [];
  const countriesByBoard = geoOptionsCache.countries_by_board || {};
  let geoSelectedBoard = "";
  let geoSelectedCountry = "";
  let geoCountryOptions = [];
  if (showGeoDropdown) {
    const cv = String(rule.value || "").trim().toLowerCase();
    const boardMatch = boards.find((b) => b.toLowerCase() === cv);
    if (boardMatch) {
      geoSelectedBoard = boardMatch;
      geoCountryOptions = countriesByBoard[boardMatch] || [];
    } else {
      for (const [board, countries] of Object.entries(countriesByBoard)) {
        const match = countries.find((c) => c.toLowerCase() === cv);
        if (match) {
          geoSelectedBoard = board;
          geoSelectedCountry = match;
          geoCountryOptions = countries;
          break;
        }
      }
      if (!geoSelectedBoard) {
        geoCountryOptions = Object.values(countriesByBoard).flat().filter((v, i, a) => a.indexOf(v) === i).sort();
      }
    }
  }
  const taxonValue = makeTaxonValue(rule.taxon);
  if (showTaxonGrid) wrapper.classList.add("is-taxon-rule");
  wrapper.innerHTML = `
    <div class="filter-rule-grid">
      <label>
        <span>Field</span>
        <select class="filter-field">
          ${FILTER_FIELD_CONFIG[pageKey].map((field) => `<option value="${field.key}" ${field.key === rule.field ? "selected" : ""}>${escapeHtml(field.label)}</option>`).join("")}
        </select>
      </label>
      <label>
        <span>Operator</span>
        <select class="filter-operator">
          ${operators.map((operator) => `<option value="${operator.key}" ${operator.key === rule.operator ? "selected" : ""}>${escapeHtml(operator.label)}</option>`).join("")}
        </select>
      </label>
      <label class="filter-value-wrap ${rule.operator.startsWith("is_") ? "is-hidden" : ""}">
        <span class="${showTaxonGrid ? "is-hidden" : ""}">Value</span>
        ${showTaxonGrid ? `
          <div class="filter-taxon-grid">
            ${TAXON_LEVELS.map((level) => {
              const options = getTaxonDropdownOptions(taxonValue, level.key);
              const currentValue = taxonValue[level.key] || "";
              return `
                <div class="filter-taxon-cell">
                  <span>${escapeHtml(level.label)}</span>
                  <div class="filter-value-input-group filter-value-input-group--taxon has-inline-select">
                    <input
                      class="filter-taxon-input"
                      data-taxon-key="${level.key}"
                      type="text"
                      value="${escapeHtml(currentValue)}"
                      placeholder="Type ${escapeHtml(level.label.toLowerCase())}"
                    >
                    <span class="filter-select-shell">
                      <select class="filter-taxon-select" data-taxon-key="${level.key}" aria-label="${escapeHtml(level.label)} dropdown">
                        <option value="">${taxonOptionsLoaded ? `All ${escapeHtml(level.label)}` : "Loading..."}</option>
                        ${options.map((option) => `
                          <option value="${escapeHtml(option)}" ${taxonOptionIsSelected(option, currentValue) ? "selected" : ""}>${escapeHtml(option)}</option>
                        `).join("")}
                      </select>
                    </span>
                  </div>
                </div>
              `;
            }).join("")}
          </div>
        ` : `
          <div class="filter-value-input-group ${showGeoDropdown ? "is-geo-cascade" : showRangeInputs ? "is-range-control" : (showBiomeDropdown || showCategoryDropdown) ? "has-inline-select" : "is-single-control"}">
            ${showGeoDropdown ? `
              <div class="filter-geo-cascade">
                <div class="filter-geo-combo">
                  <input class="filter-geo-board-input" type="text" value="${escapeHtml(geoSelectedBoard || rule.value || "")}" placeholder="Continent / Ocean">
                  <span class="filter-select-shell">
                    <select class="filter-geo-board-select" aria-label="Continent / Ocean dropdown">
                      <option value="">All regions</option>
                      ${boards.map((board) => `
                        <option value="${escapeHtml(board)}" ${board === geoSelectedBoard ? "selected" : ""}>${escapeHtml(board)}</option>
                      `).join("")}
                    </select>
                  </span>
                </div>
                <span class="filter-geo-divider">→</span>
                <div class="filter-geo-combo">
                  <input class="filter-geo-country-input" type="text" value="${escapeHtml(geoSelectedCountry || "")}" placeholder="Country">
                  <span class="filter-select-shell">
                    <select class="filter-geo-country-select" aria-label="Country dropdown">
                      <option value="">All countries</option>
                      ${geoCountryOptions.map((country) => `
                        <option value="${escapeHtml(country)}" ${country === geoSelectedCountry ? "selected" : ""}>${escapeHtml(country)}</option>
                      `).join("")}
                    </select>
                  </span>
                </div>
              </div>
            ` : showRangeInputs ? `
              <input class="filter-value-min" type="${fieldMeta?.type === "date" ? "text" : "number"}" value="${escapeHtml(rule.value || "")}" placeholder="Min">
              <span class="filter-range-divider">to</span>
              <input class="filter-value-max" type="${fieldMeta?.type === "date" ? "text" : "number"}" value="${escapeHtml(rule.value_secondary || "")}" placeholder="Max">
            ` : (rule.operator === "is_null" || rule.operator === "is_not_null") ? `
              <span class="filter-value-placeholder">No value needed</span>
            ` : `
              <input class="filter-value" type="text" value="${escapeHtml(rule.value || "")}" placeholder="Enter value">
              ${showBiomeDropdown ? `
                <span class="filter-select-shell">
                  <select class="filter-value-select" aria-label="${escapeHtml(fieldMeta?.label || "biome")} dropdown">
                    <option value="">Choose ${escapeHtml(fieldMeta?.label || "biome")}</option>
                    ${biomeOptionsWithCounts(rule.field, biomeOptions).map((opt) => `
                <option value="${escapeHtml(opt.label)}" ${rule.value === opt.label ? "selected" : ""}>${escapeHtml(opt.label)}</option>`).join("")}
                  </select>
                </span>
              ` : showCategoryDropdown ? `
                <span class="filter-select-shell">
                  <select class="filter-value-select" aria-label="Category dropdown">
                    <option value="">Choose Category</option>
                    ${(categoryOptionsCache || []).map((c) => `
                <option value="${escapeHtml(c.label)}" ${rule.value === c.label ? "selected" : ""}>${escapeHtml(c.label)}</option>`).join("")}
                  </select>
                </span>
              ` : ""}
            `}
          </div>
        `}
      </label>
      <button type="button" class="ghost-danger filter-remove"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="trash-icon"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg></button>
    </div>
  `;
  qs(".filter-field", wrapper).addEventListener("change", (event) => {
    rule.field = event.target.value;
    rule.operator = defaultOperatorForField(pageKey, rule.field);
    rule.value = "";
    rule.value_secondary = "";
    rule.taxon = makeTaxonValue();
    renderFilterBuilder(pageKey, onApply);
  });
  qs(".filter-operator", wrapper).addEventListener("change", (event) => {
    rule.operator = event.target.value;
    if (rule.operator !== "between") rule.value_secondary = "";
    renderFilterBuilder(pageKey, onApply);
  });
  if (showTaxonGrid) {
    qsa(".filter-taxon-input", wrapper).forEach((input) => {
      input.addEventListener("input", (event) => {
        const key = event.target.dataset.taxonKey;
        if (!key) return;
        rule.taxon = { ...makeTaxonValue(rule.taxon), [key]: event.target.value };
        updateFilterSummary(pageKey);
      });
      input.addEventListener("change", (event) => {
        const key = event.target.dataset.taxonKey;
        if (!key) return;
        rule.taxon = { ...makeTaxonValue(rule.taxon), [key]: event.target.value };
        clearTaxonDescendants(rule, key);
        renderFilterBuilder(pageKey, onApply);
      });
    });
    qsa(".filter-taxon-select", wrapper).forEach((select) => {
      select.addEventListener("change", (event) => {
        const key = event.target.dataset.taxonKey;
        if (!key) return;
        rule.taxon = { ...makeTaxonValue(rule.taxon), [key]: event.target.value };
        clearTaxonDescendants(rule, key);
        renderFilterBuilder(pageKey, onApply);
      });
    });
  } else if (showRangeInputs) {
    qs(".filter-value-min", wrapper)?.addEventListener("input", (event) => {
      rule.value = event.target.value;
      updateFilterSummary(pageKey);
    });
    qs(".filter-value-min", wrapper)?.addEventListener("change", (event) => {
      rule.value = event.target.value;
      renderFilterBuilder(pageKey, onApply);
    });
    qs(".filter-value-max", wrapper)?.addEventListener("input", (event) => {
      rule.value_secondary = event.target.value;
      updateFilterSummary(pageKey);
    });
    qs(".filter-value-max", wrapper)?.addEventListener("change", (event) => {
      rule.value_secondary = event.target.value;
      renderFilterBuilder(pageKey, onApply);
    });
  } else {
    qs(".filter-value", wrapper)?.addEventListener("input", (event) => {
      rule.value = event.target.value;
      updateFilterSummary(pageKey);
    });
    qs(".filter-value", wrapper)?.addEventListener("change", (event) => {
      rule.value = event.target.value;
      if (showBiomeDropdown) renderFilterBuilder(pageKey, onApply);
    });
    qs(".filter-value-select", wrapper)?.addEventListener("change", (event) => {
      rule.value = event.target.value;
      renderFilterBuilder(pageKey, onApply);
    });
    qs(".filter-geo-board-input", wrapper)?.addEventListener("input", (event) => {
      rule.value = event.target.value;
      updateFilterSummary(pageKey);
    });
    qs(".filter-geo-board-input", wrapper)?.addEventListener("change", (event) => {
      rule.value = event.target.value;
      renderFilterBuilder(pageKey, onApply);
    });
    qs(".filter-geo-board-select", wrapper)?.addEventListener("change", (event) => {
      rule.value = event.target.value;
      renderFilterBuilder(pageKey, onApply);
    });
    qs(".filter-geo-country-input", wrapper)?.addEventListener("input", (event) => {
      rule.value = event.target.value;
      updateFilterSummary(pageKey);
    });
    qs(".filter-geo-country-input", wrapper)?.addEventListener("change", (event) => {
      rule.value = event.target.value;
      renderFilterBuilder(pageKey, onApply);
    });
    qs(".filter-geo-country-select", wrapper)?.addEventListener("change", (event) => {
      rule.value = event.target.value;
      renderFilterBuilder(pageKey, onApply);
    });
  }
  qs(".filter-remove", wrapper).addEventListener("click", () => {
    removeFilterNode(getFilterState(pageKey), rule.id, pageKey);
    renderFilterBuilder(pageKey, onApply);
  });
  return wrapper;
}

function syncParams(newParams) {
  const next = new URLSearchParams(window.location.search);
  Object.entries(newParams).forEach(([key, value]) => {
    if (value === "" || value === null || value === undefined) next.delete(key);
    else next.set(key, String(value));
  });
  // Keep URL clean: only module name, no query params
  history.replaceState({}, "", window.location.pathname);
  params = next;
  return next;
}

async function loadSamples(page = Number(params.get("page") || 1)) {
  const q = params.get("q") || "";
  const pageSize = qs("#page-size")?.value || "25";
  let sampleId = params.get("sample_id") || "";
  let sampleAccession = params.get("sample_accession") || "";
  let group1 = params.get("group1") || "";
  let mapFilter = params.get("map_filter") || "";
  const orderBy = params.get("order_by") || "";
  const orderDir = params.get("order_dir") || "asc";
  const filters = serializeFilterState("sample");
  showLoading(qs("#entries-label"));
  syncParams({ q, page, page_size: pageSize, sample_id: sampleId || null, sample_accession: sampleAccession || null, group1: group1 || null, map_filter: mapFilter || null, order_by: orderBy || null, order_dir: orderBy ? orderDir : null });
  const meta = await getJSON(`/api/samples?q=${encodeURIComponent(q)}&sample_id=${encodeURIComponent(sampleId)}&sample_accession=${encodeURIComponent(sampleAccession)}&group1=${encodeURIComponent(group1)}&map_filter=${encodeURIComponent(mapFilter)}&order_by=${encodeURIComponent(orderBy)}&order_dir=${encodeURIComponent(orderDir)}&filters=${encodeURIComponent(filters)}&page=${page}&page_size=${pageSize}`);
  updateEntriesLabel(meta, qs("#entries-label"));
  renderTable(
    qs("#table-root"),
    [
      "Project",
      "Sample ID",
      "Collection time",
      "Biome1",
      "Biome2",
      "Biome3",
      { label: "Lat", sortKey: "lat" },
      { label: "Lon", sortKey: "lon" },
      { label: "MAG", sortKey: "mag_count" },
      { label: "BGC", sortKey: "bgc_count" },
      "BGC Category",
    ],
    meta.rows,
    (row) => `
      <td>${row.project ? `<a class="cell-ellipsis cell-ellipsis-link" href="https://www.ncbi.nlm.nih.gov/bioproject/${row.project}" target="_blank" rel="noreferrer" title="${escapeHtml(row.project)}">${escapeHtml(row.project)}</a>` : '<span class="subtle">NA</span>'}</td>
      <td>${ellipsisLink(row.ncbi_url, row.sample_id)}</td>
      <td>${(() => { const t = row.collection_time || 'NA'; const y = parseInt(t); return (!isNaN(y) && y > 2024) ? `<span style=\"color:#aaa;font-style:italic\" title=\"Possibly incorrect future date\">${escapeHtml(t)}</span>` : escapeHtml(t); })()}</td>
      <td>${ellipsisText(displayGroupLabel(row.group1 || row.biome1) || "NA")}</td>
      <td>${ellipsisText(displayGroupLabel(row.group2 || row.biome2) || "NA")}</td>
      <td>${ellipsisText(displayGroupLabel(row.group3 || row.biome3) || "NA")}</td>
      <td>${row.lat != null ? Number(row.lat).toFixed(4) : "NA"}</td>
      <td>${row.lon != null ? Number(row.lon).toFixed(4) : "NA"}</td>
      <td>${makeLocalLink(row.mag_url, formatNumber(row.mag_count))}</td>
      <td>${Number(row.bgc_count) > 0 ? makeLocalLink(row.bgc_url, formatNumber(row.bgc_count)) : '<span class="subtle">0</span>'}</td>
      <td>${ellipsisText(row.category || "NA")}</td>
    `,
    {
      tableClass: "sample-table-fixed",
      columnWidths: [120, 120, 120, 160, 160, 160, 80, 80, 80, 80, 180],
      sortState: orderBy ? { field: orderBy, dir: orderDir } : null,
      onSort: (field, dir) => {
        syncParams({ order_by: field, order_dir: dir, page: 1 });
        loadSamples(1);
      },
    }
  );
  const pager = buildPager(meta, loadSamples);
  const slot = qs("#pager-root");
  slot.innerHTML = "";
  slot.appendChild(pager);
}

async function loadMags(page = Number(params.get("page") || 1)) {
  const q = params.get("q") || "";
  const pageSize = qs("#page-size")?.value || "25";
  const orderBy = params.get("order_by") || "";
  const orderDir = params.get("order_dir") || "asc";
  const filters = serializeFilterState("tax");
  showLoading(qs("#entries-label"));
  const taxMode = params.get("tax_mode") || "phylum";
  syncParams({
    page,
    page_size: pageSize,
    tax_mode: taxMode,
    order_by: orderBy || null,
    order_dir: orderBy ? orderDir : null,
  });

  qsa("#tax-rank-switcher button").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.taxMode === taxMode);
    if (!button.dataset.bound) {
      button.dataset.bound = "1";
      button.addEventListener("click", () => {
        const next = button.dataset.taxMode || "phylum";
        syncParams({ tax_mode: next, page: 1, phylum: null, class_name: null, genus: null, species: null, phylum_group: null });
        loadMags(1);
      });
    }
  });

  const meta = await getJSON(
    `/api/mags?q=${encodeURIComponent(q)}&order_by=${encodeURIComponent(orderBy)}&order_dir=${encodeURIComponent(orderDir)}&filters=${encodeURIComponent(filters)}&page=${page}&page_size=${pageSize}`
  );
  updateEntriesLabel(meta, qs("#entries-label"));
   const firstHeader = taxMode === "phylum" ? "Phylum" : taxMode === "class" ? "Class" : taxMode === "genus" ? "Genus" : "Species";
   renderTable(
     qs("#table-root"),
     [
       firstHeader,
       "Genome ID",
       { label: "BGC", sortKey: "bgc_count" },
        "BGC Category",
        { label: "Completeness", sortKey: "completeness" },
        { label: "Contamination", sortKey: "contamination" },
        { label: "Genome size", sortKey: "genome_size" },
        { label: "Gene count", sortKey: "gene_count" },
        "Sample ID",
        "Biome1",
       "Biome2",
       "Biome3",
     ],
     meta.rows,
     (row) => {
       const label =
        taxMode === "phylum"
          ? row.phylum || "Unclassified"
          : taxMode === "class"
            ? row.class_name || "NA"
            : taxMode === "genus"
              ? row.genus || "NA"
              : (row.species_lineage || row.species || "NA");
      let target = null;
      if (taxMode === "phylum" && row.phylum) target = `/tax.html?tax_mode=phylum&phylum=${encodeURIComponent(row.phylum)}`;
      else if (taxMode === "class" && row.class_name) target = `/tax.html?tax_mode=class&class_name=${encodeURIComponent(row.class_name)}`;
      else if (taxMode === "genus" && row.genus) target = `/tax.html?tax_mode=genus&genus=${encodeURIComponent(row.genus)}`;
      else if (taxMode === "species" && (row.species_lineage || row.species)) target = `/tax.html?tax_mode=species&species=${encodeURIComponent(row.species_lineage || row.species)}`;
      return {
        cells: `
          <td>${renderTaxonomyDisclosure(row, label, target)}</td>
          <td>${row.antismash_url || row.portal_url ? `<a class="cell-ellipsis cell-ellipsis-link" href="${row.antismash_url || row.portal_url}" target="_blank" rel="noreferrer" title="${escapeHtml(row.genome_id)}">${escapeHtml(row.genome_id_display || row.genome_id)}</a>` : `<span class="cell-ellipsis subtle">${escapeHtml(row.genome_id_display || row.genome_id)}</span>`}</td>
          <td>${Number(row.bgc_count) > 0 ? makeLocalLink(row.bgc_url, formatNumber(row.bgc_count)) : '<span class="subtle">0</span>'}</td>
          <td>${ellipsisText(row.category_preview || "NA")}</td>
          <td>${escapeHtml(row.completeness ?? "NA")}</td>
          <td>${escapeHtml(row.contamination ?? "NA")}</td>
          <td>${formatNumber(row.genome_size)}</td>
          <td>${formatNumber(row.gene_count)}</td>
          <td>${ellipsisLink(row.sample_url, row.sample_id)}</td>
          <td>${ellipsisText(displayGroupLabel(row.biome1) || "NA")}</td>
          <td>${ellipsisText(displayGroupLabel(row.biome2) || "NA")}</td>
          <td>${ellipsisText(displayGroupLabel(row.biome3) || "NA")}</td>
        `,
        detail: renderTaxonomyDetailRow(row, label, 12),
      };
    },
    {
      tableClass: "tax-table-fixed",
      sortState: orderBy ? { field: orderBy, dir: orderDir } : null,
      onSort: (field, dir) => {
        syncParams({ order_by: field, order_dir: dir, page: 1 });
        loadMags(1);
      },
    }
  );
  bindTaxonomyDisclosureControls();
  const pager = buildPager(meta, loadMags);
  const slot = qs("#pager-root");
  slot.innerHTML = "";
  slot.appendChild(pager);
}

async function loadBgcs(page = Number(params.get("page") || 1)) {
  const q = params.get("q") || "";
  const pageSize = qs("#page-size")?.value || "25";
  let gcfIdBgc = "";
  const defaultOrderBy = gcfIdBgc ? "membership_value" : "bgc_id";
  const orderBy = qs("#bgc-sort-field")?.value || params.get("order_by") || defaultOrderBy;
  const orderDir = qs("#bgc-sort-direction")?.value || params.get("order_dir") || "asc";
  const filters = serializeFilterState("bgc");
  showLoading(qs("#entries-label"));
  syncParams({ q, page, page_size: pageSize, order_by: orderBy || null, order_dir: orderDir || null });
  const meta = await getJSON(
    `/api/bgcs?q=${encodeURIComponent(q)}&order_by=${encodeURIComponent(orderBy)}&order_dir=${encodeURIComponent(orderDir)}&filters=${encodeURIComponent(filters)}&page=${page}&page_size=${pageSize}`
  );
  updateEntriesLabel(meta, qs("#entries-label"));
  renderTable(
    qs("#table-root"),
    [
      "BGC ID",
      "Product",
      "Category",
      { label: "GCF ID", sortKey: "gcf_id" },
      { label: "Membership value", sortKey: "membership_value" },
      { label: "Length", sortKey: "length" },
      "Contig edge",
      "Genome ID",
      "Sample ID",
      "Species",
      "Biome1",
      "Biome2",
      "Biome3",
    ],
    meta.rows,
    (row) => {
      const label = bestTaxonLabel(row);
      const bgcLabel = row.bgc_source_id || row.bgc_name;
      const bgcTarget = row.antismash_url || `/bgc.html?bgc_id=${encodeURIComponent(row.bgc_source_id)}`;
      return {
        cells: `
          <td>${renderTaxonomyDisclosure(row, bgcLabel, bgcTarget)}</td>
          <td>${ellipsisText(row.product || "NA")}</td>
          <td>${ellipsisText(row.category || "NA")}</td>
          <td>${row.gcf_url ? ellipsisLink(row.gcf_url, normalizeNumericIdLabel(row.gcf_id)) : '<span class="subtle">NA</span>'}</td>
          <td>${makeMembershipBadge(row.membership_value, row.contig_edge, row.membership_status)}</td>

          <td>${formatNumber(row.length)}</td>
          <td>${row.contig_edge === true ? 'TRUE' : row.contig_edge === false ? 'FALSE' : 'NA'}</td>
          <td>${row.genome_url ? `<a class="cell-ellipsis cell-ellipsis-link" href="${row.genome_url}" title="${escapeHtml(row.genome_id)}">${escapeHtml(row.genome_id_display || row.genome_id.replace(/^spire_/, ''))}</a>` : `<span class="cell-ellipsis subtle">${escapeHtml(row.genome_id_display || row.genome_id.replace(/^spire_/, ''))}</span>`}</td>
          <td>${ellipsisLink(row.sample_url, row.sample_id)}</td>
          <td>${ellipsisText(row.species || "NA")}</td>
          <td>${ellipsisText(displayGroupLabel(row.biome1) || "NA")}</td>
          <td>${ellipsisText(displayGroupLabel(row.biome2) || "NA")}</td>
          <td>${ellipsisText(displayGroupLabel(row.biome3) || "NA")}</td>
        `,
        detail: renderTaxonomyDetailRow(row, label, 13),
      };
    },
    {
      tableClass: "bgc-table-fixed",
      sortState: { field: orderBy, dir: orderDir },
      onSort: (field, dir) => {
        syncParams({ order_by: field, order_dir: dir, page: 1 });
        loadBgcs(1);
      },
    }
  );
  bindTaxonomyDisclosureControls();
  const pager = buildPager(meta, loadBgcs);
  const slot = qs("#pager-root");
  loadGcfDetail();
  slot.innerHTML = "";
  slot.appendChild(pager);
}

async function loadGcfTable(page = Number(params.get("page") || 1)) {
  const q = params.get("q") || "";
  const pageSize = qs("#page-size")?.value || "25";
  syncParams({ q, page, page_size: pageSize });
  const meta = await getJSON(`/api/gcfs?q=${encodeURIComponent(q)}&page=${page}&page_size=${pageSize}`);
  updateEntriesLabel(meta, qs("#entries-label"));
  renderTable(
    qs("#table-root"),
    ["GCF ID", "BGC count", "Complete BGC", "Incomplete BGC", "Median length", "Mean membership", "Genome count", "Open"],
    meta.rows,
    (row) => `
      <td>${makeLocalLink(row.detail_url, row.gcf_id)}</td>
      <td>${formatNumber(row.bgc_count)}</td>
      <td>${formatNumber(row.complete_bgc_count)}</td>
      <td>${formatNumber(row.incomplete_bgc_count)}</td>
      <td>${formatNumber(row.median_length)}</td>
          <td>${makeMembershipBadge(row.mean_membership_value, null, row.representative_type || "family")}</td>
      <td>${formatNumber(row.genome_count)}</td>
      <td>${makeLocalLink(row.detail_url, "View")}</td>
    `,
    {
      tableClass: "generic-table-fixed",

    }
  );
  const pager = buildPager(meta, loadGcfTable);
  const slot = qs("#pager-root");
  slot.innerHTML = "";
  slot.appendChild(pager);
}

function renderListBars(target, rows) {
  if (!rows.length) {
    target.innerHTML = '<div class="subtle">No local records available yet.</div>';
    return;
  }
  const max = Math.max(...rows.map((row) => Number(row.value) || 0), 1);
  target.innerHTML = rows
    .map(
      (row) => `
        <div class="list-bar">
          <div class="list-bar-head"><span>${escapeHtml(row.label)}</span><strong>${formatNumber(row.value)}</strong></div>
          <div class="list-bar-track"><span style="width:${((Number(row.value) || 0) / max) * 100}%"></span></div>
        </div>
      `
    )
    .join("");
}

function biomeOptionsWithCounts(fieldKey, options) {
  return options.map((label) => ({ label }));
}

function findFilterRule(node, fieldKey) {
  if (!node) return null;
  if (node.type === "rule" && node.field === fieldKey) return node;
  if (node.type === "group" && node.rules) {
    for (const child of node.rules) {
      const found = findFilterRule(child, fieldKey);
      if (found) return found;
    }
  }
  return null;
}

async function loadGcfDetail() {
  let gcfId = params.get("gcf_id");
  if (!gcfId) {
    const state = getFilterState("bgc");
    const gcfRule = findFilterRule(state, "gcf_id");
    if (gcfRule && gcfRule.value) gcfId = gcfRule.value;
  }
  if (!gcfId) {
    qs("#detail-panel").innerHTML = "";
    return;
  }

  const detail = await getJSON(`/api/gcf-detail?gcf_id=${encodeURIComponent(gcfId)}`);
  if (detail.error) {
    qs("#detail-panel").innerHTML = `<div class="detail-card"><div class="note-box">${escapeHtml(detail.error)}</div></div>`;
    return;
  }

  const summary = detail.summary;
  qs("#detail-panel").innerHTML = `
    <section class="detail-card">
      <h2>GCF ${escapeHtml(summary.gcf_id)}</h2>
      <div class="detail-grid">
        <div class="mini-stat"><div class="subtle">Representative type</div><strong>${escapeHtml(summary.representative_type || "NA")}</strong></div>
        <div class="mini-stat"><div class="subtle">BGC count</div><strong>${formatNumber(summary.bgc_count)}</strong></div>
        <div class="mini-stat"><div class="subtle">Core BGC</div><strong>${formatNumber(summary.core_bgc_count)}</strong></div>
        <div class="mini-stat"><div class="subtle">Peripheral BGC</div><strong>${formatNumber(summary.peripheral_bgc_count)}</strong></div>
        <div class="mini-stat"><div class="subtle">Genome count</div><strong>${formatNumber(summary.genome_count)}</strong></div>
        <div class="mini-stat"><div class="subtle">Sample count</div><strong>${formatNumber(summary.sample_count)}</strong></div>
        <div class="mini-stat"><div class="subtle">Species count</div><strong>${formatNumber(summary.species_count)}</strong></div>
        <div class="mini-stat"><div class="subtle">Mean membership</div><strong>${escapeHtml(summary.mean_membership_value)}</strong></div>
      </div>
    </section>
  `;
}

function ncbiLink(sampleId) {
  return sampleId ? `https://www.ncbi.nlm.nih.gov/biosample/?term=${encodeURIComponent(sampleId)}` : null;
}

async function loadDownloads() {
  const payload = await getJSON("/api/downloads");
  const orderBy = params.get("order_by") || "";
  const orderDir = params.get("order_dir") || "asc";
  const rows = orderBy === "bytes" ? sortRowsByNullableNumber([...payload.rows], "bytes", orderDir, "title") : payload.rows;
  qs("#download-release").textContent = payload.release.release_name;
  qs("#download-date").textContent = payload.release.released_on || "NA";
  renderTable(
    qs("#table-root"),
    ["Module", "Title", "Format", { label: "Bytes", sortKey: "bytes" }, "Description", "Download"],
    rows,
    (row) => `
      <td>${ellipsisText(row.module_name)}</td>
      <td>${ellipsisText(row.title)}</td>
      <td>${ellipsisText(row.file_format || "NA")}</td>
      <td>${formatNumber(row.bytes)}</td>
      <td>${ellipsisText(row.description || "NA")}</td>
      <td><a class="pill-link" href="${row.download_url}">Download</a></td>
    `,
    {
      tableClass: "download-table-fixed",

      sortState: orderBy ? { field: orderBy, dir: orderDir } : null,
      onSort: (field, dir) => {
        syncParams({ order_by: field, order_dir: dir });
        loadDownloads();
      },
    }
  );
}

function bindControls(loader) {
  qs("#filter-btn")?.addEventListener("click", () => loader(1));
  qs("#refresh-btn")?.addEventListener("click", () => loader(1));
  qs("#page-size")?.addEventListener("change", () => loader(1));
}

async function loadNps(page = Number(params.get("page") || 1)) {
  const pageSize = qs("#page-size")?.value || "25";
  const filters = serializeFilterState("nps");
  showLoading(qs("#entries-label"));
  syncParams({ page, page_size: pageSize, filters: filters || null });
  const meta = await getJSON(`/api/nps?filters=${encodeURIComponent(filters)}&page=${page}&page_size=${pageSize}`);
  updateEntriesLabel(meta, qs("#entries-label"));
  renderTable(
    qs("#table-root"),
    ["BGC ID", "SMILES", "NP Pathway", "NP Superclass", "NP Class", "GCF ID", "Membership value"],
    meta.rows,
     (row) => ({
       cells: `
         <td>${row.bgc_url ? makeLocalLink(row.bgc_url, row.bgc_source_id || "NA") : (row.bgc_source_id || "NA")}</td>
         <td>${row.predicted_smiles ? `<span class="smiles-cell"><code class="cell-ellipsis" title="${escapeHtml(row.predicted_smiles)}">${escapeHtml(row.predicted_smiles)}</code><button class="ghost-btn copy-btn" data-smiles="${escapeHtml(row.predicted_smiles)}">📋</button></span>` : "NA"}</td>
         <td>${ellipsisText(row.np_pathway || "NA")}</td>
         <td>${ellipsisText(row.np_superclass || "NA")}</td>
         <td>${ellipsisText(row.np_class || "NA")}</td>
         <td>${row.gcf_url ? makeLocalLink(row.gcf_url, row.gcf_id) : (row.gcf_id || "NA")}</td>
         <td>${makeMembershipBadge(row.membership_value, row.contig_edge, row.membership_status)}</td>
      `,
      detail: "",
    }),
    { tableClass: "np-table-fixed", columnWidths: [100, 300, 200, 180, 180, 100, 130] }
  );
  const pager = buildPager(meta, loadNps);
  if (qs("#pager-root")) qs("#pager-root").innerHTML = ""; qs("#pager-root")?.appendChild(pager);
  qs("#table-root")?.addEventListener("click", (e) => {
    const btn = e.target.closest(".copy-btn");
    if (btn) {
      const smiles = btn.dataset.smiles;
      if (smiles) navigator.clipboard.writeText(smiles).then(() => { btn.textContent = "✓"; setTimeout(() => { btn.textContent = "📋"; }, 1500); });
    }
  });
}

async function bootstrap() {
  setActiveNav();
  const page = document.body.dataset.page;
  if (page === "home") return loadHome();
  if (page === "stats") return loadStats();
  if (page === "sample") {
    buildStandardControls("q");
    await ensureBiomeOptions();
    await ensureGeoOptions();
    mountAdvancedFilters("sample", loadSamples);
    bindControls(loadSamples);
    return loadSamples(Number(params.get("page") || 1));
  }
  if (page === "tax" || page === "mag") {
    buildStandardControls("q");
    await ensureBiomeOptions();
    await ensureGeoOptions();
    ensureTaxonOptions().then(() => renderFilterBuilder("tax", loadMags));
    mountAdvancedFilters("tax", loadMags);
    bindControls(loadMags);
    return loadMags(Number(params.get("page") || 1));
  }
  if (page === "bgc") {
    buildStandardControls("q");
    const initialPage = Number(params.get("page") || 1);
    await ensureBiomeOptions();
    ensureGeoOptions();
    await ensureCategoryOptions();
    mountAdvancedFilters("bgc", loadBgcs);
    bindControls(loadBgcs);
    loadGcfDetail();
    return loadBgcs(initialPage);
  }
  if (page === "np") {
    buildStandardControls("q");
    mountAdvancedFilters("nps", loadNps);
    bindControls(loadNps);
    return loadNps(Number(params.get("page") || 1));
  }
  if (page === "download") {
    return loadDownloads();
  }
}

bootstrap().catch((error) => {
  console.error(error);
  const root = qs("#page-error");
  if (root) root.textContent = error.message;
});
