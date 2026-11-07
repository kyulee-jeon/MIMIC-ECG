# Visit link decision record — MIMIC-ECG

Date: 2026-11-07
Target: `image_occurrence.visit_occurrence_id`
Summary: [docs/visit_link.md](../docs/visit_link.md)

## 1. Decision

### 1.1 Visit classification

Visits are classified by **`visit_concept_id`**, not by the `visit_source_value` string.

| Class | visit_concept_id | Meaning | Rows (src_visit 2,922,008) |
|---|---|---|---|
| Clinic (point event) | 38004207 | `subject\|date`, mostly start = end | 2,383,175 |
| Stay (visits with a duration, 5 types) | 262, 581385, 8870, 8883, 9201 | `subject\|hadm` family | 54,929 / 228,444 / 199,432 / 42,898 / 13,130 |

- The earlier regular expression (`visit_source_value ~ '^[0-9]+\|[0-9]+$'`) classified **7,195** visits with `visit_concept_id` 38004207 as stays because their value looks numeric. Under the new rule they are clinics.
- Some clinic visits end after they start (duration 1 day: 5,974; 2 days: 761; 3 days: 206; 4 days: 54; and so on). Clinic matching therefore uses the range `[start_date, end_date]`, not date `=`.

### 1.2 Link order

Within the same `person_id`:

1. **Stay (rule = `stay_datetime`)**: a stay whose `[visit_start_datetime, visit_end_datetime]` contains the image time (StudyDate + StudyTime, i.e. `ecg_time`). If there are several, the one with the earliest start, then the lowest `visit_occurrence_id`.
2. **Clinic (rule = `clinic_date`)**: if step 1 finds none (this includes ECGs without a time), a clinic visit whose `[visit_start_date, visit_end_date]` contains the image date. If there are several, the earliest start, then the lowest `visit_occurrence_id`.
3. **Neither**: `visit_occurrence_id = NULL`.

An image whose date matches but whose time lies outside the stay is **not** linked to that stay.

Rule names used in the comparisons:

| Name | Content |
|---|---|
| Date-only rule | Among visits whose `[start_date, end_date]` contains the image date, the one with the earliest start date, then the lowest id. The time is ignored. The former `LATERAL` in `lk_30` (start date → id, one row) is this rule |
| Earlier rule (datetime-aware) | `lk_30` before the change: date candidates → narrow by datetime if there are several → stay priority → earliest start |
| New rule | 1.2 above |

### 1.3 Where it is applied

| What | File | Status |
|---|---|---|
| Visit link | `sql/lk_30_img_mapped.sql` (`lk_img_visit_cand` → `lk_img_visit_link`) | changed to the new rule |
| StudyTime, visit datetimes | `sql/lk_10_img_clean.sql`, `sql/st_01_src_cdm_snapshot.sql`, `run_etl.py` | changed |
| QA output | `qa/validate.py` | adapted to the new columns (`rule`, `n_stay`, `n_clinic`) |

The rule needed these changes as well:
- `lk_10_img_clean.sql`: add `image_ts` from StudyTime (00080030) to `lk_img_file_clean` and `lk_img_occurrence_clean`.
- `st_01_src_cdm_snapshot.sql`: add `visit_start_datetime`, `visit_end_datetime`, `visit_source_value` and `visit_concept_id` to `src_visit`.
- `run_etl.py`: include tag 00080030 in the silver snapshot. Before, only StudyDate (00080020) and the tag_spec tags were read.
  **A `src_dicom_header` built earlier has no StudyTime, so `run_etl.py src` must be run again.** Otherwise `image_ts` is NULL everywhere, no stay is matched by datetime, and only clinic date matching remains.
- `lk_30_img_mapped.sql`: the date-only `LATERAL` is replaced by `lk_img_visit_cand` / `lk_img_visit_link`.
- `qa/validate.py`: prints the number of links per rule.

Columns of `lk_img_visit_link`: `modality_group, study_uid, series_uid, visit_occurrence_id, n_stay, n_clinic, rule`.

## 2. Evidence

The "earlier rule" is a reproduction of the `lk_30` logic before the change (datetime-aware). Its internal labels (`single` / `datetime` / `stay_priority` / `tie_break`) are approximations in the reproduction and are not used below; only whether an image is linked and to which visit is compared.

### 2.1 Sample (test schema, 2,000 test rows / 1,989 distinct study, series)

Computed with read-only queries and temporary tables.

| Item | Count | Share (of 1,989) |
|---|---|---|
| New rule: linked | 1,569 | 78.9 % |
| ├ stay by datetime (`stay_datetime`) | 1,154 | |
| └ clinic by date (`clinic_date`) | 415 | |
| New rule: not linked | 420 | 21.1 % |
| Earlier rule: linked | 1,587 | 79.8 % |

Comparison with the earlier rule:

| | Count | Description |
|---|---|---|
| Identical | 1,549 | 1,154 stay + 395 clinic |
| Different | 20 | see below |
| Linked only before | 18 | not linked under the new rule |
| Linked only under the new rule | 0 | |
| Not linked under either | 402 | |

- The 20 different = stay → clinic **15** (8870→38004207: 6, 8883→38004207: 1, 581385→38004207: 8) + clinic → another clinic **5** (when several clinics fall on the same day, the choice now uses `visit_start_datetime` instead of `visit_start_date`).
- ECGs that fall into two or more overlapping stays: 2. Two or more clinics on the same day: 5.

**Time state of the 15 that changed from stay to clinic**
- Without StudyTime: **0** (all 2,000 rows have an `ecg_time`; none is exactly 00:00).
- All 15 lie **before the start** of the stay they were linked to earlier, by 0.0 to 11.9 hours (median about 3.7 to 4.2 hours).
- So the time is not missing; the ECGs are **outside** that stay.

**The 18 linked only before**: 16 before the stay start (0 to 11.1 hours), 2 after its end (0.9 and 1.0 hours).

### 2.2 Full set (800,035 files)

Not a run of the ETL: the same logic was computed with pandas from the `ecg_time` values of the ECG result parquet (800,035 rows) and the CDM `visit_occurrence.csv`. Without the 3,418 that have no person, 796,617 ECGs are linkable.

| Rule | Linked | Link rate |
|---|---|---|
| Date-only | 635,465 | 79.8 % |
| Earlier rule (datetime-aware) | 635,465 | 79.8 % |
| **New rule** | **624,950** | **78.4 %** |

- New rule, linked 624,950 = stay by datetime **463,110** + clinic by date **161,840**. Not linked 171,667 (no date candidate 161,152 + links lost under the new rule 10,515).
- Compared with the date-only rule, 10,515 ECGs lose the link; none is newly linked.
- ECGs that fall into two or more overlapping stays: 1,155.
- Compared with the earlier rule, **17,243** ECGs lose their stay (linked to a stay before, now to another visit or none). All have an `ecg_time`.
  - **16,749** lie before the stay start, **493** after its end, **1** inside the window but another overlapping stay is chosen. Median distance from the window 2.3 hours, maximum 23.0 hours.
  - Stay type linked before: 581385: 6,949 / 8870: 6,781 / 262: 2,351 / 9201: 640 / 8883: 522.

## 3. Interpretation and limits

- The link rate under the new rule is slightly lower than before (sample 78.9 % vs 79.8 %, full set 78.4 % vs 79.8 %). The difference is made of links that existed because the date matched although the time lies outside the stay; when a clinic exists on the same day, it replaces the stay.
- Most of these ECGs are stamped a few hours **before** the stay starts, which may mean that the ED arrival or registration time was recorded after the image. Whether to link such ECGs to the stay within a tolerance (for example N hours before the start) is **undecided**. The rule has no tolerance.
- The five stay types include ER (8870) and observation (581385). Whether the number in their `visit_source_value` is a `hadm_id` or a `stay_id` has not been checked.
- The full-set figures in 2.2 are pandas calculations, not the result of running the ETL. Compare them with the `qa/validate.py` output after a full pipeline run.

## 4. Open items

1. Run the changed code: `run_etl.py src` must be run again (see 1.3). Only a syntax check (`py_compile`), `tests/test_spec.py` and a temporary-table run of the visit block of `lk_30` on the sample have been done; the whole pipeline has not been run.
2. Extract all 800,035 files, run the ETL and compare with the figures in 2.2.
3. Decide whether to add a tolerance before the stay start.
4. Check what the number in `visit_source_value` of the five stay types means (hadm_id or stay_id).
