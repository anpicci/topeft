# Run 2 quickstart pipeline

This quickstart is the shortest path from sample JSON to a first output pickle.
It uses the options-first wrapper and mirrors current TaskVine DDR defaults.

## Prerequisites

1. Activate the shared `coffea2025` environment.
2. Install `topeft` and sibling `topcoffea` checkouts in editable mode.
3. If running TaskVine profiles, prepare the environment tarball:

```bash
python -m topcoffea.modules.remote_environment
```

## Step 1: run a tiny local smoke test

Use a futures debug profile in YAML and launch via wrapper:

```bash
cd analysis/topeft_run2
./full_run.sh --options configs/fullR2_run.yml:sr
```

For lightweight smoke tests, keep a dedicated YAML profile with:

- `executor: futures` (or `iterative`)
- small `nchunks`
- small `chunksize`
- `pretend: true` for plan-only validation

The wrapper accepts only `--options`; all tuning must be done in YAML.

## Step 2: run TaskVine DDR profile

Switch to a TaskVine production profile in YAML:

- `executor: taskvine`
- `chunksize: 500000`
- `ddr_output_schema: flat`

Then launch:

```bash
cd analysis/topeft_run2
./full_run.sh --options configs/fullR2_run.yml:cr
```

## Step 3: inspect outputs

Output schema depends on executor path:

- TaskVine DDR serialized output defaults to flat canonical tuples:
  `(sample, channel, var, application, systematic_label)`
- Futures/iterative outputs are tuple-keyed:
  `(var, channel, application, sample, systematic)`

See [schemas.md](schemas.md) for the canonical tuple-key contracts and
[ddr_outputs_and_pkl.md](ddr_outputs_and_pkl.md) for the TaskVine DDR sidecars,
flattened output schema, and final `.pkl.gz` layout.

## Step 4: plot

```bash
cd analysis/topeft_run2
python make_cr_and_sr_plots.py \
  -f histos/plotsTopEFT.pkl.gz \
  -o plots/quickstart \
  -n plots \
  -y 2017 \
  --skip-syst
```

## Metadata/scenario authority

Run-2 scenario resolution is controlled by:

- `analysis/metadata/run2_scenarios.yaml`
- `analysis/topeft_run2/metadata_authority.py`

For wrapper-driven runs, place `scenarios:` in YAML options.
