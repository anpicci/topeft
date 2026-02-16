# Extreme Events Study Notes

This page is the canonical reference for the historical
`analysis/extreme_events_study/` workflow and visualization notes.

## Status

The scripts in this area are legacy and may need import updates after
`topcoffea` refactors.

## Study overview

The `extreme_events` processor targets very high-energy multilepton events.
Typical workflow:

1. Produce dataframes from `extreme_events.py` output.
2. Compare yields from MC using:
   - histogram sums from the main `topeft` processor output, or
   - dataframe-column sums from `extreme_events`.

Using the standard `topeft` histogram path is generally the lower-risk method.

## Extract dataframe outputs

`extreme_events.py` stores output as a dictionary of
`dataframe_accumulator` objects. Dataframes are available from each
entry's `.value`:

```python
import gzip
import pickle

with gzip.open("path/to/output/file", "rb") as infile:
    output = pickle.load(infile)

df_nleps = output["nleps"].value
df_pt_j = output["pt_j"].value
```

## Yield extraction approaches

### 1. Histogram-driven yields (preferred)

- Ensure the needed observables are defined in metadata histogram settings.
- Run the processor over the target MC sample set.
- Use the post-processing helper scripts to extract yields from histogram bins.

Example command pattern from historical notes:

```bash
python run_extreme_events.py ../../topcoffea/cfg/mc_signal_samples_NDSkim.cfg --skip-cr --do-np --executor taskvine
```

### 2. Dataframe-driven yields

- Add a `yield` column before downstream filtering.
- After filtering, sum the column from the selected dataframe
  (for example `df_nleps["yield"].sum()`).

## Visualization and iSpy workflow

- Event display files (`.ig`) can be opened in
  [iSpy WebGL](https://ispy-webgl.web.cern.ch/).
- To build `.ig` files from selected events:
  - run the `find_file` flow to identify matching non-skimmed events/files,
  - resolve parent datasets/files via `dasgoclient`,
  - produce pick-event ROOT with `edmCopyPickMerge`,
  - run the iSpy analyzer on the pick-events file.

Example `edmCopyPickMerge` pattern:

```bash
edmCopyPickMerge outputFile=pickevents.root eventsToProcess=297296:266:385206686 inputFiles=/store/data/Run2017B/DoubleMuon/AOD/...root
```

For the overall docs map, see [docs/index.md](index.md).
