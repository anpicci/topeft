# Datacards, scalings, and the EFTFit/Combine boundary

Card production and statistical-workspace construction are separated so each
repository owns one stable boundary. `topeft` converts compatible histogram
artifacts into individual physical-channel cards and templates, selects Wilson
coefficients, and finalizes the channel-aware EFT scaling payload. EFTFit and
Combine later combine those cards and construct the workspace.

## Artifact sequence

`make_cards.py` writes one text card and ROOT template per selected physical
channel, plus row-local `selectedWCs.txt` and `scalings-preselect.json`. When a
campaign is split into rows, each successful row's metadata must be snapshotted
and bound to its execution receipt; the shared files left by the last row are
not a consolidated era payload.

`consolidate_datacard_metadata.py` assembles one era from an explicit accepted
successful-unit registry. It preserves producer scaling records, rejects a
duplicate physical-channel/process identity, and forms the deterministic
process-to-WC union. Multiple upstream PKLs may contribute before a physical
datacard identity is formed, but the datacard layer has exactly one logical
`(physical_channel, process)` instance within each era. A duplicate there is a
contract violation, not a merge case. The atomically published result contains
`scalings-preselect.json`, `selectedWCs.txt`, and
`consolidation-provenance.json`; the consolidator is not the finalizer and does
not produce `scalings.json`.

`datacards_post_processing.py <datacard_dir> -a` selects the current full
topology from `ch_lst.json`. It sorts physical channel names deterministically,
maps them to `ch1`, `ch2`, and so on, copies the selected individual artifacts,
and relabels every matching scaling record while preserving its other fields.
The result is `scalings.json`.

## Repository boundary

`combinedcard.txt` is neither an input nor an output of the finalizer. It is
created later when EFTFit/Combine combines the individual cards. The shared
contract is the deterministic physical-channel order and the compatible set of
individual cards, templates, selected Wilson coefficients, and final scaling
records.

A missing final scaling record means that exact channel/process pair has no
external EFT morph. It is not a process-wide fallback or normalization.

The campaign-specific `run_make_cards_run3_yawen_matrix.sh` is a DATACARD023
archival operator record. It does not own the durable region-to-distribution
mapping or define a supported current wrapper. Changing, generalizing, moving,
or deleting that runnable script requires a separate source-control decision.

After separate Run 2 and Run 3 finalization, any cross-era renaming, channel
shift, combined scaling assembly, or combined-card construction is another
packaging/consumer boundary. `datacards_post_processing.py` does not combine
the eras. EFTFit and Combine remain outside `topeft` ownership; they are not
validators for producer metadata consolidation.
Run 2 and Run 3 remain separate namespaces until that later combined-package
boundary; neither consolidated JSON position nor filesystem ordering defines
combined channel identity.

The maintained combined-package assembler consumes one explicit 258-row
`TOP22006_v1` manifest with `artifact_type` set to
`combined_mapping_manifest` and the durable
`source_per_era_package_root` field. It keeps Run 2 `ch1..ch129`, maps Run 3
per-era `ch1..ch129` to combined `ch130..ch258`, prefixes packaged
card/template filenames by era, and updates only each card's ROOT template
reference. Individual card `bin_*` identities remain physical. The manifest
supplies the ordered card list, so the later consumer invocation uses
`ordered_card_inputs.txt` instead of the historical
`ttx_multileptons-*.txt` shell glob. That ordered-input convention is new
TOP-26-006 hardening, not an Andrew-authored mechanism. A combined
`selectedWCs.txt` is outside this packaging boundary. Current fresh cards are
valid package inputs as-is; nuisance convention migration is separately owned
and does not gate package publication.

See the [card and scaling how-to](../how_to/datacards_and_scalings.md) and the
[artifact reference](../reference/datacards_and_scalings.md).
