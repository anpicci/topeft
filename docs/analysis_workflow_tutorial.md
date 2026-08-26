# Analysis workflow tutorial

This tutorial follows the maintained path from sample configuration to the
artifacts handed to EFTFit/Combine. Commands are run from
`analysis/topeft_run2` unless stated otherwise. Activate an environment in
which the current `topeft` and matching `topcoffea` checkouts are installed
before starting. Site paths below are placeholders; choose fresh absolute
paths for real campaigns.

The detailed task recipes are in
[Analysis workflow how-to](analysis_workflow_how_to.md), the exact software
contracts are in [Analysis workflow reference](analysis_workflow_reference.md),
and the ownership model is in
[Analysis workflow architecture](analysis_workflow_architecture.md).

## 1. Choose a production route

There are three supported layers. They share `run_analysis.py` as the analysis
entrypoint, but they do not make the same decisions for you.

1. `run_cr.sh` is the maintained campaign orchestrator. For `run3_full` it
   freezes a five-block plan, sample/environment identity, output namespace,
   and resume state. It runs nonprompt production in a fresh process after each
   source job.
2. `fullR3_run.sh` selects NDSkim sample bundles, region mode, years, histogram
   families, and constructs one `run_analysis.py` command. It is useful for a
   bounded source job or a custom block.
3. `run_analysis.py` is the independently supported low-level CLI. It accepts a
   sample JSON or cfg input directly and leaves sample grouping, output naming,
   and downstream orchestration to the caller.

For a maintained full Run 3 campaign, first inspect the resolved plan:

```bash
./run_cr.sh \
  --production-profile run3_full \
  --output-dir /absolute/path/to/fresh_run3_campaign \
  --campaign-tag run3_campaign \
  --dry-run
```

Remove `--dry-run` only after reviewing the block plan and confirming the
output directory does not exist. A resume is allowed only against the exact
campaign state and environment frozen in that directory.

## 2. Understand sample selection

`fullR3_run.sh` is the current owner of default cfg selection. Run 2 uses the
aggregate maintained bundles:

- `mc_signal_samples_NDSkim.cfg`
- `mc_background_samples_NDSkim.cfg`
- `data_samples_NDSkim.cfg`
- `mc_background_samples_cr_NDSkim.cfg` in the relevant CR path

Run 3 resolves year-specific `NDSkim_${year}_...` cfg files. `--sample-json`
or `--cfg-override` replaces that default for one lower-level run. A file being
present in `input_samples/cfgs` does not make it a current production input;
the selection branches in `fullR3_run.sh` are authoritative.

## 3. Produce source and transformed PKLs

The processor writes `<outname>.pkl.gz` and its adjacent
`<outname>.pkl.gz.metadata.json` sidecar. The sidecar records source identity,
the histogram-family contract, Wilson coefficients, production sample
profile, sumw2 provenance, and related composition evidence.

`run3_full` passes `--do-np --np-postprocess=defer`. After the source process
exits, `run_cr.sh` invokes `run_data_driven.py` in a separate process and
requires `<outname>_np.pkl.gz` plus its transformed sidecar before completing
the block. Direct users can choose inline, deferred, or skipped nonprompt
post-processing, but must not treat a source PKL as equivalent to the final
nonprompt product.

Compatible fragments can be merged by the consumer loaders. They reject
inconsistent artifact identities, axes, Wilson-coefficient order, or sumw2
contracts. See [HistEFT API contract](histeft_api_contract.md) for the complete
sidecar and merge schema.

## 4. Validate distributions with plots

The reusable plotting wrapper is `run_plotter.sh`; the direct entrypoint is
`make_cr_and_sr_plots.py`. Both consume one coherent Run 2 or Run 3 artifact
family. Mixed Run 2 and Run 3 inputs are rejected. Plot metadata comes first
from `topeft/params/cr_sr_plots_metadata.yml`; when an observed channel is not
declared there, one coherent producer `ch_lst.json` preset may supply it.
Ambiguous producer presets fail closed.

Plotting is a validation step, not a card producer. Inspect control-region
yields, uncertainty bands, negative-weight reports, and the selected
processing or fitting binning before making cards.

## 5. Create individual cards and scaling preselection

Use final coherent `_np.pkl.gz` inputs for ordinary card production. The direct
interface accepts positional PKLs or `--pkl-list-file`, never both. For example:

```bash
python make_cards.py /path/to/final_np.pkl.gz \
  --out-dir /absolute/path/to/cards \
  --var-lst lj0pt ptz ptll ptz_wtau lt \
  --ch-lst '^2lss_.*' '^3l_.*' '^4l_.*' \
  --binning fitting \
  --year-coverage-policy error
```

`fitting` is the default card binning. The producer validates and merges the
input family, selects channels/variables/WCs, checks systematic pairs,
sanitizes disallowed negative nominal bins unless `--keep-negative-bins` is
set, and writes:

- individual `ttx_multileptons-*.txt` cards;
- matching `ttx_multileptons-*.root` templates;
- `selectedWCs.txt`;
- `scalings-preselect.json`.

The tracked matrix scripts are campaign-specific operator records, not the
supported specification of this step. Their embedded paths and provenance
must not be copied into a new campaign. The maintained direct interface above
is independently usable.

## 6. Finalize the selected card topology and scalings

For the full current analysis topology run:

```bash
python datacards_post_processing.py /absolute/path/to/cards -a
```

The input is the datacard directory. It must already contain the individual
cards/templates, `selectedWCs.txt`, and `scalings-preselect.json`.
`datacards_post_processing.py` obtains `ALL_CH_LST_SR` from
`topeft/channels/ch_lst.json`, derives physical card-channel names, sorts them,
and assigns `ch1`, `ch2`, ... in that order. It copies the selected cards,
templates, and `selectedWCs.txt` into the historically named
`ptz-lj0pt_withSys` subdirectory, filters every matching scaling record, keeps
its process/parameters/coefficient payload, changes only the channel label,
and writes the final `scalings.json`.

`-a` includes off-Z, tau, and forward contributions. The explicitly mapped
off-Z `high`/`low` categories use final `ptll`; this does not make `ptz` and
`ptll` aliases.

## 7. Hand off to EFTFit/Combine

Correction-lib ownership ends at the selected individual text/ROOT cards,
`selectedWCs.txt`, and final ordered `scalings.json`. EFTFit/Combine later
combines the individual cards, creates `combinedcard.txt`, and builds the
workspace. Therefore:

- `combinedcard.txt` is not an input to `datacards_post_processing.py`;
- this repository does not define a current copy-paste EFTFit command;
- final `chN` ordering is intentionally aligned with the later combined-card
  and workspace channel ordering;
- a missing scaling record means no external EFT morph for that
  channel/process, not a process-global normalization default.

Carry the complete selected output directory across the repository boundary;
do not transport `scalings.json` without the cards and `selectedWCs.txt` that
define its physical meaning.
