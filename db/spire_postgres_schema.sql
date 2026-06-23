BEGIN;

CREATE SCHEMA IF NOT EXISTS spire;
SET search_path TO gem, public;

-----------------------------------------------
-- 1. 辅助表
-----------------------------------------------
CREATE TABLE IF NOT EXISTS release_version (
    release_id BIGSERIAL PRIMARY KEY,
    release_name TEXT NOT NULL UNIQUE,
    release_label TEXT,
    released_on DATE,
    is_current BOOLEAN NOT NULL DEFAULT FALSE,
    antismash_version TEXT,
    bigslice_version TEXT,
    bgc_membership_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.4,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS download_asset (
    asset_id BIGSERIAL PRIMARY KEY,
    release_id BIGINT NOT NULL REFERENCES release_version(release_id),
    asset_key TEXT NOT NULL UNIQUE,
    module_name TEXT NOT NULL,
    title TEXT NOT NULL,
    file_format TEXT,
    file_path TEXT NOT NULL,
    md5 TEXT,
    bytes BIGINT,
    description TEXT,
    is_public BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-----------------------------------------------
-- 2. 核心实体表
-----------------------------------------------
CREATE TABLE IF NOT EXISTS sample (
    sample_pk BIGSERIAL PRIMARY KEY,
    sample_id TEXT NOT NULL UNIQUE,
    biosample_accession TEXT,
    primary_sample_accession TEXT,
    sample_name TEXT,
    project TEXT,
    biome3 TEXT,
    biome2 TEXT,
    biome1 TEXT,
    geo_region TEXT,
    collection_date_raw TEXT,
    collection_date_start TEXT,
    collection_date_end TEXT,
    collection_year INTEGER,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    has_coordinates BOOLEAN NOT NULL DEFAULT FALSE,
    is_ncbi_biosample BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT sample_lat_range CHECK (latitude IS NULL OR (latitude >= -90 AND latitude <= 90)),
    CONSTRAINT sample_lon_range CHECK (longitude IS NULL OR (longitude >= -180 AND longitude <= 180))
);

-----------------------------------------------
-- 3. SRA 层 (SQLite 实际结构: sample_project + sample_run + run)
-----------------------------------------------
CREATE TABLE IF NOT EXISTS sample_project (
    sample_pk BIGINT NOT NULL REFERENCES sample(sample_pk) ON DELETE CASCADE,
    bioproject_accession TEXT NOT NULL,
    sra_study_accession TEXT,
    project_rank INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (sample_pk, bioproject_accession)
);

CREATE TABLE IF NOT EXISTS run (
    run_accession TEXT PRIMARY KEY,
    experiment_accession TEXT,
    bioproject_accession TEXT,
    sra_study_accession TEXT,
    primary_sample_accession TEXT,
    release_date TIMESTAMPTZ,
    load_date TIMESTAMPTZ,
    download_path TEXT,
    library_name TEXT,
    library_strategy TEXT,
    platform TEXT,
    model TEXT,
    scientific_name TEXT,
    center_name TEXT,
    submission_accession TEXT,
    consent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sample_run (
    sample_pk BIGINT NOT NULL REFERENCES sample(sample_pk) ON DELETE CASCADE,
    run_accession TEXT NOT NULL REFERENCES run(run_accession) ON DELETE CASCADE,
    run_rank INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (sample_pk, run_accession)
);

-----------------------------------------------
-- 4. MAG
-----------------------------------------------
CREATE TABLE IF NOT EXISTS mag (
    mag_pk BIGSERIAL PRIMARY KEY,
    genome_id TEXT NOT NULL UNIQUE,
    sample_pk BIGINT NOT NULL REFERENCES sample(sample_pk),
    spire_cluster TEXT,
    spire_cluster_assignment TEXT,
    genome_size BIGINT,
    genome_size_est BIGINT,
    gs_est_ratio DOUBLE PRECISION,
    n_contigs INTEGER,
    n50 BIGINT,
    max_contig_length BIGINT,
    translation_table SMALLINT,
    completeness NUMERIC(5, 2),
    contamination NUMERIC(5, 2),
    drep NUMERIC(5, 2),
    n_genes INTEGER,
    gunc_taxlevel TEXT,
    clade_separation_score DOUBLE PRECISION,
    gunc_contamination DOUBLE PRECISION,
    reference_representation_score DOUBLE PRECISION,
    gunc_pass BOOLEAN,
    gunc_pass_5 BOOLEAN,
    classification TEXT,
    domain TEXT,
    phylum TEXT,
    class_name TEXT,
    order_name TEXT,
    family TEXT,
    genus TEXT,
    species TEXT,
    red_value DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-----------------------------------------------
-- 5. BGC
-----------------------------------------------
CREATE TABLE IF NOT EXISTS bgc (
    bgc_pk BIGSERIAL PRIMARY KEY,
    bgc_source_id BIGINT UNIQUE,
    bgc_name TEXT NOT NULL UNIQUE,
    mag_pk BIGINT NOT NULL REFERENCES mag(mag_pk),
    sample_pk BIGINT NOT NULL REFERENCES sample(sample_pk),
    orig_filename TEXT UNIQUE,
    contig_name TEXT,
    region_number INTEGER,
    start_nt INTEGER,
    end_nt INTEGER,
    length_nt INTEGER,
    product_primary TEXT,
    products_json TEXT,
    category_primary TEXT,
    categories_json TEXT,
    contig_edge BOOLEAN,
    antismash_tool TEXT,
    antismash_html_path TEXT,
    antismash_gbk_path TEXT,
    raw_region_json TEXT,
    predicted_smiles TEXT,
    np_classifier_pathway TEXT,
    np_classifier_superclass TEXT,
    np_classifier_class TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT bgc_len_ck CHECK (length_nt IS NULL OR length_nt >= 0)
);

-----------------------------------------------
-- 6. GCF
-----------------------------------------------
CREATE TABLE IF NOT EXISTS gcf (
    gcf_id BIGINT PRIMARY KEY,
    representative_bgc_pk BIGINT REFERENCES bgc(bgc_pk),
    representative_type TEXT,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bgc_gcf_membership (
    release_id BIGINT NOT NULL REFERENCES release_version(release_id),
    bgc_pk BIGINT NOT NULL REFERENCES bgc(bgc_pk) ON DELETE CASCADE,
    gcf_id BIGINT NOT NULL REFERENCES gcf(gcf_id),
    membership_value DOUBLE PRECISION NOT NULL,
    membership_status TEXT,
    is_core BOOLEAN NOT NULL DEFAULT FALSE,
    is_backbone BOOLEAN NOT NULL DEFAULT FALSE,
    is_peripheral BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (release_id, bgc_pk)
);

-----------------------------------------------
-- 7. 索引 (事实表)
-----------------------------------------------
CREATE INDEX IF NOT EXISTS idx_sample_biome3 ON sample (biome3);
CREATE INDEX IF NOT EXISTS idx_sample_collection_year ON sample (collection_year);
CREATE INDEX IF NOT EXISTS idx_sample_has_coordinates ON sample (has_coordinates);
CREATE INDEX IF NOT EXISTS idx_sample_sample_id_lower ON sample (lower(sample_id));
CREATE INDEX IF NOT EXISTS idx_sample_primary_accession_lower ON sample (lower(primary_sample_accession));

CREATE INDEX IF NOT EXISTS idx_sample_project_project ON sample_project (bioproject_accession);
CREATE INDEX IF NOT EXISTS idx_sample_project_sample_pk ON sample_project (sample_pk);
CREATE INDEX IF NOT EXISTS idx_sample_project_study ON sample_project (sra_study_accession);

CREATE INDEX IF NOT EXISTS idx_sample_run_run_accession ON sample_run (run_accession);
CREATE INDEX IF NOT EXISTS idx_sample_run_sample_pk ON sample_run (sample_pk);

CREATE INDEX IF NOT EXISTS idx_run_project ON run (bioproject_accession);
CREATE INDEX IF NOT EXISTS idx_run_experiment ON run (experiment_accession);
CREATE INDEX IF NOT EXISTS idx_run_release_date ON run (release_date);

CREATE INDEX IF NOT EXISTS idx_mag_sample_pk ON mag (sample_pk);
CREATE INDEX IF NOT EXISTS idx_mag_spire_cluster ON mag (spire_cluster);
CREATE INDEX IF NOT EXISTS idx_mag_species_lower ON mag (lower(species));
CREATE INDEX IF NOT EXISTS idx_mag_genus_lower ON mag (lower(genus));
CREATE INDEX IF NOT EXISTS idx_mag_phylum ON mag (phylum);
CREATE INDEX IF NOT EXISTS idx_mag_completeness ON mag (completeness);

CREATE INDEX IF NOT EXISTS idx_bgc_mag_pk ON bgc (mag_pk);
CREATE INDEX IF NOT EXISTS idx_bgc_sample_pk ON bgc (sample_pk);
CREATE INDEX IF NOT EXISTS idx_bgc_product_lower ON bgc (lower(product_primary));
CREATE INDEX IF NOT EXISTS idx_bgc_category ON bgc (category_primary);
CREATE INDEX IF NOT EXISTS idx_bgc_contig_edge ON bgc (contig_edge);
CREATE INDEX IF NOT EXISTS idx_bgc_antismash_html ON bgc (antismash_html_path);

CREATE INDEX IF NOT EXISTS idx_gcf_representative_type ON gcf (representative_type);

CREATE INDEX IF NOT EXISTS idx_bgc_gcf_membership_gcf ON bgc_gcf_membership (gcf_id);
CREATE INDEX IF NOT EXISTS idx_bgc_gcf_membership_gcf_value ON bgc_gcf_membership (gcf_id, membership_value);
CREATE INDEX IF NOT EXISTS idx_bgc_gcf_membership_status ON bgc_gcf_membership (gcf_id, membership_status);
CREATE INDEX IF NOT EXISTS idx_bgc_gcf_membership_release_gcf ON bgc_gcf_membership (release_id, gcf_id);
CREATE INDEX IF NOT EXISTS idx_bgc_gcf_membership_core_threshold ON bgc_gcf_membership (gcf_id, bgc_pk)
    WHERE membership_value <= 0.4;

-----------------------------------------------
-- 8. 物化视图 (前端查询层)
-----------------------------------------------

-- Home 统计
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_home_stats AS
SELECT
    (SELECT count(*) FROM sample) AS sample_count,
    (SELECT count(*) FROM mag) AS mag_count,
    (SELECT count(*) FROM bgc) AS bgc_count,
    (SELECT count(*) FROM gcf) AS gcf_count,
    (SELECT count(*) FROM bgc WHERE contig_edge IS FALSE) AS complete_bgc_count,
    (SELECT count(DISTINCT species) FROM mag WHERE species IS NOT NULL AND species <> '') AS species_count,
    (SELECT count(DISTINCT biome3) FROM sample WHERE biome3 IS NOT NULL AND biome3 <> '') AS environment_count,
    (SELECT count(*) FROM sample WHERE latitude IS NOT NULL AND longitude IS NOT NULL) AS geocoded_sample_count;

-- Sample 页
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_sample_page AS
SELECT
    s.sample_pk,
    s.sample_id,
    s.project,
    COALESCE(
        string_agg(DISTINCT b.category_primary, '，' ORDER BY b.category_primary)
            FILTER (WHERE b.category_primary IS NOT NULL AND btrim(b.category_primary) <> ''),
        NULL
    ) AS category,
    s.collection_date_raw AS collection_time,
    s.biome1,
    s.biome2,
    s.biome3,
    s.latitude AS lat,
    s.longitude AS lon,
    s.geo_region,
    count(DISTINCT m.mag_pk) AS mag_count,
    count(DISTINCT b.bgc_pk) AS bgc_count,
    ROW_NUMBER() OVER (
        ORDER BY
            CASE WHEN s.project IS NOT NULL AND s.project LIKE 'PRJ%'
                      AND s.sample_id ~ '^(SAMN|SAMEA|SAMD)'
                      AND s.biome1 IS NOT NULL AND s.latitude IS NOT NULL
                      AND s.collection_date_raw IS NOT NULL AND s.collection_date_raw <> '' THEN 0
                 WHEN s.project IS NOT NULL AND s.project LIKE 'PRJ%'
                      AND s.sample_id ~ '^(SAMN|SAMEA|SAMD)'
                      AND s.biome1 IS NOT NULL AND s.latitude IS NOT NULL THEN 1
                 WHEN s.project IS NOT NULL AND s.project LIKE 'PRJ%'
                      AND s.sample_id ~ '^(SAMN|SAMEA|SAMD)'
                      AND s.biome1 IS NOT NULL THEN 2
                 WHEN s.project IS NOT NULL AND s.project LIKE 'PRJ%'
                      AND s.sample_id ~ '^(SAMN|SAMEA|SAMD)' THEN 3
                 WHEN s.biome1 IS NOT NULL AND s.latitude IS NOT NULL
                      AND s.collection_date_raw IS NOT NULL AND s.collection_date_raw <> '' THEN 4
                 WHEN s.biome1 IS NOT NULL AND s.latitude IS NOT NULL THEN 5
                 WHEN s.biome1 IS NOT NULL THEN 6
                 WHEN s.collection_date_raw IS NOT NULL AND s.collection_date_raw <> '' THEN 7
                 ELSE 8
            END,
            s.sample_id
    ) AS display_order
FROM sample s
LEFT JOIN mag m ON m.sample_pk = s.sample_pk
LEFT JOIN bgc b ON b.sample_pk = s.sample_pk
GROUP BY
    s.sample_pk,
    s.sample_id,
    s.project,
    s.collection_date_raw,
    s.biome1,
    s.biome2,
    s.biome3,
    s.latitude,
    s.longitude,
    s.geo_region;

CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_sample_page_sample_pk
    ON mv_sample_page (sample_pk);
CREATE INDEX IF NOT EXISTS idx_mv_sample_page_display_order
    ON mv_sample_page (display_order);
CREATE INDEX IF NOT EXISTS idx_mv_sample_biome_lower
    ON mv_sample_page (lower(biome3));
CREATE INDEX IF NOT EXISTS idx_mv_sample_biome_lower_trgm
    ON mv_sample_page USING gin (lower(biome3) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_sample_biome1_lower
    ON mv_sample_page (lower(biome1));
CREATE INDEX IF NOT EXISTS idx_mv_sample_biome1_lower_trgm
    ON mv_sample_page USING gin (lower(biome1) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_sample_biome2_lower
    ON mv_sample_page (lower(biome2));
CREATE INDEX IF NOT EXISTS idx_mv_sample_biome2_lower_trgm
    ON mv_sample_page USING gin (lower(biome2) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_sample_page_project_lower
    ON mv_sample_page (lower(project));
CREATE INDEX IF NOT EXISTS idx_mv_sample_page_category_lower
    ON mv_sample_page (lower(category));
CREATE INDEX IF NOT EXISTS idx_mv_sample_sample_id_lower
    ON mv_sample_page (lower(sample_id));
CREATE INDEX IF NOT EXISTS idx_mv_sample_sampleid_lower_trgm
    ON mv_sample_page USING gin (lower(sample_id) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_sample_category_lower_trgm
    ON mv_sample_page USING gin (lower(category) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_sample_project_lower_trgm
    ON mv_sample_page USING gin (lower(project) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_sample_mag_count
    ON mv_sample_page (mag_count);
CREATE INDEX IF NOT EXISTS idx_mv_sample_bgc_count
    ON mv_sample_page (bgc_count);

-- MAG 页
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_mag_page AS
SELECT
    m.mag_pk,
    m.genome_id,
    s.sample_id,
    s.biome3,
    m.species,
    m.spire_cluster,
    m.completeness,
    m.contamination,
    m.genome_size,
    m.n_genes AS gene_count,
    count(DISTINCT b.bgc_pk) AS bgc_count,
    s.biome1,
    s.biome2,
    m.domain,
    m.phylum,
    m.class_name,
    m.order_name,
    m.family,
    m.genus,
    COALESCE(
        string_agg(DISTINCT b2.category_primary, '，' ORDER BY b2.category_primary)
            FILTER (WHERE b2.category_primary IS NOT NULL AND btrim(b2.category_primary) <> ''),
        NULL
    ) AS category_preview
FROM mag m
JOIN sample s ON s.sample_pk = m.sample_pk
LEFT JOIN bgc b ON b.mag_pk = m.mag_pk
LEFT JOIN bgc b2 ON b2.mag_pk = m.mag_pk
GROUP BY
    m.mag_pk,
    m.genome_id,
    s.sample_id,
    s.biome3,
    m.species,
    m.spire_cluster,
    m.completeness,
    m.contamination,
    m.genome_size,
    m.n_genes,
    s.biome1,
    s.biome2,
    m.domain,
    m.phylum,
    m.class_name,
    m.order_name,
    m.family,
    m.genus;

CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_mag_page_mag_pk
    ON mv_mag_page (mag_pk);
CREATE INDEX IF NOT EXISTS idx_mv_mag_sample_id_lower
    ON mv_mag_page (lower(sample_id));
CREATE INDEX IF NOT EXISTS idx_mv_mag_page_species_lower
    ON mv_mag_page (lower(species));
CREATE INDEX IF NOT EXISTS idx_mv_mag_biome3_lower_trgm
    ON mv_mag_page USING gin (lower(biome3) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_mag_biome1_lower_trgm
    ON mv_mag_page USING gin (lower(biome1) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_mag_biome2_lower_trgm
    ON mv_mag_page USING gin (lower(biome2) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_mag_genome_id ON mv_mag_page (genome_id);
CREATE INDEX IF NOT EXISTS idx_mv_mag_genome_id_lower
    ON mv_mag_page (lower(genome_id));
CREATE INDEX IF NOT EXISTS idx_mv_mag_genomeid_lower_trgm
    ON mv_mag_page USING gin (lower(genome_id) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_mag_genus_lower_trgm
    ON mv_mag_page USING gin (lower(genus) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_mag_sampleid_lower_trgm
    ON mv_mag_page USING gin (lower(sample_id) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_mag_species_lower_trgm
    ON mv_mag_page USING gin (lower(species) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_mag_biome1_lower
    ON mv_mag_page (lower(biome1));
CREATE INDEX IF NOT EXISTS idx_mv_mag_biome2_lower
    ON mv_mag_page (lower(biome2));
CREATE INDEX IF NOT EXISTS idx_mv_mag_biome3_lower
    ON mv_mag_page (lower(biome3));
CREATE INDEX IF NOT EXISTS idx_mv_mag_sample_id_lower_genome_id
    ON mv_mag_page (lower(sample_id), genome_id);
CREATE INDEX IF NOT EXISTS idx_mv_mag_completeness
    ON mv_mag_page (completeness);
CREATE INDEX IF NOT EXISTS idx_mv_mag_contamination
    ON mv_mag_page (contamination);
CREATE INDEX IF NOT EXISTS idx_mv_mag_bgc_count
    ON mv_mag_page (bgc_count);
CREATE INDEX IF NOT EXISTS idx_mv_mag_cat_preview_lower
    ON mv_mag_page (lower(category_preview));
CREATE INDEX IF NOT EXISTS idx_mv_mag_phylum_lower ON mv_mag_page (lower(phylum));
CREATE INDEX IF NOT EXISTS idx_mv_mag_phylum_lower_trgm ON mv_mag_page USING gin (lower(phylum) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_mag_class_name_lower ON mv_mag_page (lower(class_name));
CREATE INDEX IF NOT EXISTS idx_mv_mag_class_name_lower_trgm ON mv_mag_page USING gin (lower(class_name) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_mag_genus_lower ON mv_mag_page (lower(genus));

-- BGC 页
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_bgc_page AS
SELECT
    b.bgc_pk,
    b.bgc_name,
    b.bgc_source_id,
    m.genome_id,
    s.sample_id,
    s.biome3,
    s.biome1,
    s.biome2,
    m.species,
    m.domain,
    m.phylum,
    m.class_name,
    m.order_name,
    m.family,
    m.genus,
    b.product_primary AS product,
    b.category_primary AS category,
    b.length_nt AS length,
    b.contig_edge,
    gm.gcf_id,
    gm.membership_value,
    gm.membership_status,
    b.antismash_html_path,
    b.predicted_smiles,
    b.np_classifier_pathway AS NP_pathway,
    b.np_classifier_superclass AS NP_superclass,
    b.np_classifier_class AS NP_class
FROM bgc b
JOIN mag m ON m.mag_pk = b.mag_pk
JOIN sample s ON s.sample_pk = b.sample_pk
LEFT JOIN bgc_gcf_membership gm ON gm.bgc_pk = b.bgc_pk;

CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_bgc_page_bgc_pk
    ON mv_bgc_page (bgc_pk);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_page_gcf_id
    ON mv_bgc_page (gcf_id);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_page_membership_value
    ON mv_bgc_page (membership_value);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_page_bgc_source_id
    ON mv_bgc_page (bgc_source_id);

-- Additional indexes for filter performance
CREATE INDEX IF NOT EXISTS idx_mv_bgc_genome_id_lower ON mv_bgc_page (lower(genome_id));
CREATE INDEX IF NOT EXISTS idx_mv_bgc_sample_id_lower ON mv_bgc_page (lower(sample_id));
CREATE INDEX IF NOT EXISTS idx_mv_bgc_lower_genome_id_src ON mv_bgc_page (lower(genome_id), bgc_source_id);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_biome1_lower ON mv_bgc_page (lower(biome1));
CREATE INDEX IF NOT EXISTS idx_mv_bgc_biome2_lower ON mv_bgc_page (lower(biome2));
CREATE INDEX IF NOT EXISTS idx_mv_bgc_biome3_lower ON mv_bgc_page (lower(biome3));
CREATE INDEX IF NOT EXISTS idx_mv_bgc_biome1_lower_trgm ON mv_bgc_page USING gin (lower(biome1) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_biome2_lower_trgm ON mv_bgc_page USING gin (lower(biome2) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_biome3_lower_trgm ON mv_bgc_page USING gin (lower(biome3) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_lower_b1_src ON mv_bgc_page (lower(biome1), bgc_source_id);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_lower_b2_src ON mv_bgc_page (lower(biome2), bgc_source_id);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_lower_b3_src ON mv_bgc_page (lower(biome3), bgc_source_id);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_category_lower ON mv_bgc_page (lower(category));
CREATE INDEX IF NOT EXISTS idx_mv_bgc_product_lower ON mv_bgc_page (lower(product));
CREATE INDEX IF NOT EXISTS idx_mv_bgc_species ON mv_bgc_page (species);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_species_lower ON mv_bgc_page (lower(species));
CREATE INDEX IF NOT EXISTS idx_mv_bgc_species_lower_trgm ON mv_bgc_page USING gin (lower(species) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_contig_edge ON mv_bgc_page (contig_edge);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_genomeid_lower_trgm ON mv_bgc_page USING gin (lower(genome_id) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_sampleid_lower_trgm ON mv_bgc_page USING gin (lower(sample_id) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_product_lower_trgm ON mv_bgc_page USING gin (lower(product) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_category_lower_trgm ON mv_bgc_page USING gin (lower(category) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_sid_lower_src_pk ON mv_bgc_page (lower(sample_id), bgc_source_id, bgc_pk);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_gid_lower_src_pk ON mv_bgc_page (lower(genome_id), bgc_source_id, bgc_pk);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_length ON mv_bgc_page (length);

-- GCF 页
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_gcf_page AS
SELECT
    g.gcf_id,
    g.representative_type,
    count(*) AS bgc_count,
    count(*) FILTER (WHERE b.contig_edge IS FALSE) AS complete_bgc_count,
    count(*) FILTER (WHERE b.contig_edge IS TRUE) AS incomplete_bgc_count,
    round(avg(b.length_nt)::numeric, 2) AS mean_length,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY b.length_nt) AS median_length,
    round(avg(gm.membership_value)::numeric, 4) AS mean_membership_value,
    count(DISTINCT b.mag_pk) AS genome_count,
    count(DISTINCT s.sample_pk) AS sample_count,
    count(DISTINCT m.species) FILTER (WHERE m.species IS NOT NULL AND m.species <> '') AS species_count,
    count(*) FILTER (WHERE gm.is_backbone) AS backbone_bgc_count,
    count(*) FILTER (WHERE gm.is_core) AS core_bgc_count,
    count(*) FILTER (WHERE gm.is_peripheral OR gm.membership_value > 0.4) AS peripheral_bgc_count
FROM gcf g
JOIN bgc_gcf_membership gm ON gm.gcf_id = g.gcf_id
JOIN bgc b ON b.bgc_pk = gm.bgc_pk
JOIN mag m ON m.mag_pk = b.mag_pk
JOIN sample s ON s.sample_pk = b.sample_pk
GROUP BY g.gcf_id, g.representative_type;

CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_gcf_page_gcf_id
    ON mv_gcf_page (gcf_id);
CREATE INDEX IF NOT EXISTS idx_mv_gcf_page_representative_type
    ON mv_gcf_page (representative_type);
CREATE INDEX IF NOT EXISTS idx_mv_gcf_page_bgc_count
    ON mv_gcf_page (bgc_count DESC);
CREATE INDEX IF NOT EXISTS idx_mv_gcf_page_mean_membership_value
    ON mv_gcf_page (mean_membership_value);

COMMIT;

-- NP 页
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_np_page AS
SELECT
    b.bgc_source_id,
    b.predicted_smiles,
    b.np_classifier_pathway AS np_pathway,
    b.np_classifier_superclass AS np_superclass,
    b.np_classifier_class AS np_class,
    b.contig_edge,
    bgm.gcf_id,
    bgm.membership_value
FROM bgc b
LEFT JOIN bgc_gcf_membership bgm ON bgm.bgc_pk = b.bgc_pk
WHERE b.np_classifier_pathway IS NOT NULL
   OR b.np_classifier_superclass IS NOT NULL
   OR b.np_classifier_class IS NOT NULL
   OR b.predicted_smiles IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_np_page_bgc_source_id
    ON mv_np_page (bgc_source_id);
CREATE INDEX IF NOT EXISTS idx_mv_np_pathway_lower ON mv_np_page (lower(np_pathway));
CREATE INDEX IF NOT EXISTS idx_mv_np_superclass_lower ON mv_np_page (lower(np_superclass));
CREATE INDEX IF NOT EXISTS idx_mv_np_class_lower ON mv_np_page (lower(np_class));
