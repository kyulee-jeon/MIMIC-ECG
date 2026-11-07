# MIMIC-ECG

DICOM → OMOP **Medical Imaging CDM (MI-CDM) extension** ETL for **MIMIC-IV-ECG v1.0**, run **after** MIMIC-IV v3.1 has been loaded into OMOP CDM with [OHDSI/MIMIC](https://github.com/OHDSI/MIMIC).
Branch `kj_dicom_extension_1`. The sibling repo `MIMIC-CXR` does the same for MIMIC-CXR with the identical method; only the dataset-specific files differ (`mappings/`, `custom_mapping_csv/`, `config.example.py`, `qa/`).

| | |
|---|---|
| Structured data | MIMIC-IV v3.1 (already in the OMOP CDM: `person`, `visit_occurrence`, `procedure_occurrence`, `concept` …) |
| Image / waveform | MIMIC-IV-ECG v1.0 as **DICOM** (any folder you point `DICOM_DIR` at, e.g. a local folder, an s3fs mount or an `s3://` prefix) |
| Output | `image_occurrence`, `image_feature`, `measurement_ADD` (+ DICOM vocabulary `concept_ADD`, `vocabulary_ADD`, `concept_class_ADD`) (published reference: the already published MIMIC-IV Extension tables) |

The ETL source is always DICOM headers. The only non-DICOM input is the finished MIMIC-IV OMOP CDM used for linking (person / visit / procedure).

**Scope**: DICOM → OMOP only. Converting the original WFDB records to DICOM ([dr-you-group/mimic-iv-ecg-to-dcm](https://github.com/dr-you-group/mimic-iv-ecg-to-dcm)) is upstream of this repo.

## Medallion layers

```
bronze   DICOM files in DICOM_DIR (read-only; any folder - local disk, NAS, an s3fs mount …)
   │  extract/build_silver.py  ──►  third_party/dicom_to_parquet  (git submodule, pinned commit)
silver   <SILVER_DIR>/modality=<ECG>/tag=<8 hex>/part-*.parquet      ← same folder layout for ECG and CXR
   │  run_etl.py src … cdm       (OHDSI/MIMIC five logic steps, SQL)
gold     OMOP CDM imaging extension: cdm_image_occurrence / cdm_image_feature / cdm_measurement → *_ADD.csv
```

Silver row = one scalar of one DICOM file: `file_path, study_uid, series_uid, instance_uid, sop_class_uid, modality, tag, vr, vm, path, value`
(+ hive partitions `modality`, `tag`). `path` keeps nested sequences traceable, e.g. ECG lead 4 label = `54000100[0]/003A0200[3]/003A0203[0]/`; the ETL reads the lead number from `003A0200[k]`. Silver contains **every** tag (private tags too); the ETL only loads the tags in `mappings/tag_spec.csv`, so a new attribute is a spec change, not a re-extraction.
Point `SILVER_DIR` of both repos at the same folder: the two datasets then live side by side (`modality=ECG`, `modality=DX`, `modality=CR`).

## OHDSI/MIMIC's five logic steps, applied

| # | OHDSI/MIMIC step | Here | Artifacts |
|---|---|---|---|
| 1 | snapshot → `src_` | silver parquet → `run_etl.py src` (needed tags only; local dir or `s3://`); `sql/st_01_src_cdm_snapshot.sql` (CDM tables) | `src_dicom_header`, `src_person`, `src_visit`, `src_procedure`, `src_tag_spec`, `src_modality_profile`, `src_custom_map` |
| 2 | clean → `lk_*_clean` | `sql/lk_10_img_clean.sql`, `sql/lk_11_feature_clean.sql` | `lk_img_file_clean`, `lk_img_occurrence_clean`, `lk_img_feature_clean` |
| 3 | map codes → `lk_*_concept` | `sql/lk_20_img_concept.sql`; custom mappings = `custom_mapping_csv/*.csv` (OHDSI/MIMIC `gcpt_*.csv` format) | `lk_img_modality_concept`, `lk_img_value_concept`, **`lk_img_unmapped`** (review list) |
| 4 | join → `lk_*_mapped` | `sql/lk_30_img_mapped.sql` (person / visit / procedure links, ids) | `lk_img_occurrence_mapped`, `lk_img_feature_mapped` |
| 5 | distribute by target domain → `cdm_` | `sql/cdm_*.sql` (attribute values → `measurement`, link rows → `image_feature`) | `cdm_image_occurrence`, `cdm_image_feature`, `cdm_measurement` |
| – | unload | `export/export_csv.py` (PostgreSQL `COPY`, then an exact id round-trip check) | `*.csv` |

SQL files use `@etl` / `@cdm` / `@voc` placeholders (like OHDSI/MIMIC's `@etl_dataset`), set in `config.py`.

## MI-CDM wiki steps (ImageWG "Medical Imaging Extension Conventions") – how they are made concrete

| Wiki step | Concrete implementation |
|---|---|
| 1–2 install CDM, create extension tables | `ddl/01_micdm_tables.sql` (created as `cdm_*` in the ETL schema) |
| 3 load DICOM vocabulary | **custom** `vocabulary_id='DICOM'`, ids 2128xxxxxx – built with [paulnagy/DICOM2OMOP](https://github.com/paulnagy/DICOM2OMOP) (see Prerequisites) |
| 4 extract headers only | `extract/build_silver.py` → `dicom_to_parquet.py --skip_pixel_data` |
| 5 choose attributes | `mappings/tag_spec.csv` (single source of truth) |
| 6 series-level → `image_occurrence`; other attributes → `measurement` | unit = **(study, series)**; each attribute value becomes a measurement row |
| 7 features → `image_feature` | 1 `image_feature` row per measurement row; `image_feature_event_id` + `image_feature_event_field_concept_id` (1147330 = measurement) point at it; `image_feature_value_order` carries lead 1..12 / multi-value order |
| 8 occurrences before features | step order `cdm_10` → `cdm_40`; QA checks no orphan |
| 9 map to standard concepts | `custom_mapping_csv/` → SNOMED / DICOM; unresolved codes surface in `lk_img_unmapped`, value_as_concept_id=0 |
| 11 custom concept ids in 2-billion range | 2128000000+ (DICOM2OMOP); source concepts of `custom_mapping_csv` 2129000000+ |

## Prerequisites

1. **MIMIC-IV-ECG v1.0 data from PhysioNet** as **WFDB** (v1.0) and convert it to DICOM with [dr-you-group/mimic-iv-ecg-to-dcm](https://github.com/dr-you-group/mimic-iv-ecg-to-dcm) - the DICOM files are the input of this repo; WFDB is never read here.
2. **MIMIC-IV v3.1 in OMOP CDM v5.3.1**, built with [OHDSI/MIMIC](https://github.com/OHDSI/MIMIC) in the same PostgreSQL database (schema = `CDM_SCHEMA`). Needed from it: `person` with `person_source_value = subject_id`, `visit_occurrence`, `procedure_occurrence`, and the vocabularies (`concept`, …) with the standard concepts used in `custom_mapping_csv/` (SNOMED etc.).
3. **DICOM vocabulary** (custom `vocabulary_id = 'DICOM'`: 8,814 concepts, ids 2128000000+) from [paulnagy/DICOM2OMOP](https://github.com/paulnagy/DICOM2OMOP): `files/OMOP CDM Staging/omop_table_staging_v5.csv` holds the concepts, and its code builds the `concept`, `concept_class` and `vocabulary` rows - follow it and load them into the CDM vocabulary tables. `vocabulary/build_vocabulary_add.py` + `python run_etl.py --steps vocab` is a shortcut that produces the same rows from `omop_table_staging_v5.csv` (its `concept_ADD` is content-identical to the published `Extension/concept_ADD.csv`, only CSV quoting differs).
4. **The folder that holds the DICOM files** - you pass it at the start (`DICOM_DIR` / `--dicom_dir`); nothing is assumed about S3 or mounts. It is the folder that contains `p10/p10000032/s50414267/<file>.dcm` (i.e. the `files/` folder), and **it is written as the prefix of `image_occurrence.local_path`** (`<DICOM_DIR>/p10/p10000032/s50414267` - `image_occurrence` is series-level, so it points at the series folder, not at a file).
5. Python with `pydicom`, `pyarrow`, `psycopg2`, `pandas` (`pip install -r requirements.txt`) and the `third_party/dicom_to_parquet` submodule.

## Run

```bash
git clone --recurse-submodules <this repo>        # or: git submodule update --init
pip install -r requirements.txt
export DB_NAME=<your_db> ETL_SCHEMA=micdm_etl_ecg   # copy config.example.py to config.py (not tracked); every setting is documented there (SILVER_DIR, CDM_SCHEMA …)
export DICOM_DIR=/path/to/mimic-iv-ecg-dcm/files               # the DICOM source folder (prerequisite 4)

# bronze -> silver (resumable; smoke test first)
python extract/build_silver.py --workers 16 --limit_dirs 1 --max_files 100
python extract/build_silver.py --workers 16                       # 800,035 files

# silver -> gold
python run_etl.py --steps ddl,config,src,snapshot,clean,concept,mapped,cdm,qa
python export/export_csv.py --out work/export                      # --upload_to s3://bucket/prefix/ to also copy them to S3
python -m qa.compare_published                                     # content check against an already published Extension
pytest tests/
```

An existing silver of the same format can be reused instead of re-reading DICOM: `python run_etl.py --silver s3://bucket/prefix …` or a local `SILVER_DIR`.

## Conventions (all from the published Extension CSVs; edit in `mappings/`)

* 1 `.dcm` = 1 `image_occurrence` (study = series = instance); 68 feature rows (8 instance attributes + 5 attributes × 12 leads). Lead order = `ChannelDefinitionSequence` item index. `SamplingFrequency` replicated per lead; `ChannelSensitivityUnitsSequence` → constant millivolt (720843). Modality 4145308, anatomic site 4217142 (on `image_occurrence` only).
* No procedure link (the published ECG rows have none).
* `measurement_source_value` = 8-digit tag, `value_source_value` = raw DICOM text. Unmapped / empty CS value → `value_as_concept_id = 0`.
* ids = positional bands (`mappings/modality_profile.csv`), deterministic for the same input; the bands of the two datasets do not overlap.
* **`custom_mapping_csv/*.csv`** follow OHDSI/MIMIC's `custom_mapping_csv/gcpt_*.csv`: each file is a raw → standard value table only. One row = one *source concept* (`source_concept_id` 2129000001+, `source_vocabulary_id` = `dicom_<map>`, `concept_code` = raw DICOM code, validity dates) plus its `Maps to` relationship (`target_concept_id`, `target_concept_name` = the standard concept's name, added for readability and not used by the ETL, `relationship_id`, `reverse_relationship_id`, relationship dates, `invalid_reason_cr`). Which attribute a file belongs to is `tag_spec.csv` (`value_map` + `attribute_concept_id`), the analogue of DICOM2OMOP's attribute → value `Maps to value` (DICOM2OMOP ships it only for Modality). The ETL joins on `concept_code` and only uses valid `Maps to` rows; retire a mapping by filling `invalid_reason_cr`.
* **Never let an id pass through pandas numbers.** person / visit / procedure / event ids are 64-bit hashes (> 2^53). A nullable bigint column (e.g. `visit_occurrence_id`) read or written by pandas becomes float64 and is silently rounded - once published that way, joins to `visit_occurrence` break for some rows. Here the CSVs are written by PostgreSQL `COPY` (no pandas), config tables are read as `dtype=str`, silver is loaded with pyarrow as text, `export/export_csv.py` re-reads every written CSV and compares row count, non-null count and exact sum of each id column with the table (`--no-verify` to skip), and `tests/test_spec.py::test_no_float_path_for_ids` fails if code reads data through pandas numbers.
* `person_id` is joined as exact int64 via `person_source_value = subject_id`.
* `measurement_date` is each instance's own StudyDate (as published).
* `image_occurrence.local_path` = the **series folder**: `DICOM_DIR` + `/p<NN>/p<subject>/s<study>` (image_occurrence is series-level). The published files held a file path; `qa.compare_published` compares the folder part.

## Validation status

`python -m qa.compare_published` compares the ETL output with the already published Extension (loaded in the CDM schema) **by content** (ids are positional, so they are excluded).

| | scope | measurement + image_feature | image_occurrence |
|---|---|---|---|
| ECG | sample – 1,989 occurrences, silver built with `extract/build_silver.py` from the DICOM | 135,252 rows; identical except `visit_occurrence_id` of 4,352 rows (3.2 %, by design; an earliest-start, lowest-id date-only rule would differ in 2,244 rows) | all columns 1,989/1,989 except visit 1,925 (64 differ by design, see Known gaps) |

The content of the Extension tables is reproduced on the sample; the only difference is the visit link, which deliberately no longer follows the published date-only link (see "Known gaps"; the visit figures were computed from `lk_img_occurrence_clean` with the same logic as `lk_30` and should be re-checked with `qa.compare_published` after a full run). **The full extraction (≈ 800k files, ≈ 2 h with 8 workers) has not been run.** `qa/validate.py` structural checks pass.

## Known gaps

* `local_path` is the series folder under `DICOM_DIR`; the published files held a file path.
* **Visit link** (`sql/lk_30_img_mapped.sql`, rule in the header of that file): a stay (any visit that is not a point event, i.e. `visit_concept_id` <> 38004207: 262, 581385, 8870, 8883, 9201) whose `[visit_start_datetime, visit_end_datetime]` contains StudyDate+StudyTime wins; if there is none (or no StudyTime), a clinic record (`visit_concept_id` 38004207) whose date range contains StudyDate; else no visit. Ties: earliest start, then lowest id. A stay that only matches by date is no longer used. Result on the full ECG set (796,617 occurrences with a person; computed from the ECG `ecg_time` values and the CDM visits, not by running the ETL): 624,950 linked (463,110 stay, 161,840 clinic), 171,667 none, against 635,465 linked in the published table; 1,155 fall into two or more overlapping stays. **Versus the published Extension**: its link uses the date only (no StudyTime, stays and clinics not distinguished): every occurrence with at least one visit whose date range contains the image date is linked, the others are not (no candidate: 161,152). With several candidates (32,425) it takes the earliest start date where the start dates differ (1,327 of 1,327) and is arbitrary where they are equal (96 % of the cases; lowest id 49.8 %, highest id 50.1 %). Stay and clinic candidates are picked about half and half. This is inferred from the data (`Extension/image_occurrence.csv`), not documented. The new rule deliberately differs for 26,938 occurrences (3.4 %, 1,831,784 of 54,169,956 feature rows): 16,423 get another visit, 10,515 lose the link. The 17,243 ECGs that lose their stay under the earlier datetime-aware rule (date candidates, then datetime, then stay priority) all have an `ecg_time` (16,749 before the stay start, 493 after its end, 1 inside the window but another stay is picked; median 2.3 h, max 23.0 h). There is no tolerance before the visit start (ED registration may be stamped after the image); open decision. An earliest-start, lowest-id date-only rule would differ from the published link in 15,591 ECG occurrences, because the published pick is arbitrary among visits with the same start date. ECG sample (1,989): 1,569 linked (1,154 stay, 415 clinic), 420 none; 64 differ from the published link (3.2 %). Details: `log/visit_link_decision_20261107.md`, `log/visit_link_published_vs_new_20261107.md`.
* `measurement_lvef_ADD.csv` (echo LVEF) is not DICOM-derived and is out of scope.
* measurement uses CDM 5.4 columns (as the published CSVs do), although the base CDM is 5.3.
