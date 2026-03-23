# DDR Outputs and Pickle Structure

This page describes three related data shapes:

1. Raw DDR payload returned by DDR helpers.
2. Flattened output used by default for TaskVine DDR serialization.
3. Final `histos/<outname>.pkl.gz` structure written by workflow.

## 1) Raw DDR payload (pre-flatten)

The raw payload is nested by processor key and dataset:

```text
{
  <processor_key>: {
    <dataset_name>: {
      <histogram_key_tuple>: <accumulator>,
      ...
      <optional sidecar key>: <sidecar payload>,
    },
    ...
  },
  ...
}
```

`processor_key` encodes channel/variable/application/systematic according to
`ddr_processor_key_delim`.

## 2) Flattened payload (default schema)

Default TaskVine DDR output schema is `flat`, with canonical key ordering:

```text
(sample, channel, variable, application, systematic)
```

Examples:

```text
("UL18_WWW_4F_NDSkim", "2los_CRZ_0j", "invmass", "isAR_2lOS", "nominal")
("UL18_WWW_4F_NDSkim", "2los_CRZ_0j", "invmass_sumw2", "isAR_2lOS", "nominal")
```

`*_sumw2` keys are expected partner accumulators for variance bookkeeping.

## 3) Optional tuple schema

When `ddr_output_schema: tuple`, the tuple-style compatibility ordering is used:

```text
(variable, channel, application, sample, systematic)
```

## 4) Final pickle (`.pkl.gz`) written by workflow

`run_analysis` writes a gzipped pickle containing the merged histogram map.

At a high level:

```text
{
  <histogram_key_tuple>: <accumulator object>,
  ...
  [optional sidecar key]: <sidecar payload>
}
```

Key shape depends on executor/schema path:

- TaskVine DDR default: flat tuple keys
- TaskVine DDR with tuple schema: tuple-compat keys
- futures/iterative: tuple-keyed processor outputs (legacy-compatible)

## Quick inspection snippet

```python
import gzip
import pickle

path = "histos/plotsTopEFT.pkl.gz"
with gzip.open(path, "rb") as handle:
    payload = pickle.load(handle)

print(type(payload), len(payload))
for key in list(payload.keys())[:20]:
    print(key)

sumw2_keys = [k for k in payload if isinstance(k, tuple) and str(k[2]).endswith("_sumw2")]
print("sumw2 entries:", len(sumw2_keys))
```

## Related references

- `docs/schemas.md`
- `docs/ddr_preprocess_proxy_policy.md`
- `docs/taskvine_ddr_knobs.md`
- `analysis/topeft_run2/workflow.py`
