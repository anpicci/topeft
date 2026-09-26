# Datacards, scalings, and the EFTFit/Combine boundary

Card production and statistical-workspace construction are separated so each
repository owns one stable boundary. `topeft` converts compatible histogram
artifacts into individual physical-channel cards and templates, selects Wilson
coefficients, and finalizes the channel-aware EFT scaling payload. EFTFit and
Combine later combine those cards and construct the workspace.

## Artifact sequence

`make_cards.py` writes one text card and ROOT template per selected physical
channel, plus row-local `selectedWCs.txt` and
`scalings-preselect.json`. The resumable matrix producer records row
completions, receipts, and metadata snapshots. Its final shared metadata
files are not a complete era package.

`build_per_era_datacard_package.py build` consumes validated matrix-v2
completions for one era. It rechecks receipt-bound sources, copies the selected
card/template pairs, consolidates selected WCs and scaling records, and writes
the deterministic physical-to-`chN` mapping. Each Run 2 or Run 3 package
contains `cards/`, `selectedWCs.txt`, `scalings.json`,
`physical_to_chN.json`, and provenance. A duplicate
`(physical_channel, process)` scaling identity is a contract violation.
Multiple upstream PKLs may contribute before that datacard identity is formed.

`build_combined_datacard_package.py build` consumes the two per-era package
roots. It derives the combined mapping and scaling-channel labels, copies
cards/templates, and source-certifies a cards-only package. The result includes
`combined_mapping_manifest.json`, `scalings.json`,
`ordered_card_inputs.txt`, provenance, and a consumer README. It does not
produce a combined `selectedWCs.txt` or `combinedcard.txt`.

## Repository boundary

`ordered_card_inputs.txt` is the current card-order authority. From the
combined package root, the later consumer follows the generated README:

```bash
mapfile -t cards < ordered_card_inputs.txt
combineCards.py "${cards[@]}" > combinedcard.txt
```

EFTFit and Combine own the combined card and workspace. A missing final
scaling record means the exact channel/process pair has no external EFT morph;
it is not a process-wide fallback or normalization. Filesystem order and the
historical `ttx_multileptons-*.txt` shell glob do not define the mapping.

The older `consolidate_datacard_metadata.py`,
`datacards_post_processing.py`,
`assemble_combined_datacard_package.py`, and
`finalize_combined_datacard_package.py` describe predecessor packaging
procedures. They remain separate source surfaces; their retirement status is
not decided here. The campaign-specific
`run_make_cards_run3_yawen_matrix.sh` is a DATACARD023 archival operator
record. Nuisance convention migration is separately owned and does not
change this packaging boundary.

See the [card and scaling how-to](../how_to/datacards_and_scalings.md) and the
[artifact reference](../reference/datacards_and_scalings.md).
