# Visit link (MIMIC-ECG)

Implemented in `sql/lk_30_img_mapped.sql` (the rule is also in the header of that file).

## Rule

1. A **stay** (any visit that is not a point event, i.e. `visit_concept_id` <> 38004207: 262, 581385, 8870, 8883, 9201) whose `[visit_start_datetime, visit_end_datetime]` contains the ECG time (StudyDate + StudyTime) wins.
2. If there is none (or the ECG has no time): a **clinic** record (`visit_concept_id` = 38004207) whose date range contains StudyDate.
3. Otherwise no visit.

Ties: earliest start, then lowest id. A stay that matches by date only is not used. There is no tolerance before the visit start (an ED registration may be stamped after the image); this is an open decision.

## Result on the full ECG set

Computed from the ECG `ecg_time` values and the CDM visits, not by running the ETL.

| | ECGs |
|---|---|
| with a person | 796,617 |
| linked to a visit | 624,950 (78.5 %): 463,110 stay, 161,840 clinic |
| no visit | 171,667 |
| fall into two or more overlapping stays | 1,155 |

## Versus a date-only rule

A date-only rule links every ECG for which at least one visit's date range contains the ECG date: 635,465 linked (79.8 %). The new rule links 10,515 fewer, so 10,515 ECGs lose the link.

Versus the earlier datetime-aware rule (date candidates, then datetime, then stay priority), 17,243 ECGs lose their stay. All have an `ecg_time`: 16,749 lie before the stay start, 493 after its end, and 1 lies inside the window but another stay is picked (median 2.3 h outside the window, max 23.0 h).

Sample run (1,989 ECGs): 1,569 linked (1,154 stay, 415 clinic), 420 none.

Decision record (with the detailed counts): `log/visit_link_decision_20261107.md`.
