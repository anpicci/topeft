# Datacards, scalings, and the EFTFit/Combine boundary

`topeft` converts compatible histograms into individual physical-channel
datacards and ROOT templates, selects Wilson coefficients, and packages EFT
scalings. The combined package provides the ordered cards and scaling records
used for subsequent card combination and workspace construction with EFTFit
and Combine.

## Artifact sequence

`make_cards.py` writes one text card and ROOT template per selected physical
channel, plus row-local `selectedWCs.txt` and
`scalings-preselect.json`. The resumable matrix producer records row
completions, receipts, and metadata snapshots. Its final shared metadata
files are not a complete era package.

`build_per_era_datacard_package.py build` reads completed matrix-v2 manifests
for one era. It checks the source files recorded in their receipts, copies the
selected card/template pairs, consolidates selected WCs and scaling records,
and writes the deterministic physical-to-`chN` mapping. Each Run 2 or Run 3 package
contains `cards/`, `selectedWCs.txt`, `scalings.json`,
`physical_to_chN.json`, and provenance. A duplicate
`(physical_channel, process)` scaling identity is rejected.
Multiple upstream PKLs may contribute before that datacard identity is formed.

`build_combined_datacard_package.py build` reads the two per-era package
directories. It derives the combined mapping and scaling-channel labels,
copies cards/templates, and checks the cards-only package against its inputs.
The result includes `combined_mapping_manifest.json`, `scalings.json`,
`ordered_card_inputs.txt`, provenance, and a README. It does not
produce a combined `selectedWCs.txt` or `combinedcard.txt`.

## Repository boundary

`ordered_card_inputs.txt` lists the cards in the order used for combination.
From the combined package directory, follow the generated README:

```bash
mapfile -t cards < ordered_card_inputs.txt
combineCards.py "${cards[@]}" > combinedcard.txt
```

Card combination creates `combinedcard.txt`; workspace construction and fitting
follow in EFTFit/Combine. A missing final scaling record means the exact
channel/process pair has no external EFT morph; it is not a process-wide
fallback or normalization. The packaged mapping and ordered list determine
the combination order.

See the [card and scaling how-to](../how_to/datacards_and_scalings.md) and the
[artifact reference](../reference/datacards_and_scalings.md).
