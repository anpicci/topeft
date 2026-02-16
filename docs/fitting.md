# Datacard fitting workflow

This page is the canonical reference for the datacard-to-fit handoff used in
`topeft`. Create datacards from histogram outputs inside this repository, then
run the statistical fit in a separate CMSSW/Combine environment.

## 1. Create datacards from histogram outputs

From the repository root, run `make_cards.py` with the histogram pickle
produced by the analysis workflow:

```bash
python analysis/topeft_run2/make_cards.py path/to/histos_np.pkl.gz \
    --do-nuisance \
    --var-lst lj0pt ptz \
    -d path/to/output/cards
```

Choose any writable output directory for `-d` (for example a project scratch
area or local work directory).

## 2. Run Combine outside this repository

After datacards are produced, perform the statistical fit in a CMSSW release
that includes Combine tools. For the maintained fitting workflow and workspace
steps, use the [EFTFit](https://github.com/TopEFT/EFTFit) guide.

## 3. Related workflow references

- [Run 2 quickstart pipeline](quickstart_run2.md) for analysis-side production
  of histogram inputs.
- [TaskVine workflow quickstart](taskvine_workflow.md) for distributed
  execution setup.
- [Documentation index](index.md) for the full docs map.
