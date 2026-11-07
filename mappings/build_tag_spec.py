"""Generate mappings/tag_spec.csv (and the derived custom-mapping CSVs) -- run once, commit the output.

tag_spec.csv is the single place that says *which* DICOM attribute becomes *which* CDM row.
It replaces the xlsx field lists (cxr-metadata-field_*.xlsx, mimic-ecg-metadata_*.xlsx) used in the
earlier notebooks.  attribute_concept_id comes from DICOM2OMOP's omop_table_staging_v5.csv
(concept_code = 8-hex-digit DICOM tag, concept_class_id = 'DICOM Attributes').

Usage:
    python mappings/build_tag_spec.py \
        --staging  <DICOM2OMOP>/files/"OMOP CDM Staging"/omop_table_staging_v5.csv \
"""
import argparse
import csv
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))

COLS = ["modality_group", "block", "k_scope", "row_seq", "tag", "keyword", "vr", "target_table",
        "value_field", "attribute_concept_id", "value_map", "const_source_value", "const_concept_id"]

# ECG: 8 instance rows + 5 attributes x 12 leads = 68 rows / DICOM file.
# block: pre (instance rows before the lead rows) | channel (per lead) | post (instance rows after)
# k_scope: instance = one row | channel = value per lead, read from 003A0200[k] |
#          channel_repl = single DICOM value replicated for every lead | channel_const = constant per lead
ECG = [
    # block,   k_scope,       seq, tag,        keyword,                          vr,   value_field,         value_map,        const_src, const_cid
    ("pre",     "instance",     0, "00200011", "SeriesNumber",                   "IS", "value_as_number",     "",              "", ""),
    ("pre",     "instance",     1, "00200013", "InstanceNumber",                 "IS", "value_as_number",     "",              "", ""),
    ("pre",     "instance",     2, "54001004", "WaveformBitsAllocated",          "US", "value_as_number",     "",              "", ""),
    ("pre",     "instance",     3, "003A0005", "NumberOfWaveformChannels",       "US", "value_as_number",     "",              "", ""),
    ("pre",     "instance",     4, "003A0010", "NumberOfWaveformSamples",        "UL", "value_as_number",     "",              "", ""),
    ("channel", "channel_repl", 0, "003A001A", "SamplingFrequency",              "DS", "value_as_number",     "",              "", ""),
    ("channel", "channel",      1, "003A0203", "ChannelLabel",                   "SH", "value_as_concept_id", "ecg_channel_label", "", ""),
    ("channel", "channel",      2, "003A0210", "ChannelSensitivity",             "DS", "value_as_number",     "",              "", ""),
    ("channel", "channel_const", 3, "003A0211", "ChannelSensitivityUnitsSequence", "SQ", "value_as_concept_id", "",           "millivolt", "720843"),
    ("channel", "channel",      4, "003A0213", "ChannelBaseline",                "DS", "value_as_number",     "",              "", ""),
    ("post",    "instance",    65, "003A021A", "WaveformBitsStored",             "US", "value_as_number",     "",              "", ""),
    ("post",    "instance",    66, "003A0220", "FilterLowFrequency",             "DS", "value_as_number",     "",              "", ""),
    ("post",    "instance",    67, "003A0221", "FilterHighFrequency",            "DS", "value_as_number",     "",              "", ""),
]



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--staging", required=True)
    a = ap.parse_args()

    stg = pd.read_csv(a.staging, dtype=str)
    attr = stg[stg.concept_class_id == "DICOM Attributes"].set_index("concept_code")["concept_id"]

    rows = []
    for block, scope, seq, tag, kw, vr, vf, vmap, csrc, ccid in ECG:
        rows.append(["ECG", block, scope, seq, tag, kw, vr, "measurement", vf, attr[tag], vmap, csrc, ccid])

    out = os.path.join(HERE, "tag_spec.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        w.writerows(rows)
    print(f"wrote {out}: {len(rows)} rows")


if __name__ == "__main__":
    main()
