# Missing-parton payloads

## Overview

`missing_parton_run2.root` and `missing_parton_run3.root` are the production
payloads for the `missing_parton` normalization nuisance.  The active branch
and the new pull request support the current schema as the production
contract.  The schema introduced by immutable `run3_test_mmerged` commit
`2469053a8d7ab0b42c86c68000f51b6e7f6dafff` is supported only as one explicit
legacy compatibility contract.  No other legacy payload schema is supported.

The executable contracts are covered by
`tests/test_missing_parton_payload_schema.py`, while the category registry is
maintained in `topeft/channels/ch_lst.json` and interpreted by
`topeft/modules/missing_parton_contract.py`.

## Physics definition

For each category and physical jet population, the producer compares private
`tllq` with the corresponding central `tZq` source-card inputs.  It combines
nominal yields, shape responses, and rate inputs into a non-negative fractional
uncertainty.  The public consumer converts that fraction to the directional
`lnN` factors used in cards.  The nuisance is named `missing_parton` in both
eras, so Run 2 and Run 3 use the same correlated nuisance identity.

## Source authority by era

- Run 2 uses the Andrea MP004W source-card set.
- Run 3 uses the Yawen fixyield source-card set.
- Yawen reported that her Run 2 production used Andrea's Run 2 PKL files. This
  is user-provided provenance evidence; it is not a claim of byte-level
  PKL-to-card identity because the exact private Run 2 PKL hashes are not
  available.

The accepted source manifests, including site-dependent card locations and
hashes, are archived in the MP010B8E evidence package.  Source-set labels and
the immutable manifests, rather than private absolute paths, are the durable
reproduction identifiers.

## Affected and excluded processes

The consumer applies `missing_parton` to `tllq` and `tHq`.  It does not apply
the nuisance to `tZq`, `ttll`, `ttH`, or unrelated processes.  The policy is
checked in `tests/test_make_cards_missing_parton_option.py` and
`tests/test_missing_parton_payload_roundtrip.py`.

## Current derivation semantics

Downward and upward shape errors accumulate independently in quadrature.  For
a direct jet bin, the scalar missing-parton formula is evaluated for that bin.
For a terminal population, the producer first aggregates source-level nominal
yields, directional shape responses, and rate inputs over the complete
physical tail, then applies the scalar formula exactly once.  It does not add
already-derived missing-parton amounts across source bins.

The maintained producer is `analysis/topeft_run2/missing_parton.py`.  Its
source-card parser and writer are implementation code; the immutable source
manifests and semantic payload digests below identify the installed scientific
inputs and outputs.

## Terminal-bin semantics

A registry terminal category written as `>N` has public length `N + 1`.
Physical jet indexing is used directly: index `N` represents the complete
physical population with `njet >= N`, and no index above `N` is present.  The
producer aggregates the source population before evaluating the uncertainty,
and the consumer maps the resulting public index to the same physical jet
population.

## Forward-category correction

The current schema defines both `3l_m_offZ_1b_fwd` and
`3l_p_offZ_1b_fwd` with length 5.  Index 4 is the complete `njet >= 4`
population and index 5 is absent.  This population redefinition is distinct
from the numerical change caused by correcting terminal aggregation.

The supported `run3_test_mmerged` legacy schema instead has length 6 for these
two categories: index 4 represents exactly four jets and index 5 represents
`njet >= 5`.

## Current ROOT schema

Each era file contains exactly 34 top-level `TTree` objects: one for every
`ALL_CH_LST_SR` base category, in registry key order.  Every tree contains
exactly one `tllq` branch represented as a `double`/`float64` array.  Array
lengths follow the current physical-jet terminal contract and every stored
value is finite.

The installed semantic identities are:

- Run 2: `4a869bc8ecc56adb491100e50b29d0e600a6916824b2849ff9f9d31c5a09736a`
- Run 3: `6f948c7859a43249dae70e4e679c4439425dc4384991ab2829e0d85c09eed26f`

These identities are exact assertions in the current-payload tests.  A
payload using the legacy ordering or legacy forward lengths is not a valid
current payload.

## Supported legacy run3_test_mmerged schema

The sole supported legacy contract is frozen from immutable commit
`2469053a8d7ab0b42c86c68000f51b6e7f6dafff`.  Its explicit 34-tree order,
complete per-tree length manifest, `tllq` `double`/`float64` branch contract,
and forward population meanings are constants in
`tests/test_missing_parton_payload_schema.py`.  Tests build a temporary
synthetic ROOT fixture from those constants, so CI does not depend on a Git
ref, historical commit object, external ROOT file, or private filesystem.

The immutable historical payload semantic identities, retained as provenance
rather than runtime fixtures, are:

- Run 2: `08895d0ba12fab53609b8732e992bb5da2736e215c70f6b7c9db97af6b3bc5e8`
- Run 3: `884d10b315f56444a0d205dfcce0cd5b19180d9967acaa3d0c06f17633804ff5`

This compatibility contract documents and validates that exact historical
schema.  It does not make the active producer write the legacy layout and does
not make the production consumer accept arbitrary historical payloads.

## Unsupported schemas

Unsupported layouts include historical A-specific variants, arbitrary
alphabetical orders, arbitrary legacy lengths, partially migrated schemas,
extra entries above a terminal threshold, missing or extra trees, wrong branch
types, non-finite values, and inferred or heuristic fallbacks.  A payload is
validated against one named contract; there is no “registry or alphabetical”
or “length 5 or length 6” fallback.

## Payload selection and overrides

The era defaults resolve to `missing_parton_run2.root` for Run 2 and
`missing_parton_run3.root` for Run 3.  An explicit missing-parton payload
override is used exactly as supplied.  When the nuisance is skipped or
disabled, the consumer must not open a payload.  These behaviors are covered
by `tests/test_make_cards_missing_parton_option.py`.

## Reproduction inputs

Reproduction requires the accepted source manifest for the selected era, the
`ALL_CH_LST_SR` registry in `topeft/channels/ch_lst.json`, and the maintained
producer in `analysis/topeft_run2/missing_parton.py`.  Select Andrea MP004W for
Run 2 and Yawen fixyield for Run 3.  Validate source hashes before generation,
write a scratch candidate, and compare its semantic digest to the installed
identity before considering installation.  Site-specific paths recorded in
the MP010B8E manifest are environment-dependent examples, not the contract.

## Validation summary

The installation evidence independently reconstructed all 422 public values:
177 direct and 34 terminal values for each era.  It also validated the exact
34-tree registry schema, process policy, payload override, era defaults, and
skip behavior.  The present schema tests separately validate the strict
current contract and the frozen `run3_test_mmerged` compatibility contract,
including negative tests for unsupported layouts.

## Quantitative legacy impact

With each selected source-card set held fixed, correcting only the legacy
aggregation of already-derived terminal amounts changed 28 of 34 terminal
categories in both Run 2 and Run 3.  The maximum directional effect on the
private source-card `tllq` derivation yield was approximately 0.2154 events in
Run 2 and 0.08152 events in Run 3.  The numbers of categories at or above 0.01
event were 2 and 6, respectively; at or above 0.1 event they were 1 and 0; and
at or above 1 event they were 0 and 0.

Those values are a diagnostic effect on the private source-card yield used to
derive the nuisance.  They are not a final-analysis impact and do not establish
one by themselves.  The forward-category `>=4` population redefinition is a
separate public-layout effect, not part of the pure aggregation comparison.

The accepted downstream smoke test covered Run 3 year 2022, five final
channels, and ten `tllq`/`tHq` cells.  It found zero unexpected consumer
differences, a maximum selected-versus-reference directional difference of
approximately 0.002692 events, and zero cells at or above 0.01 event.  This was
a bounded smoke test, not exhaustive era or channel coverage, and its
final-consumer quantity must not be conflated with the source-card diagnostic
above.

## Known validation coverage

Run 2 and Run 3 payload values, schemas, and focused consumer contracts have
complete installed-payload checks.  Dynamic downstream smoke coverage is
bounded: the accepted test exercised only Run 3, year 2022, five final
channels, and ten target-process cells.  It does not establish exhaustive
Run 2 or Run 3 analysis-level effects.

## Historical payload replacement

The legacy production payloads were replaced because they combined several
outdated behaviors:

- cross-coupled directional shape-error accumulation;
- aggregation of already-derived terminal missing-parton amounts;
- hard-coded public ordering;
- the old forward terminal population and array layout; and
- absence of the final source-backed, registry-driven contract.

The frozen legacy schema remains testable for explicit compatibility coverage;
it is not an alternative production contract.

## Maintenance rules

- Keep current and `run3_test_mmerged` validators explicitly named and
  separate.
- Derive the current order and lengths from `ALL_CH_LST_SR`, never from the
  payload under test.
- Change the frozen legacy manifest only with direct evidence from immutable
  commit `2469053a8d7ab0b42c86c68000f51b6e7f6dafff`.
- Do not add schema auto-detection, permissive fallbacks, or additional legacy
  layouts without a new explicit scientific decision.
- Treat payload semantic digest changes as source/derivation changes requiring
  a new evidence-backed installation, not as routine test maintenance.
- Keep source-card diagnostic effects distinct from downstream consumer
  effects in documentation and reviews.
