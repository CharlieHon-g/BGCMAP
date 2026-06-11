# Spire 数据库结构设计

这版设计是按你现在最核心的前端逻辑反推出来的：

- `Home / Sample / MAG / BGC / GCF / Download / Help`
- 核心关系是 `Sample -> MAG -> BGC -> GCF`
- `Sample` 页面必须一行一个样本
- `MAG`、`Run`、`BioProject` 不是和样本一对一
- `sample_id` 需要支持跳转 NCBI
- `MAG` 数量和 `BGC` 数量要能从样本页直接联动跳转

我建议你正式库采用 `PostgreSQL` 作为在线库，`Python/DuckDB` 只作为离线清洗和导入工具。

原因很简单：

- 你的数据量已经明显超过轻量演示库的舒适区
- `MAG` 约 `1,158,553`
- `BGC` 约 `3,343,403`
- `GCF membership` 约 `3,343,403`
- `SRA run` 约 `108,321`
- 后面还会有搜索、分页、联动跳转和汇总统计

---

## 1. 推荐的三层结构

### 第一层：事实表

这是最核心的真实数据层：

- `sample`
- `sra_project`
- `sra_experiment`
- `sra_run`
- `mag`
- `bgc`
- `gcf`
- `bgc_gcf_membership`

### 第二层：字典/辅助表

- `environment_dictionary`
- `sample_identifier`
- `download_asset`
- `release_version`

### 第三层：前端汇总层

这些不是原始事实表，而是为了前端页面和查询速度服务：

- `mv_home_stats`
- `mv_sample_page`
- `mv_mag_page`
- `mv_bgc_page`
- `mv_gcf_page`

这一步很重要。  
你现在的站点不是纯后台数据库，而是“带多页面检索和联动跳转的科研门户”，所以必须有前端专用汇总层。

---

## 2. 为什么这样拆表

### `sample` 作为全站主入口

你现在已经确认了一个关键事实：

- `sample_id` 才是一行一个样本的最稳定主键
- `BioProject / Experiment / Run` 都不是 1 对 1

所以主实体必须是 `sample`，不是 `project`，也不是 `run`。

`sample` 表负责：

- 样本唯一主键
- collection time
- biome
- 经纬度
- NCBI BioSample 跳转基础字段

### `sra_project / sra_experiment / sra_run` 单独拆开

这是为了正确处理下面这种真实关系：

- 一个样本可以对应多个 `BioProject`
- 一个样本可以对应多个 `Experiment`
- 一个 `Experiment` 可以对应多个 `Run`

如果你把这些强行塞进 `sample` 表，会立刻出现：

- 字段不再一对一
- 搜索难做
- 表格展示混乱
- 后期导出很痛苦

所以这里一定要标准化。

### `mag` 和 `bgc` 必须都连回 `sample`

虽然 `BGC` 来源于 `MAG`，`MAG` 来源于 `Sample`，但我仍然建议在 `bgc` 表上保留 `sample_pk` 外键。

原因是：

- 样本页要快速统计 `BGC_count`
- BGC 页面会按 `sample_id` 联动筛选
- 3 百万级数据上，少一次联表就会更稳

这不是“重复设计”，这是典型的查询友好型设计。

### `gcf` 和 `bgc_gcf_membership` 分开

这里不要把 `gcf_id` 和 `membership_value` 直接硬塞到 `bgc` 表里。

更合理的是：

- `gcf` 表保存家族本身
- `bgc_gcf_membership` 保存某条 `BGC` 属于哪个 `GCF`、距离是多少、属于 `core/backbone/peripheral` 哪一类

原因：

- 这本来就是一张“membership”关系表
- 后期如果你有多个 release 或多个 clustering version，这个结构更稳

---

## 3. 每张表的职责

### `sample`

一行一个样本，是前端 `Sample` 页主表的来源。

建议关键字段：

- `sample_id`
- `biosample_accession`
- `primary_sample_accession`
- `group1/group2/group3`
- `collection_date_raw`
- `collection_date_start`
- `collection_date_end`
- `collection_year`
- `latitude`
- `longitude`
- `is_ncbi_biosample`

这里我专门保留了：

- `collection_date_raw`
- `collection_date_start`
- `collection_date_end`

因为你当前日期数据并不总是标准单日格式，像：

- `2015`
- `2016-11`
- `2018-06/2019-06`

直接只存一个 `DATE` 会丢信息。

### `sample_identifier`

这个表是为了解决一个现实问题：

- 一个样本除了 `sample_id` 外，还会出现 `BioSample accession`
- `SRA Sample accession`
- `SampleName`
- `query_biosample`

所以不建议只在 `sample` 表里塞一个 `Sample accession` 字段。  
更稳的办法是：

- `sample` 保留主字段
- 所有别名/辅助 accession 放在 `sample_identifier`

### `sra_project`

一行一个 `BioProject`。

你前端暂时不一定直接展示很多项目细节，但这个表必须有，不然：

- 无法做 `project_count`
- 无法后面扩展项目页
- 无法规范处理同一样本属于多个项目

### `sra_experiment`

这一层保存：

- `Experiment accession`
- `library_strategy`
- `library_source`
- `platform`
- `model`

这是 SRA 设计里非常自然的一层，也是你后续区分：

- `WGS`
- `AMPLICON`
- `OTHER`

最关键的位置。

### `sra_run`

这一层保存：

- `Run accession`
- `release_date`
- `spots / bases`
- `download_path`

这张表是原始运行层，不应该跟 `sample` 混在一起。

### `mag`

一行一个 MAG。

建议它成为 `MAG` 页面主表来源，保存：

- `genome_id`
- `sample_pk`
- `spire_cluster`
- `genome_size`
- `n_contigs`
- `n50`
- `completeness`
- `contamination`
- `n_genes`
- `domain/phylum/class/order/family/genus/species`

### `bgc`

一行一个 BGC。

这是 `BGC` 页面最核心的事实表。

建议保存：

- `bgc_name`
- `display_bgc_id`
- `bgc_source_id`
- `mag_pk`
- `sample_pk`
- `orig_filename`
- `contig_name`
- `region_number`
- `start_nt`
- `end_nt`
- `length_nt`
- `product_primary`
- `products`
- `category_primary`
- `categories`
- `contig_edge`
- `antismash_html_path`
- `antismash_gbk_path`
- `raw_region_json`

这里我特别保留了 `raw_region_json`，因为 antiSMASH 原始区段信息后续很可能还会被你继续挖字段。

### `gcf`

一行一个 GCF。

建议保存：

- `gcf_id`
- `representative_bgc_pk`
- `representative_type`

### `bgc_gcf_membership`

这是整个数据库非常关键的一张关系表。

它负责：

- 一条 BGC 属于哪个 GCF
- `membership_value`
- `membership_status`
- `is_core`
- `is_backbone`
- `is_peripheral`
- 不同 release 下的 membership 版本

这张表直接支撑：

- `BGC` 页面 `GCF ID` 列
- `GCF` 页面家族成员统计
- `membership value > 0.4` 的颜色提示

---

## 4. 为什么必须做物化视图

如果你直接让前端每次都去扫事实表：

- 样本页要统计 `MAG_count / BGC_count`
- MAG 页要统计 `BGC_count`
- BGC 页要连 `MAG + Sample + GCF membership`
- GCF 页要做 family summary

那你每个页面都会变成大联表。

在你这个数据量下，这不是最稳的方案。

所以我建议用物化视图直接对应页面：

- `mv_sample_page`
- `mv_mag_page`
- `mv_bgc_page`
- `mv_gcf_page`

也就是：

- 事实层负责真实数据
- 物化视图负责前端检索页

这会让前端开发和后端查询都明显简单很多。

---

## 5. 每个页面对应哪个表

### Home

主要来自：

- `mv_home_stats`
- `release_version`

### Sample 页

主要来自：

- `mv_sample_page`

搜索字段：

- `sample_id`
- `project`
- `category`
- `biome`

### MAG 页

主要来自：

- `mv_mag_page`

搜索字段：

- `genome_id`
- `species`
- `biome`
- `sample_id`

### BGC 页

主要来自：

- `mv_bgc_page`

搜索字段：

- `bgc_name / display_bgc_id`
- `genome_id`
- `gcf_id`

### GCF 页

主要来自：

- `mv_gcf_page`

详情成员表来自：

- `bgc_gcf_membership`
- `bgc`
- `mag`
- `sample`

### Download 页

主要来自：

- `download_asset`
- `release_version`

---

## 6. 你最需要的索引

下面这些是我认为真正“必须建”的。

### 样本层

- `sample(sample_id)` 唯一索引
- `sample(group3)` 过滤索引
- `sample(collection_year)` 时间过滤索引
- `sample_identifier(identifier_type, identifier_value)` 唯一索引

原因：

- `Sample` 页会频繁按 `sample_id / project / category / biome / accession` 检索

### SRA 层

- `sra_experiment(sample_pk)`
- `sra_experiment(bioproject_accession)`
- `sra_run(sample_pk)`
- `sra_run(experiment_accession)`

原因：

- 样本详情和后续下载页很容易需要展示 `project_count / run_count`

### MAG 层

- `mag(genome_id)` 唯一索引
- `mag(sample_pk)`
- `mag(spire_cluster)`
- `GIN lower(species)` trigram 索引

原因：

- `MAG` 页核心搜索就是 `genome_id / species / sample_id`

### BGC 层

- `bgc(bgc_name)` 唯一索引
- `bgc(bgc_source_id)` 唯一索引
- `bgc(mag_pk)`
- `bgc(sample_pk)`
- `bgc(contig_edge)`
- `GIN lower(product_primary)` trigram 索引

原因：

- `BGC` 页会频繁按 `Genome ID / BGC / Sample / Product` 做组合查询

### GCF membership 层

- `bgc_gcf_membership(gcf_id)`
- `bgc_gcf_membership(gcf_id, membership_value)`
- `bgc_gcf_membership(gcf_id, membership_status)`
- `partial index WHERE membership_value <= 0.4`

原因：

- `GCF` 页和 `BGC` 页都会频繁碰 `0.4 threshold`
- 这个索引非常值

### 物化视图层

你前端真正访问最多的，不是底层表，而是页面视图。

所以必须给这些物化视图建索引：

- `mv_sample_page(sample_id, biome)`
- `mv_mag_page(genome_id, sample_id, biome)`
- `mv_bgc_page(bgc_name, genome_id, gcf_id, sample_id)`
- `mv_gcf_page(gcf_id, representative_type)`

---

## 7. 我建议的搜索策略

### 精确/前缀搜索

对这些字段，优先走普通索引：

- `sample_id`
- `genome_id`
- `gcf_id`
- `run_accession`
- `experiment_accession`
- `bioproject_accession`

### 模糊搜索

对这些字段，建议用 `pg_trgm`：

- `species`
- `product_primary`
- `project`
- `category`
- `primary_sample_accession`

原因：

- 科研用户经常不会输入完整字段
- `ILIKE '%xxx%'` 没 trigram 会很慢

---

## 8. 这个设计最适合你的地方

### 好处 1：完全匹配你的前端跳转关系

你最关心的这些都能直接支持：

- `Sample -> MAG`
- `Sample -> BGC`
- `MAG -> BGC`
- `BGC -> MAG`
- `BGC -> GCF`
- `Sample ID -> NCBI`

### 好处 2：正确处理 “一个样本多个项目/多个 run”

这一点你前面已经确认过很多次了。  
这个结构不会把这种正常关系当成脏数据。

### 好处 3：对后续扩展很稳

以后你想再加：

- taxonomy 汇总页
- project 页
- 全球地图页
- sample 详情页
- release 历史页

这个底层都能接住。

---

## 9. 我建议你下一步怎么做

最稳的顺序是：

1. 先建 `sample / sra_project / sra_experiment / sra_run / mag / bgc / gcf / bgc_gcf_membership`
2. 写 ETL，把现有 TSV / CSV / antiSMASH JSON 装进去
3. 再刷新 `mv_sample_page / mv_mag_page / mv_bgc_page / mv_gcf_page`
4. 最后让前端页面只查物化视图

一句话说：

**前端查视图，后台保留事实表。**

这会是你这个数据库现在最稳、最清晰、最像正式科研门户的做法。

---

## 10. 已生成的文件

对应 SQL DDL 文件在这里：

- [spire_postgres_schema.sql](db/spire_postgres_schema.sql)

如果你愿意，我下一步可以继续直接帮你做两件事里的一个：

- 按这个 schema 再给你写一份 `ETL 导入脚本设计`
- 或者继续往下，把 `Sample/MAG/BGC/GCF` 四个页面的后端查询 SQL 一起写好
