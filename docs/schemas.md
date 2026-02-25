# Output and key schemas

This page is the single source of truth for histogram key and DDR output
schemas.

## 1) Internal histogram tuple schema

Inside planning and processor filling, histogram keys are 5-tuples:

- `(var, channel, application, sample, systematic)`

This is the canonical internal tuple contract.

## 2) TaskVine DDR processor-key schema

TaskVine DDR processors are keyed by:

- `<channel><delim><var><delim><application><delim><systematic_label>`

Default delimiter is `-` (`ddr_processor_key_delim`).

Delimiter safety rule:

- If any component contains the delimiter, key construction fails fast.

## 3) DDR raw nested shape (before flattening)

Dynamic data reduction returns nested mappings:

- `{processor_key: {dataset_name: leaf_payload}}`

`leaf_payload` contains histogram tuple keys (and optionally sidecars when
produced/preserved).

## 4) TaskVine DDR flattened canonical schema (default)

By default, serialized TaskVine DDR output is flattened to:

- `(sample, channel, var, application, systematic_label)`

`systematic_label` normalization:

- tuples/lists are converted to colon-joined labels
- scalars are converted with `str(...)`

## 5) Optional DDR tuple-schema serialization

TaskVine DDR can serialize using tuple-style schema with:

- `ddr_output_schema: tuple`

Tuple output schema in this mode is:

- `(var, channel, application, sample, systematic_label)`

## 6) Strict flatten validation rules

Flattening enforces all of the following:

1. Processor key must parse into exactly 4 fields using configured delimiter.
2. Leaf histogram keys must be 5-tuples.
3. For each histogram tuple key, `(channel, var, application, systematic_label)`
   must exactly match parsed processor-key fields.
4. Mismatches fail fast with processor key and offending tuple diagnostics.

## 7) Flatten collision policy

Flattening is fail-fast for duplicate target keys.

- If two origins map to the same flattened key, processing raises with both
  origins (processor/dataset/histogram-key) in diagnostics.
- No implicit `iadd` merge is performed in default flattening path.

## 8) Sidecar behavior

Two independent controls:

- `produce_sidecars` (processor-side creation; default `false`)
- `ddr_preserve_sidecars` (flatten-time preservation; default `false`)

Defaults:

- sidecars are not produced and therefore not serialized.

If preserved:

- non-hist sidecars are stored under `ddr_sidecars_key` (default
  `__sidecars__`) in flattened DDR output.

## 9) What is written to pickle by executor path

- TaskVine DDR default: flattened canonical keys
  `(sample, channel, var, application, systematic_label)`
- TaskVine DDR with `ddr_output_schema: tuple`: tuple-style keys
  `(var, channel, application, sample, systematic_label)`
- Futures/iterative: internal tuple keys
  `(var, channel, application, sample, systematic)`

## 10) Related docs

- [How to run workflow](how_to_run_analysis_workflow.md)
- [DDR preprocess/proxy policy](ddr_preprocess_proxy_policy.md)
- [Analysis processor data flow](analysis_processor_data_flow.md)
