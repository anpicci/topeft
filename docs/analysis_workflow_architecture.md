# Analysis workflow architecture

## Documentation and source ownership

This repository has no generated API-reference toolchain. Curated Markdown owns
tutorials, task recipes, artifact schemas, and architecture explanations.
CLI parsers, typed function signatures, source docstrings, registries, and
configuration files remain the machine-near authority. Documentation links to
those owners instead of copying every volatile function signature.

The four documentation roles are intentionally separate:

- [tutorial](analysis_workflow_tutorial.md): one guided artifact path;
- [how-to](analysis_workflow_how_to.md): executable task recipes;
- [reference](analysis_workflow_reference.md): defaults, schemas, ownership,
  failure behavior, and extension surfaces;
- this explanation: why the current layers and repository boundary exist.

## Wrapper and direct-entrypoint layering

`run_cr.sh` automates a campaign; `fullR3_run.sh` automates sample/config and
command selection; `run_analysis.py` executes one analysis request. The
direct interface is supported independently so the shell wrappers never become
the only specification of the workflow.

The same rule applies downstream. `run_plotter.sh` is reusable automation over
`make_cr_and_sr_plots.py`. No current general card wrapper is maintained, so
`make_cards.py` is the supported interface. Campaign/date/site-specific matrix
scripts are retained only as operator records and are not promoted into public
automation. Scaling finalization is directly owned by
`datacards_post_processing.py`.

## Artifact and provenance model

The workflow transports more than nominal histograms. A PKL family is coupled
to an adjacent sidecar that records source/family identity, axes, Wilson
coefficients, sumw2 selection and content, production sample profile, and
transformation provenance. Merge and downstream consumers validate these
semantic fields before composing fragments. A matching filename or histogram
shape is insufficient evidence of compatibility.

Cards preserve the same semantic chain: exact late rebinning is applied to
nominal, sumw2, EFT, and scaling payloads; individual card/template names encode
physical channel and distribution; `selectedWCs.txt` identifies the fitted
parameter selection; and scaling records remain channel/process/bin-aware.

## Production profile and configuration model

Profiles in `run_cr.sh` are orchestration plans, not alternate physics
registries. `fullR3_run.sh` owns runtime-reachable NDSkim bundles and passes the
resolved sample universe into `run_analysis.py`. The processor and installed
package configuration own selections, corrections, histogram definitions,
sumw2 policy, and artifact serialization. This keeps resume state and campaign
automation from silently redefining analysis behavior.

## Sumw2 model

Selective sumw2 storage is a concrete target policy over dataset, process, and
histogram family. The selected mode resolves before execution, is serialized
in schema-v2 provenance, and is checked against actual companions and consumer
requirements. `production` is a policy/default name; schema version 2 is the
format used to serialize the resolved contract. These are separate concepts.

Adding a mode extends the registry and resolution semantics. Changing the
default changes what an absent config means. Changing the provenance schema
changes artifact compatibility. Treat them as three distinct developer
operations.

## Flexible-binning model

Processing binning determines the physical dense axis stored during histogram
production. Fitting binning is an exact downstream aggregation view with a
family default and optional category/channel overrides. Plotting defaults to
the processing view; cards default to the fitting view. Both call the same
resolver, preventing plot/card drift.

This model permits a coarse fit view without losing the reproducible source
axis. It also makes provenance important: changing fitting edges changes card
and scaling meaning even when a PKL can still be read. `ptz` and `ptll` remain
different observable families; only explicit off-Z final-category mappings use
`ptll`.

## Correction-lib to EFTFit/Combine boundary

Correction-lib produces and selects individual cards/templates, records the
selected WCs, and emits final physical-channel-to-`chN` scaling records.
EFTFit/Combine owns card combination and workspace construction. Consequently
`combinedcard.txt` appears only after the handoff and cannot be an input to the
scaling finalizer.

The deterministic sorted physical-channel order is the shared boundary
contract. It lets final `scalings.json` refer to the same `chN` namespace that
the later combined card/workspace uses. A scaling record is consumed
bin-by-bin for one channel/process; absence means no external EFT morph for
that pair, not an implicit global normalization.
