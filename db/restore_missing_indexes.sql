-- =============================================
-- 恢复 gem_portal.dump 后需要补充的索引
-- 用法: psql -d gem_portal -f restore_missing_indexes.sql
-- 共 43 个索引
-- =============================================

-- bgc 表 UNIQUE KEY (来自 UNIQUE 约束)
CREATE UNIQUE INDEX IF NOT EXISTS bgc_bgc_name_key ON gem.bgc USING btree (bgc_name);
CREATE UNIQUE INDEX IF NOT EXISTS bgc_bgc_source_id_key ON gem.bgc USING btree (bgc_source_id);
CREATE UNIQUE INDEX IF NOT EXISTS bgc_orig_filename_key ON gem.bgc USING btree (orig_filename);
CREATE UNIQUE INDEX IF NOT EXISTS mag_genome_id_key ON gem.mag USING btree (genome_id);
CREATE UNIQUE INDEX IF NOT EXISTS sample_sample_id_key ON gem.sample USING btree (sample_id);
CREATE UNIQUE INDEX IF NOT EXISTS download_asset_asset_key_key ON gem.download_asset USING btree (asset_key);
CREATE UNIQUE INDEX IF NOT EXISTS release_version_release_name_key ON gem.release_version USING btree (release_name);
CREATE UNIQUE INDEX IF NOT EXISTS mv_biome_counts_field_label_idx ON gem.mv_biome_counts USING btree (field, label);

-- mv_bgc_page 索引 (性能关键)
CREATE INDEX IF NOT EXISTS idx_mv_bgc_bgc_name_lower ON gem.mv_bgc_page USING btree (lower(bgc_name));
CREATE INDEX IF NOT EXISTS idx_mv_bgc_bgcname_lower_trgm ON gem.mv_bgc_page USING gin (lower(bgc_name) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_genome_id_lower ON gem.mv_bgc_page USING btree (lower(genome_id));
CREATE INDEX IF NOT EXISTS idx_mv_bgc_genomeid_lower_trgm ON gem.mv_bgc_page USING gin (lower(genome_id) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_sample_id_lower ON gem.mv_bgc_page USING btree (lower(sample_id));
CREATE INDEX IF NOT EXISTS idx_mv_bgc_sampleid_lower_trgm ON gem.mv_bgc_page USING gin (lower(sample_id) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_product_lower ON gem.mv_bgc_page USING btree (lower(product));
CREATE INDEX IF NOT EXISTS idx_mv_bgc_product_lower_trgm ON gem.mv_bgc_page USING gin (lower(product) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_category_lower_trgm ON gem.mv_bgc_page USING gin (lower(category) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_biome1_lower ON gem.mv_bgc_page USING btree (lower(biome1));
CREATE INDEX IF NOT EXISTS idx_mv_bgc_biome2_lower ON gem.mv_bgc_page USING btree (lower(biome2));
CREATE INDEX IF NOT EXISTS idx_mv_bgc_biome3_lower ON gem.mv_bgc_page USING btree (lower(biome));
CREATE INDEX IF NOT EXISTS idx_mv_bgc_np_class_lower ON gem.mv_bgc_page USING btree (lower(np_class));
CREATE INDEX IF NOT EXISTS idx_mv_bgc_np_class_lower_trgm ON gem.mv_bgc_page USING gin (lower(np_class) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_np_pathway_lower ON gem.mv_bgc_page USING btree (lower(np_pathway));
CREATE INDEX IF NOT EXISTS idx_mv_bgc_np_pathway_lower_trgm ON gem.mv_bgc_page USING gin (lower(np_pathway) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_np_superclass_lower ON gem.mv_bgc_page USING btree (lower(np_superclass));
CREATE INDEX IF NOT EXISTS idx_mv_bgc_np_superclass_lower_trgm ON gem.mv_bgc_page USING gin (lower(np_superclass) gin_trgm_ops);
-- 复合索引 (用于 ORDER BY bgc_source_id 查询)
CREATE INDEX IF NOT EXISTS idx_mv_bgc_lower_b1_src ON gem.mv_bgc_page USING btree (lower(biome1), bgc_source_id);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_lower_b2_src ON gem.mv_bgc_page USING btree (lower(biome2), bgc_source_id);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_lower_b3_src ON gem.mv_bgc_page USING btree (lower(biome), bgc_source_id);
CREATE INDEX IF NOT EXISTS idx_mv_bgc_lower_genome_id_src ON gem.mv_bgc_page USING btree (lower(genome_id), bgc_source_id);

-- mv_mag_page 索引
CREATE INDEX IF NOT EXISTS idx_mv_mag_genome_id_lower ON gem.mv_mag_page USING btree (lower(genome_id));
CREATE INDEX IF NOT EXISTS idx_mv_mag_genomeid_lower_trgm ON gem.mv_mag_page USING gin (lower(genome_id) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_mag_sample_id_lower ON gem.mv_mag_page USING btree (lower(sample_id));
CREATE INDEX IF NOT EXISTS idx_mv_mag_sampleid_lower_trgm ON gem.mv_mag_page USING gin (lower(sample_id) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_mag_biome_lower_trgm ON gem.mv_mag_page USING gin (lower(biome) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_mag_species_lower_trgm ON gem.mv_mag_page USING gin (lower(species) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_mag_biome1_lower ON gem.mv_mag_page USING btree (lower(biome1));
CREATE INDEX IF NOT EXISTS idx_mv_mag_biome2_lower ON gem.mv_mag_page USING btree (lower(biome2));
CREATE INDEX IF NOT EXISTS idx_mv_mag_biome3_lower ON gem.mv_mag_page USING btree (lower(biome));

-- mv_sample_page 索引
CREATE INDEX IF NOT EXISTS idx_mv_sample_sample_id_lower ON gem.mv_sample_page USING btree (lower(sample_id));
CREATE INDEX IF NOT EXISTS idx_mv_sample_sampleid_lower_trgm ON gem.mv_sample_page USING gin (lower(sample_id) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_sample_category_lower_trgm ON gem.mv_sample_page USING gin (lower(category) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_sample_biome_lower_trgm ON gem.mv_sample_page USING gin (lower(biome) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_sample_project_lower_trgm ON gem.mv_sample_page USING gin (lower(project) gin_trgm_ops);
