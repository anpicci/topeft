# HistEFT and pkl inspection tutorial

## 1. Purpose and scope

This note is an onboarding guide for the current TOP EFT histogram workflow:

```text
analysis processor -> HistEFT/SparseHist output -> pkl.gz file -> plotting or manual inspection
```

It is intentionally source-grounded. File and line references point to the
implementation that was inspected for this guide. The goal is to make a new
student autonomous enough to inspect pkl files and understand the current
contracts before planning a future `scikit-hist` EFT-aware replacement.

This guide does not change any physics behavior. It does not redesign HistEFT,
the processor, `run_cr.sh`, `fullR3_run.sh`, `run_analysis.py`, plotting code,
sample JSONs, or CFG files.

## 2. Big picture: processor -> HistEFT/coffea output -> pkl -> plotting/inspection

The current workflow has four layers:

1. `analysis/topeft_run2/run_cr.sh` is the student-facing source of truth for
   how this workspace is meant to launch the processor. It delegates to
   `analysis/topeft_run2/fullR3_run.sh`, which builds a `run_analysis.py`
   command.
2. `analysis/topeft_run2/run_analysis.py` reads JSON or CFG sample inputs,
   builds a sample dictionary and WC list, instantiates
   `AnalysisProcessor`, runs coffea, and writes a gzip-compressed pkl with
   `cloudpickle`.
3. `analysis/topeft_run2/analysis_processor.py` declares one histogram per
   requested variable. One-dimensional analysis variables are `HistEFT`
   objects. Two-dimensional variables are `SparseHist` objects.
4. `analysis/topeft_run2/make_cr_and_sr_plots.py` loads one or more pkl files,
   validates and merges histograms, groups process labels, integrates channels
   and systematics, evaluates HistEFT at SM or WC points, and produces plots.

Manual inspection only needs the pkl file and the histogram object API. The
helper added with this guide,
`analysis/topeft_run2/inspect_histeft_pkl.py`, gives a safe first look without
depending on the plotting script.

## 3. What HistEFT is

`HistEFT` is a histogram class for storing EFT polynomial coefficients instead
of only one nominal bin content per bin.

In a normal weighted histogram, each event contributes one weight to one dense
bin. In `HistEFT`, each event contributes one value for every quadratic EFT
coefficient term. With `n` Wilson coefficients, the number of stored quadratic
terms is the lower-triangular count for `sm` plus all WCs. For example, with
one WC the terms are `sm*sm`, `ctG*sm`, and `ctG*ctG`.

Important source behavior:

- `topcoffea/topcoffea/modules/histEFT.py:74-126`: `HistEFT` requires named
  axes, exactly one user dense axis, that dense axis last, categorical axes with
  growth, and `Double` storage. It creates or accepts an internal
  `quadratic_term` axis.
- `topcoffea/topcoffea/modules/histEFT.py:140-163`: maps WC pairs such as
  `("sm", "ctG")` or `("ctG", "ctG")` to a quadratic-term index.
- `topcoffea/topcoffea/modules/histEFT.py:197-249`: `fill` repeats dense
  values and event weights across all quadratic terms, then fills the internal
  `quadratic_term` axis with EFT coefficients multiplied by the event weight.
- `topcoffea/topcoffea/modules/histEFT.py:271-305`: `eval({})` evaluates the
  stored polynomial at the SM point, while `eval({"ctG": 1.0})` evaluates at a
  specific WC point. `as_hist(values)` materializes a regular histogram after
  evaluation.

The practical consequence: for a `HistEFT` object, raw stored values are not yet
the final physics yield at an arbitrary EFT point. Plotting and manual
inspection must either evaluate it at a WC point or explicitly inspect the raw
coefficient axis.

## 4. Where HistEFT lives in the code

The implementation is in the sibling `topcoffea` repository:

```text
/users/apiccine/work/correction-lib/topcoffea/topcoffea/modules/histEFT.py
/users/apiccine/work/correction-lib/topcoffea/topcoffea/modules/sparseHist.py
```

`HistEFT` inherits from `SparseHist`. `SparseHist` is the sparse categorical
storage layer: it tracks categorical axes in a small bookkeeping histogram and
stores one dense `hist.Hist` block per populated categorical key. The relevant
source is:

- `topcoffea/topcoffea/modules/sparseHist.py:15-39`: class setup, categorical
  axes, dense axes, and `_dense_hists`.
- `topcoffea/topcoffea/modules/sparseHist.py:124-139`: fill bookkeeping and
  per-key dense histogram creation.
- `topcoffea/topcoffea/modules/sparseHist.py:299-325`: slicing/integration
  return either a dense histogram, a new sparse histogram, or a scalar.
- `topcoffea/topcoffea/modules/sparseHist.py:349-376`: `values`, `view`, and
  `integrate`.
- `topcoffea/topcoffea/modules/sparseHist.py:378-406`: grouping categorical
  bins.
- `topcoffea/topcoffea/modules/sparseHist.py:445-529`: arithmetic and pickle
  reconstruction.

EFT coefficient helper logic is split across:

- `topcoffea/topcoffea/modules/quad_fit_tools.py:203-240`: extracts
  `EFTfitCoefficients` from events and defines the quadratic coefficient order.
- `topcoffea/topcoffea/modules/eft_helper.py:208-266`: remaps coefficient
  arrays when a histogram WC list differs from the sample WC list.

## 5. HistEFT data model

### Axes

The processor constructs a `HistEFT` with four sparse categorical axes and one
analysis dense axis:

```text
process, channel, systematic, appl, <analysis variable>
```

Source:

- `analysis/topeft_run2/analysis_processor.py:212-236`: declares the
  categorical axes `process`, `channel`, `systematic`, and `appl`, then builds
  histogram-variable names from `topeft/modules/axes.py`.
- `analysis/topeft_run2/analysis_processor.py:245-292`: creates one
  `HistEFT` per selected one-dimensional variable and a matching
  `<name>_sumw2` histogram when sumw2 is enabled.
- `topeft/modules/axes.py:1-32`: examples of one-dimensional variable
  definitions such as `invmass`, `ptz`, and `njets`.
- `topeft/modules/axes.py:230-260`: two-dimensional variable definitions use a
  separate `info_2d` dictionary.

`HistEFT` also carries an internal dense `quadratic_term` axis. That axis is
created in `histEFT.py:105-126` and is included in the dense storage layer, but
the user-facing analysis dense axis is still the physics variable such as
`njets` or `ptz`.

### Dense vs sparse axes

`SparseHist` treats categorical axes as sparse and dense axes as regular
histogram axes. In this codebase:

- sparse axes: process, channel, systematic, appl;
- dense physics axis: one requested analysis variable;
- dense internal EFT axis: `quadratic_term`, managed by `HistEFT`.

Only populated sparse category combinations get dense histogram blocks. That is
why manual pkl inspection should not assume every process/channel/systematic
combination exists.

### Sample and process labels

The processor uses sample JSON metadata to assign the process axis label:

- `analysis/topeft_run2/analysis_processor.py:450-466`: reads `dataset`,
  `histAxisName`, `year`, xsec, sum of weights, and whether the sample has WCs.
- `analysis/topeft_run2/analysis_processor.py:1900-1911`: fills
  `process=histAxisName`.

The plotting script later groups these raw process labels into physics groups
using metadata patterns:

- `topeft/params/cr_sr_plots_metadata.yml:432-503`: SR group map, including
  patterns for `ttH`, `ttlnu`, `ttll`, `tllq`, `tHq`, and `tttt`.
- `analysis/topeft_run2/make_cr_and_sr_plots.py:5810-5832`: groups process
  bins and validates labels.

### Category and channel labels

The processor stores selected analysis categories on the `channel` axis. It
also stores application-region labels on the `appl` axis, for example signal
region versus application region.

Source:

- `analysis/topeft_run2/analysis_processor.py:60-99`: resolves category-group
  names into SR or CR category dictionaries.
- `analysis/topeft_run2/analysis_processor.py:1136-1170`: chooses SR and/or CR
  category lists depending on run options.
- `analysis/topeft_run2/analysis_processor.py:1230-1412`: builds packed
  selections, preselection, SR/CR masks, lepton flavor masks, njet masks, and
  application-region masks.
- `analysis/topeft_run2/analysis_processor.py:1638-1703`: builds the concrete
  category dictionary used in the fill loop.
- `analysis/topeft_run2/analysis_processor.py:1771-1817`: loops over category,
  njet label, application region, lepton channel, and lepton flavor.
- `topeft/params/cr_sr_plots_metadata.yml:20-24`: plotting metadata records
  that CR pkls include lepton flavor in channel labels, while SR pkls do not.
- `topeft/params/cr_sr_plots_metadata.yml:116-352`: SR channel aliases and
  leaves.

### Systematics

The `systematic` axis stores nominal and variation labels. The processor loops
over object variations and weight variations:

- `analysis/topeft_run2/analysis_processor.py:642-669`: defines object and
  weight systematic lists.
- `analysis/topeft_run2/analysis_processor.py:716-719`: builds the object
  systematic loop, including nominal.
- `analysis/topeft_run2/analysis_processor.py:1744-1760`: selects nominal,
  object-shifted, or weight-shifted event weights.
- `analysis/topeft_run2/analysis_processor.py:1900-1911`: fills
  `systematic=wgt_fluct`.

Manual comparisons should first list the actual labels in the pkl and only then
compare pairs such as `JESUp` and `JESDown`. Labels are not guaranteed to be
present in tiny runs or in runs without `--do-systs`.

### EFT coefficient storage

For samples with EFT metadata, the processor reads event-level coefficients:

- `analysis/topeft_run2/analysis_processor.py:620-631`: reads
  `events["EFTfitCoefficients"]`, remaps coefficients to the requested WC
  list, and prepares optional squared-weight coefficients.
- `analysis/topeft_run2/analysis_processor.py:1900-1911`: passes
  `eft_coeff=eft_coeffs_cut` into `HistEFT.fill`.
- `topcoffea/topcoffea/modules/quad_fit_tools.py:217-240`: defines the
  coefficient order with `sm` prepended.
- `topcoffea/topcoffea/modules/eft_helper.py:208-266`: remaps coefficient
  arrays when current and target WC lists differ.

If a sample has no EFT coefficients, `HistEFT.fill` defaults to SM-only
coefficients, according to `histEFT.py:214-224`.

### Nominal vs variation content

Nominal and systematic variations are not separate top-level pkl files by
default. They are labels on the `systematic` axis. Sumw2 content, when enabled,
is stored as a separate top-level histogram key with a `_sumw2` suffix. The
processor creates the companion histograms in
`analysis_processor.py:245-292` and fills them in
`analysis_processor.py:1913-1924`.

### Values and variances

For `HistEFT`, call `eval(wc_values)` to get evaluated values. The plotting
script uses this pattern for HistEFT:

- `analysis/topeft_run2/make_cr_and_sr_plots.py:6231-6277`: helper functions
  call `hist_slice.eval({})` for `HistEFT` and use `.values(...)` for ordinary
  histograms.

For sumw2, current analysis outputs use separate `_sumw2` HistEFT-like objects
rather than relying only on regular weighted-hist variance storage. Plotting and
datacard utilities therefore often require matching base and `_sumw2` keys.

### Serialization and pickle behavior

Output pkls are gzip-compressed cloudpickle files:

- `topcoffea/topcoffea/modules/utils.py:399-405`: `dump_to_pkl` writes with
  `gzip.open(..., "wb")` and `cloudpickle.dump`.
- `analysis/topeft_run2/run_analysis.py:1715-1765`: writes the final histogram
  dictionary to `<outpath>/<outname>.pkl.gz`.

`HistEFT.__reduce__` reconstructs categorical axes, the user dense axis,
initialization arguments, WC names, and `_dense_hists`:

- `topcoffea/topcoffea/modules/histEFT.py:307-319`.

The plotting script also monkey-patches `SparseHist._read_from_reduce` for
faster loading:

- `analysis/topeft_run2/make_cr_and_sr_plots.py:55-110`.

## 6. How the analysis processor fills histograms

### Histogram declaration

`AnalysisProcessor.__init__` resolves the requested histogram list, builds
axes, and creates histograms:

- `analysis/topeft_run2/analysis_processor.py:114-150`: normalizes requested
  histogram names.
- `analysis/topeft_run2/analysis_processor.py:212-236`: creates sparse axes and
  finds available 1D and 2D variables.
- `analysis/topeft_run2/analysis_processor.py:245-292`: creates one
  `HistEFT` and one optional `_sumw2` HistEFT per 1D variable.
- `analysis/topeft_run2/analysis_processor.py:293-343`: creates `SparseHist`
  objects for 2D variables, without EFT coefficient storage.

### Event selection

Selections are built with masks for lepton multiplicity, trigger, Z windows,
b-tag regions, category definitions, application regions, and optional lepton
flavor splitting. The main selection-building block is:

- `analysis/topeft_run2/analysis_processor.py:1014-1020`: lepton-multiplicity
  selections.
- `analysis/topeft_run2/analysis_processor.py:1230-1412`: preselection,
  category, njet, lepton flavor, and `appl` selections.
- `analysis/topeft_run2/analysis_processor.py:1718-1817`: per-histogram,
  per-systematic, per-category fill loop.

### Weights

The base MC event weight is normalized by luminosity, cross section, generator
weight, and sum of weights:

- `analysis/topeft_run2/analysis_processor.py:681-692`.

Additional nominal and systematic weights are added through correction helpers:

- `analysis/topeft_run2/analysis_processor.py:694-711`: prefiring, parton
  shower, scale, and pileup weight setup.
- `analysis/topeft_run2/analysis_processor.py:1135-1226`: category-specific
  lepton SF, fake-factor, flip-rate, and data-driven behavior.
- `analysis/topeft_run2/analysis_processor.py:1744-1760`: chooses which
  weight variation is used for the current systematic label.

### Nominal fills

The nominal fill is just one pass through the same systematic loop with
`wgt_fluct == "nominal"`. The fill payload includes the dense variable,
category labels, application region, process label, systematic label, event
weight, and EFT coefficients when the histogram requires them:

- `analysis/topeft_run2/analysis_processor.py:1900-1911`.

### Systematic fills

Object systematic variations change the event collections before the selection
and dense variable are computed. Weight systematic variations keep the same
object collection but use a shifted weight. The relevant source ranges are:

- `analysis/topeft_run2/analysis_processor.py:766-961`: object variation
  handling for muons, taus, jets, and MET.
- `analysis/topeft_run2/analysis_processor.py:1718-1760`: variable and weight
  choice for each systematic loop.

### EFT fills

`eft_coeffs_cut` is selected with the same event mask as the event weights and
dense variable:

- `analysis/topeft_run2/analysis_processor.py:1771-1817`: category mask and
  `eft_coeffs_cut`.
- `analysis/topeft_run2/analysis_processor.py:1900-1911`: `eft_coeff` is
  included only for histograms marked as requiring EFT.

### CR vs SR behavior

`run_analysis.py` controls CR and SR behavior through `--skip-sr`, `--skip-cr`,
category dictionaries, and histogram-list aliases:

- `analysis/topeft_run2/run_analysis.py:1058-1067`: resolves requested
  category groups.
- `analysis/topeft_run2/run_analysis.py:1081-1175`: expands histogram-list
  aliases such as `ana` and `cr`.
- `analysis/topeft_run2/analysis_processor.py:359-362`: processor flags for
  systematics, lepton flavor splitting, skip SR, and skip CR.
- `analysis/topeft_run2/analysis_processor.py:1136-1170`: selects SR and/or
  CR category dictionaries.

### Run 2 vs Run 3 behavior

The processor marks an event sample as Run 2 or Run 3 from the sample JSON
`year` string:

- `analysis/topeft_run2/analysis_processor.py:450-466`: `is_run2` is true for
  years starting with `201`, and `is_run3` for years starting with `202`.

The runner expands year aliases:

- `analysis/topeft_run2/fullR3_run.sh:143-156`: `run3` expands to
  `2022 2022EE 2023 2023BPix`.
- `analysis/topeft_run2/fullR3_run.sh:190-270`: chooses CFG files by year and
  CR/SR mode.

## 7. `run_cr.sh` as the source-of-truth runner

The source-of-truth student runner is:

```text
analysis/topeft_run2/run_cr.sh
```

Important local behavior:

- `analysis/topeft_run2/run_cr.sh:10-33`: workspace-specific output path,
  chunk size, pkl tag, default histogram variables, years, and category sets.
- `analysis/topeft_run2/run_cr.sh:72-119`: active `run_cr_block` delegates to
  `./fullR3_run.sh` with `--cr`, `--hist-vars`, `--do-systs`, output path,
  category groups, tau analysis, and split lepton flavor.
- `analysis/topeft_run2/run_cr.sh:125-130`: active main loop runs CR jobs over
  the configured years and category sets.
- `analysis/topeft_run2/run_cr.sh:177-220`: commented SR scaffold shows the
  same script family used for SR runs, with `--sr`, `--do-systs`, `--do-np`,
  category groups, and `--all-analysis`.

Do not run this script blindly for a tutorial. As inspected, the active body is
a CR production-style loop over multiple years and category sets. For an SR
tutorial, treat `run_cr.sh` as the source of the command shape, then use
`fullR3_run.sh --dry-run` to source-validate the downstream command before any
real processing.

`fullR3_run.sh` provides the safe dry-run switch:

- `analysis/topeft_run2/fullR3_run.sh:4-21`: usage includes `--dry-run`,
  `--cr`, `--sr`, and `--hist-vars`.
- `analysis/topeft_run2/fullR3_run.sh:48-116`: parses command-line options.
- `analysis/topeft_run2/fullR3_run.sh:129-135`: requires exactly one of CR or
  SR mode.
- `analysis/topeft_run2/fullR3_run.sh:176-185`: forms the output name as
  `<YEAR_LABEL>CRs_<TAG>` or `<YEAR_LABEL>SRs_<TAG>`.
- `analysis/topeft_run2/fullR3_run.sh:282-289`: forwards `--hist-vars` as
  `--hist-list`; CR defaults to `cr`, SR defaults to `ana`.
- `analysis/topeft_run2/fullR3_run.sh:325-337`: prints the `run_analysis.py`
  command and exits before running it when `--dry-run` is present.

## 8. Quick-run tutorial

### Choose a Run 3 EFT signal sample

For the SR tutorial, use:

```text
input_samples/sample_jsons/signal_samples/ND_SRskim2023/ttH_NDSkim_2023.json
```

Why this sample:

- It is directly listed in the 2023 SR signal CFG used by `fullR3_run.sh`:
  `input_samples/cfgs/NDSkim_2023_mc_signal_samples_sr.cfg:7-12`.
- It has `year: "2023"`, `histAxisName: "ttH_private2023"`, and a non-empty
  `WCnames` list:
  `input_samples/sample_jsons/signal_samples/ND_SRskim2023/ttH_NDSkim_2023.json:1-40`.
- It is an SR skim signal sample, matching the SR-oriented tutorial target.

### Dry-run the source-derived SR command

This is the safe command shape derived from the commented SR block in
`run_cr.sh` and the option parser in `fullR3_run.sh`. It does not launch the
processor because of `--dry-run`.

```bash
cd /users/apiccine/work/correction-lib/topeft/analysis/topeft_run2

./fullR3_run.sh \
  -y 2023 \
  -t CL007AA_SR_tutorial_ttH_2023_njets \
  -s 1000 \
  --sr \
  --hist-vars njets \
  --dry-run \
  --category-groups 2l \
  --all-analysis \
  -p /tmp/cl007aa_histeft_demo \
  -x futures \
  --nworkers 1 \
  --nchunks 1 \
  --pretend
```

Validated dry-run output in this workspace:

```text
OUT_NAME: 2023SRs_CL007AA_SR_tutorial_ttH_2023_njets
Resolved years: 2023
Resolved CFGS: ../../input_samples/cfgs/NDSkim_2023_background_samples.cfg,../../input_samples/cfgs/NDSkim_2023_data_samples.cfg,../../input_samples/cfgs/NDSkim_2023_mc_signal_samples_sr.cfg
Resolved region: SR
Resolved histogram list: njets

Running the following command:
python run_analysis.py ../../input_samples/cfgs/NDSkim_2023_background_samples.cfg,../../input_samples/cfgs/NDSkim_2023_data_samples.cfg,../../input_samples/cfgs/NDSkim_2023_mc_signal_samples_sr.cfg --years 2023 -p /groups/klannon/apiccine/ --hist-list njets --skip-cr --do-systs --do-np -o 2023SRs_CL007AA_SR_tutorial_ttH_2023_njets -s 1000 --category-groups 2l --all-analysis -p /tmp/cl007aa_histeft_demo -x futures --nworkers 1 --nchunks 1 --pretend
```

Option notes:

- `-y 2023`: one Run 3 year, not the full `run3` alias.
- `--sr`: selects SR mode and makes `fullR3_run.sh` choose SR CFG files.
- `--hist-vars njets`: asks for one small histogram variable.
- `--category-groups 2l`: limits category construction to the 2l SR group.
- `--dry-run`: prints the downstream command and exits before running Python.
- `-x futures --nworkers 1 --nchunks 1 --pretend`: bounded internal
  `run_analysis.py` options, included in the printed command. `--pretend`
  would stop `run_analysis.py` after input discovery if the dry-run guard were
  removed.
- `-p /tmp/cl007aa_histeft_demo`: a tutorial output path. In the dry-run output
  this appears after the default group output path, so argparse should use the
  later value if the command is actually run.

Expected pkl path for an authorized real run without `--dry-run` and without
`--pretend`:

```text
/tmp/cl007aa_histeft_demo/2023SRs_CL007AA_SR_tutorial_ttH_2023_njets.pkl.gz
```

This path follows `fullR3_run.sh:176-185` for the output name and
`run_analysis.py:1017-1019` plus `run_analysis.py:1715-1765` for the pkl write.

### Important limitation: one-sample-only running

The source-of-truth runner does not currently expose a public option to run
only one JSON from the SR CFG. The dry-run command above uses the 2023 SR CFG
set, and the chosen `ttH_NDSkim_2023.json` is one of the EFT signal JSONs in
that CFG. A truly one-sample run would require either a temporary one-entry CFG
or an internal direct `run_analysis.py` call. That direct path is not the
primary student workflow; treat it as an advanced path derived from the
dry-run output and use it only after authorization.

### If you temporarily edit `run_cr.sh` for a tutorial

Do not commit such edits unless the analysis conveners request them. The active
file currently runs CR blocks. For an SR tutorial edit, make a temporary local
change modeled on the commented SR scaffold around
`analysis/topeft_run2/run_cr.sh:177-220`, for example:

```diff
- years=(2022 2022EE 2023 2023BPix 2018)
- pkl_base_tag="CR_muonres"
- vars=(invmass tau0Tpt l0ptcorr)
+ years=(2023)
+ pkl_base_tag="CL007AA_SR_tutorial_ttH"
+ vars=(njets)
```

Then use the SR scaffold, add `--dry-run` first, and keep the output path in a
scratch location. The point is to prove command construction before launching
any real processing.

## 9. How `make_cr_and_sr_plots.py` consumes pkl files

The plotting script accepts one or more pkl files and merges them before
plotting:

- `analysis/topeft_run2/make_cr_and_sr_plots.py:7528-7676`: CLI arguments
  include repeated `-f/--pkl-file-path`, pkl list files, output path/name,
  years, region override, variables, workers, merge options, cache options, and
  systematic switches.
- `analysis/topeft_run2/make_cr_and_sr_plots.py:7679-7692`: resolves pkl paths.
- `analysis/topeft_run2/make_cr_and_sr_plots.py:7727-7854`: detects region,
  loads and merges histograms with `load_and_merge_histogram_pkls`, writes an
  optional cached merged pkl, and dispatches plotting.
- `topeft/modules/datacard_tools.py:175-302`: opens each pkl, requires a
  dictionary with string keys, checks base and `_sumw2` companions when
  requested, validates histogram compatibility, and merges matching keys.

Expected pkl structure:

- top-level object: dictionary;
- top-level keys: histogram variable names such as `njets`, `ptz`, `invmass`;
- optional companion keys: `<hist>_sumw2`;
- values: `HistEFT` for 1D variables, `SparseHist` for 2D variables.

Histogram selection and process grouping:

- `analysis/topeft_run2/make_cr_and_sr_plots.py:2365-2479`: prepares variable
  payloads, finds available channels, handles sumw2 histograms, and filters
  process labels.
- `analysis/topeft_run2/make_cr_and_sr_plots.py:732-808`: resolves channel and
  process axis labels.
- `analysis/topeft_run2/make_cr_and_sr_plots.py:5810-5832`: groups process
  bins from metadata patterns.

Category/channel handling:

- `analysis/topeft_run2/make_cr_and_sr_plots.py:1738-1767`: integrates
  application region and category labels.
- `topeft/modules/yield_tools.py:475-513`: integrates categories and `appl`
  labels for yield extraction.

Systematics:

- `analysis/topeft_run2/make_cr_and_sr_plots.py:6140-6214`: discovers
  systematic labels, completes Up/Down pairs, integrates nominal and variation
  histograms, and prepares arrays.

Yields and HistEFT evaluation:

- `analysis/topeft_run2/make_cr_and_sr_plots.py:6231-6277`: evaluates HistEFT
  with `eval({})` for SM values and uses regular `.values(...)` for other
  histogram types.
- `topeft/modules/yield_tools.py:548-567`: yield code integrates categories,
  evaluates HistEFT at a requested WC point, and combines value and variance
  arrays.

Manual inspectors must reproduce these assumptions: dictionary pkl, string
keys, base and `_sumw2` pairing, categorical axes named `process`, `channel`,
`systematic`, and `appl`, and explicit HistEFT evaluation before using values
as physics yields.

## 10. Manual pkl inspection

### Use the helper script

The helper is read-only:

```bash
WRAP=/users/apiccine/work/correction-lib/codex-run.sh
PYTHON_ENV=/users/apiccine/work/miniconda3/envs/clib-env/bin/python

$WRAP /bin/bash --noprofile --norc -c 'cd /users/apiccine/work/correction-lib/topeft && "$PYTHON_ENV" analysis/topeft_run2/inspect_histeft_pkl.py --help'
```

Inspect a pkl:

```bash
$WRAP /bin/bash --noprofile --norc -c 'cd /users/apiccine/work/correction-lib/topeft && "$PYTHON_ENV" analysis/topeft_run2/inspect_histeft_pkl.py /path/to/output.pkl.gz --max-labels 10'
```

Inspect one histogram and ask for a simple nominal total when discoverable:

```bash
$WRAP /bin/bash --noprofile --norc -c 'cd /users/apiccine/work/correction-lib/topeft && "$PYTHON_ENV" analysis/topeft_run2/inspect_histeft_pkl.py /path/to/output.pkl.gz --hist njets --max-labels 10 --yield-summary'
```

The helper prints:

- top-level object type;
- top-level keys;
- histogram-like object types;
- axes and labels;
- `process`, `channel`, `systematic`, and `appl` labels when discoverable;
- WC names when the object exposes them;
- optional simple nominal yield and variance sums.

### Minimal manual Python snippets

Use the same analysis environment when opening analysis pkls. A pkl may require
`topcoffea` classes to be importable.

List top-level keys:

```bash
WRAP=/users/apiccine/work/correction-lib/codex-run.sh
PYTHON_ENV=/users/apiccine/work/miniconda3/envs/clib-env/bin/python

$WRAP /bin/bash --noprofile --norc -c 'cd /users/apiccine/work/correction-lib/topeft && "$PYTHON_ENV" -c "import gzip,pickle; p=\"/path/to/output.pkl.gz\"; f=gzip.open(p,\"rb\") if p.endswith(\".gz\") else open(p,\"rb\"); obj=pickle.load(f); print(type(obj)); print(list(obj)[:20])"'
```

List axes for one histogram:

```bash
$WRAP /bin/bash --noprofile --norc -c 'cd /users/apiccine/work/correction-lib/topeft && "$PYTHON_ENV" -c "import gzip,pickle; p=\"/path/to/output.pkl.gz\"; obj=pickle.load(gzip.open(p,\"rb\")); h=obj[\"njets\"]; print(type(h)); print([ax.name for ax in h.axes])"'
```

List labels on common categorical axes:

```bash
$WRAP /bin/bash --noprofile --norc -c 'cd /users/apiccine/work/correction-lib/topeft && "$PYTHON_ENV" -c "import gzip,pickle; p=\"/path/to/output.pkl.gz\"; h=pickle.load(gzip.open(p,\"rb\"))[\"njets\"]; print(list(h.axes[\"process\"])[:20]); print(list(h.axes[\"channel\"])[:20]); print(list(h.axes[\"systematic\"])[:20])"'
```

Evaluate a HistEFT at the SM point and sum all returned blocks:

```bash
$WRAP /bin/bash --noprofile --norc -c 'cd /users/apiccine/work/correction-lib/topeft && "$PYTHON_ENV" -c "import gzip,pickle,numpy as np; p=\"/path/to/output.pkl.gz\"; h=pickle.load(gzip.open(p,\"rb\"))[\"njets\"]; vals=h.integrate(\"systematic\",\"nominal\").eval({}); print(sum(float(np.nansum(v)) for v in vals.values()))"'
```

Compare nominal to one systematic label:

```bash
$WRAP /bin/bash --noprofile --norc -c 'cd /users/apiccine/work/correction-lib/topeft && "$PYTHON_ENV" -c "import gzip,pickle,numpy as np; p=\"/path/to/output.pkl.gz\"; h=pickle.load(gzip.open(p,\"rb\"))[\"njets\"]; nom=h.integrate(\"systematic\",\"nominal\").eval({}); up=h.integrate(\"systematic\",\"JESUp\").eval({}); print(sum(float(np.nansum(up[k]-nom.get(k,0))) for k in up))"'
```

The last snippet assumes `JESUp` exists. Always list systematic labels first.

### Make a small yield table

For a quick manual table, select one histogram, integrate one systematic label,
then loop over process labels:

```bash
$WRAP /bin/bash --noprofile --norc -c 'cd /users/apiccine/work/correction-lib/topeft && "$PYTHON_ENV" -c "import gzip,pickle,numpy as np; p=\"/path/to/output.pkl.gz\"; h=pickle.load(gzip.open(p,\"rb\"))[\"njets\"].integrate(\"systematic\",\"nominal\"); procs=list(h.axes[\"process\"]); print(\"process yield\"); [print(proc, sum(float(np.nansum(v)) for v in h.integrate(\"process\",proc).eval({}).values())) for proc in procs[:20]]"'
```

This is deliberately simple. It does not group processes, handle overflow
policy, or combine sumw2 uncertainties the same way the plotter does. Use it as
a first sanity check, not as a publication number.

### Check EFT/WC content

For a `HistEFT`, inspect WC names:

```bash
$WRAP /bin/bash --noprofile --norc -c 'cd /users/apiccine/work/correction-lib/topeft && "$PYTHON_ENV" -c "import gzip,pickle; p=\"/path/to/output.pkl.gz\"; h=pickle.load(gzip.open(p,\"rb\"))[\"njets\"]; print(getattr(h,\"wc_names\", getattr(h,\"_wc_names\", None)))"'
```

Evaluate a non-SM point if the WC exists:

```bash
$WRAP /bin/bash --noprofile --norc -c 'cd /users/apiccine/work/correction-lib/topeft && "$PYTHON_ENV" -c "import gzip,pickle,numpy as np; p=\"/path/to/output.pkl.gz\"; h=pickle.load(gzip.open(p,\"rb\"))[\"njets\"].integrate(\"systematic\",\"nominal\"); vals=h.eval({\"ctG\": 1.0}); print(sum(float(np.nansum(v)) for v in vals.values()))"'
```

If this raises a `LookupError`, the histogram WC list does not include that WC.

## 11. Debugging checklist

Missing pkl:

- Check whether the command was a dry-run or used `--pretend`; those do not
  write the final pkl.
- Check the final `-p` output path and `-o` output name in the printed
  `run_analysis.py` command.
- Check `run_analysis.py:1017-1019` and `run_analysis.py:1715-1765` for output
  path construction and writing.

Empty histograms:

- Verify the category group exists in the active `ch_lst.json` block.
- Check whether `--skip-sr` or `--skip-cr` removed the target region.
- List `channel`, `process`, and `systematic` labels with the helper.
- Use a broad category first, then narrow.

Missing category:

- Confirm the category group passed through `--category-groups`.
- Check `analysis_processor.py:60-99` for group resolution and
  `analysis_processor.py:1638-1703` for concrete category labels.
- For plotting, check `topeft/params/cr_sr_plots_metadata.yml:20-24` because
  CR and SR channel-label expectations differ.

Missing process/sample:

- Confirm the sample JSON is present in the CFG selected by `fullR3_run.sh`.
- Check the sample JSON `histAxisName`; this is the raw process-axis label.
- Check plot grouping patterns in `topeft/params/cr_sr_plots_metadata.yml`.

Missing systematic:

- Confirm the run used `--do-systs`.
- Tiny or pretend runs may not fill all requested variations.
- List actual `systematic` labels before comparing Up/Down pairs.

Missing EFT coefficients:

- Check the sample JSON `WCnames` list.
- Check whether event files have `EFTfitCoefficients`.
- Check `analysis_processor.py:620-631` for the coefficient read/remap path.
- If `HistEFT.eval({"ctG": 1.0})` fails, list the histogram's WC names.

Mismatched histogram variable names:

- `fullR3_run.sh --hist-vars` forwards to `run_analysis.py --hist-list`.
- Valid 1D names are in `topeft/modules/axes.py:1-228`.
- Valid 2D names are in `topeft/modules/axes.py:230-260` and later entries.

CR/SR mismatch:

- `--cr` makes `fullR3_run.sh` add `--skip-sr`.
- `--sr` makes `fullR3_run.sh` add `--skip-cr`.
- The active `run_cr.sh` body is CR-oriented in this workspace.

Wrong sample JSON/CFG:

- For 2023 SR, `fullR3_run.sh` uses:
  `NDSkim_2023_background_samples.cfg`,
  `NDSkim_2023_data_samples.cfg`, and
  `NDSkim_2023_mc_signal_samples_sr.cfg`.
- The chosen tutorial sample is listed in
  `input_samples/cfgs/NDSkim_2023_mc_signal_samples_sr.cfg:9`.

Pkl too large to inspect naively:

- Use the helper with `--hist` and small `--max-labels`.
- Avoid printing full `.values()` arrays.
- Start with top-level keys and axes.
- For many pkls, use the plotter merge-only path or a small custom inspector
  before loading every histogram into plotting.

## 12. Mapping to a future scikit-hist EFT-aware replacement

A future `scikit-hist` EFT-aware histogram class must reproduce current
behavior before it can replace `HistEFT` safely.

Core histogram behavior:

- accept named categorical axes and dense axes;
- preserve sparse categorical behavior or provide an equivalent memory-safe
  representation;
- support fill calls with scalar categorical labels, dense arrays, event
  weights, and optional EFT coefficient arrays;
- support addition and in-place addition for merging pkl outputs;
- support pruning, removal, grouping, slicing, projection, and integration
  patterns used by the processor and plotter.

Axes and metadata behavior:

- preserve axis names: `process`, `channel`, `systematic`, `appl`, dense
  variable name, and EFT coefficient dimension;
- preserve process labels from sample JSON `histAxisName`;
- preserve channel labels exactly as produced by the processor;
- preserve systematic labels exactly as filled;
- keep WC names and their order available after pickle load;
- preserve enough metadata for plotting group maps and yield tools.

Values and variances behavior:

- expose SM and WC-evaluated values with clear flow-bin policy;
- preserve or replace the current `_sumw2` companion convention;
- make variance behavior explicit, because current plotting often treats
  `<hist>_sumw2` as the variance source rather than using only weighted storage;
- support efficient summed yields over process/channel/systematic selections.

EFT coefficient storage and evaluation:

- store the quadratic coefficient order currently produced by
  `quad_fit_tools.py:217-240`;
- reproduce `HistEFT.quadratic_term_index` behavior from
  `histEFT.py:140-163`;
- reproduce `fill(eft_coeff=...)` semantics from `histEFT.py:197-249`,
  including SM-only default coefficients for non-EFT samples;
- reproduce `eval({})`, `eval({"wc": value})`, and unknown-WC error behavior;
- support coefficient remapping or define a stricter common WC-list contract.

Systematic variation handling:

- allow `systematic` to remain a categorical axis;
- support nominal and Up/Down comparisons without forcing all variations to be
  dense axes;
- preserve missing-variation behavior for small or partial runs.

Processor API assumptions:

- constructor can be called where `analysis_processor.py:245-292` currently
  calls `HistEFT(...)`;
- `fill` accepts `process=`, `channel=`, `systematic=`, `appl=`, dense variable
  keyword, `weight=`, and `eft_coeff=`;
- histograms are pickleable and mergeable after coffea execution;
- 2D non-EFT histograms can remain separate if the first replacement only
  targets 1D EFT-aware histograms.

Plotting API assumptions:

- pkl top-level dictionary keys remain variable names plus optional `_sumw2`;
- objects expose `.axes`, `.integrate(...)`, `.group(...)`, `.remove(...)`,
  `.prune(...)`, `.values(...)`, and HistEFT-like `.eval(...)`;
- process grouping and channel integration work with existing labels;
- `load_and_merge_histogram_pkls` compatibility checks can validate axes,
  dense binning, and WC metadata.

Serialization compatibility:

- old pkls may need a compatibility reader;
- new pkls should load without monkey-patches;
- pkl size and load time matter because plotting merges large outputs;
- a migration may need a converter from old HistEFT pkls to the new format.

What can be simplified if plotting migrates too:

- the new class does not need to mimic every legacy `SparseHist` method if the
  plotter and yield tools move to a clearer shared API at the same time;
- process grouping can be centralized outside histogram objects;
- sumw2 handling can be made explicit as variance storage instead of separate
  top-level keys;
- WC evaluation can return regular `hist` or `scikit-hist` objects with a
  documented flow-bin convention.

Tests to write before swapping implementation:

- fill one EFT sample and one non-EFT sample, then compare SM yields;
- compare `eval({})` and several nonzero WC points against current `HistEFT`;
- verify category, process, systematic, and `appl` labels after pickle round
  trip;
- verify `_sumw2` or replacement variance behavior;
- verify merge/add behavior for two compatible pkls;
- verify plotting path on a small SR and CR pkl;
- verify failure messages for unknown WCs, incompatible axes, and missing
  sumw2 companions.

## 13. Glossary

`HistEFT`
: EFT-aware histogram class implemented in `topcoffea`. Stores quadratic EFT
  coefficient terms and evaluates bin contents at a chosen WC point.

`SparseHist`
: Sparse categorical histogram layer used by `HistEFT`. Stores dense histogram
  blocks only for populated categorical keys.

`WC`
: Wilson coefficient.

`EFTfitCoefficients`
: Event branch containing quadratic coefficient values used by `HistEFT.fill`.

`process`
: Histogram axis label usually sourced from sample JSON `histAxisName`.

`channel`
: Histogram axis label for analysis category, sometimes including lepton flavor
  and njet suffixes.

`systematic`
: Histogram axis label for nominal and systematic variations.

`appl`
: Histogram axis label for signal/application-region selection.

`_sumw2`
: Companion histogram key convention for storing squared-weight content.

`CR`
: Control region.

`SR`
: Signal region.

`CFG`
: Text file listing sample JSON files and optional redirector prefixes.

## 14. Source map: relevant files and line ranges

HistEFT and sparse histogram implementation:

- `topcoffea/topcoffea/modules/histEFT.py:23-72`: class purpose and examples.
- `topcoffea/topcoffea/modules/histEFT.py:74-126`: constructor restrictions,
  WC metadata, and `quadratic_term` axis.
- `topcoffea/topcoffea/modules/histEFT.py:140-163`: quadratic-term indexing.
- `topcoffea/topcoffea/modules/histEFT.py:197-249`: EFT-aware fill.
- `topcoffea/topcoffea/modules/histEFT.py:271-305`: `eval` and `as_hist`.
- `topcoffea/topcoffea/modules/histEFT.py:307-319`: pickle reduce state.
- `topcoffea/topcoffea/modules/sparseHist.py:15-39`: sparse/dense axis model.
- `topcoffea/topcoffea/modules/sparseHist.py:124-139`: fill bookkeeping.
- `topcoffea/topcoffea/modules/sparseHist.py:299-325`: slicing behavior.
- `topcoffea/topcoffea/modules/sparseHist.py:349-406`: values, view,
  integrate, and group.

EFT helpers and pkl helpers:

- `topcoffea/topcoffea/modules/quad_fit_tools.py:203-240`: coefficient
  extraction and ordering.
- `topcoffea/topcoffea/modules/eft_helper.py:208-266`: coefficient remapping.
- `topcoffea/topcoffea/modules/utils.py:399-405`: pkl writing helper.
- `topcoffea/topcoffea/modules/compat.py:13-39`: HistEFT pickle compatibility
  hook used by local yield tools and the inspector.

Processor:

- `analysis/topeft_run2/analysis_processor.py:1-30`: imports `HistEFT`.
- `analysis/topeft_run2/analysis_processor.py:60-99`: category group
  resolution.
- `analysis/topeft_run2/analysis_processor.py:112-158`: processor init and
  histogram-name normalization.
- `analysis/topeft_run2/analysis_processor.py:212-343`: histogram axes and
  declarations.
- `analysis/topeft_run2/analysis_processor.py:450-466`: sample metadata.
- `analysis/topeft_run2/analysis_processor.py:620-631`: EFT coefficient read
  and remap.
- `analysis/topeft_run2/analysis_processor.py:642-719`: systematic lists.
- `analysis/topeft_run2/analysis_processor.py:681-711`: nominal weight setup.
- `analysis/topeft_run2/analysis_processor.py:1135-1226`: category-specific
  weights and data-driven behavior.
- `analysis/topeft_run2/analysis_processor.py:1230-1412`: selections.
- `analysis/topeft_run2/analysis_processor.py:1414-1629`: dense variables.
- `analysis/topeft_run2/analysis_processor.py:1638-1703`: category dictionary.
- `analysis/topeft_run2/analysis_processor.py:1718-1924`: fill loop and sumw2
  fill.

Runner:

- `analysis/topeft_run2/run_cr.sh:10-33`: local runner defaults.
- `analysis/topeft_run2/run_cr.sh:72-119`: active CR block.
- `analysis/topeft_run2/run_cr.sh:125-130`: active main CR loop.
- `analysis/topeft_run2/run_cr.sh:177-220`: commented SR scaffold.
- `analysis/topeft_run2/fullR3_run.sh:4-21`: usage and options.
- `analysis/topeft_run2/fullR3_run.sh:48-116`: option parsing.
- `analysis/topeft_run2/fullR3_run.sh:129-156`: CR/SR and year resolution.
- `analysis/topeft_run2/fullR3_run.sh:176-185`: output-name construction.
- `analysis/topeft_run2/fullR3_run.sh:190-270`: CFG selection.
- `analysis/topeft_run2/fullR3_run.sh:282-337`: hist-list forwarding,
  command construction, and dry-run exit.
- `analysis/topeft_run2/run_analysis.py:639-860`: CLI arguments.
- `analysis/topeft_run2/run_analysis.py:1017-1051`: output paths and test
  mode.
- `analysis/topeft_run2/run_analysis.py:1058-1175`: category and histogram-list
  resolution.
- `analysis/topeft_run2/run_analysis.py:1177-1463`: JSON/CFG loading and sample
  setup.
- `analysis/topeft_run2/run_analysis.py:1532-1556`: pretend mode and WC-list
  aggregation.
- `analysis/topeft_run2/run_analysis.py:1575-1595`: processor construction.
- `analysis/topeft_run2/run_analysis.py:1678-1765`: runner execution and pkl
  writing.

Run 3 EFT signal sample:

- `input_samples/cfgs/NDSkim_2023_mc_signal_samples_sr.cfg:7-12`: 2023 SR EFT
  signal JSON list.
- `input_samples/sample_jsons/signal_samples/ND_SRskim2023/ttH_NDSkim_2023.json:1-40`:
  selected tutorial sample metadata and WC names.

Plotting and yield consumers:

- `analysis/topeft_run2/make_cr_and_sr_plots.py:55-110`: SparseHist pickle
  load patch.
- `analysis/topeft_run2/make_cr_and_sr_plots.py:732-808`: process/channel axis
  helpers.
- `analysis/topeft_run2/make_cr_and_sr_plots.py:1738-1767`: category and appl
  integration.
- `analysis/topeft_run2/make_cr_and_sr_plots.py:2365-2479`: variable payload
  preparation.
- `analysis/topeft_run2/make_cr_and_sr_plots.py:5810-5832`: process grouping.
- `analysis/topeft_run2/make_cr_and_sr_plots.py:6140-6214`: systematic
  extraction.
- `analysis/topeft_run2/make_cr_and_sr_plots.py:6231-6277`: HistEFT value
  evaluation.
- `analysis/topeft_run2/make_cr_and_sr_plots.py:7528-7854`: plotter CLI,
  loading, merging, and dispatch.
- `topeft/modules/datacard_tools.py:175-302`: pkl loading and merge validation.
- `topeft/modules/yield_tools.py:305-383`: axis and category label helpers.
- `topeft/modules/yield_tools.py:475-567`: category/appl integration and yield
  extraction.

Plot metadata:

- `topeft/params/cr_sr_plots_metadata.yml:20-24`: CR/SR channel-label
  convention.
- `topeft/params/cr_sr_plots_metadata.yml:116-352`: SR channels.
- `topeft/params/cr_sr_plots_metadata.yml:432-503`: SR process group patterns.
- `topeft/params/cr_sr_plots_metadata.yml:530-554`: Run 2 and Run 3 lumi
  metadata.
