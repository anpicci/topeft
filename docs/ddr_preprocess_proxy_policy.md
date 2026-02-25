# DDR preprocess and proxy policy

This page documents TaskVine DDR operational behavior for preprocess artifacts
and proxy handling.

## Proxy handling policy

When `ddr_x509_proxy` is configured:

1. Workflow validates source path exists/is readable.
2. Proxy is copied into TaskVine staging as exactly `proxy.pem`.
3. `proxy.pem` is shipped with DDR tasks via `extra_files`.
4. Worker environment is populated with:
   - `X509_USER_PROXY=proxy.pem`

This basename contract matches the TaskVine worker-side lookup pattern.

## Preprocess reuse/save policy

### Reuse mode

Set `ddr_preprocessed_data: <path>` to load a preprocessed mapping from disk and
skip `preprocess()`.

### Save mode

Set `ddr_save_preprocess: <path>` to persist preprocess output to the requested
path.

### Auto-save default

If reuse is not requested and `ddr_auto_save_preprocess: true` (default):

- artifact path defaults to
  `taskvine-results/ddr_preprocessed_data.json`
- can be overridden with `ddr_preprocess_artifact: <path>`

Reuse precedence:

- When reuse path is set, auto-save is not emitted unless an explicit save path
  is also set.

## Serialization format for preprocess artifacts

`topcoffea.modules.dynamic_data_reduction.run_ddr` uses:

1. JSON first (preferred, deterministic key sorting)
2. cloudpickle fallback when payload is not JSON-serializable

Loading follows the same order (JSON first, then cloudpickle fallback).

## Where this behavior is implemented

- topeft workflow orchestration:
  `analysis/topeft_run2/workflow.py`
- DDR helper load/save and preprocess control:
  `topcoffea/modules/dynamic_data_reduction.py`

## Related references

- [schemas.md](schemas.md)
- [run_analysis CLI reference](run_analysis_cli_reference.md)
