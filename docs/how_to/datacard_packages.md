# Build and use datacard packages

This guide starts after successful datacard matrix execution. It follows the
individual TXT cards, ROOT templates, and EFT scalings to a package that a fit
consumer can use. For matrix production itself, see [create cards and finalize
EFT scalings](datacards_and_scalings.md). For exact interfaces and nuisance
names, see the [reference](../reference/datacards_and_scalings.md).

## Artifact ladder

| Step and producer | Input → output | Check at the boundary | Source changed? |
| --- | --- | --- | --- |
| `build_per_era_datacard_package.py build` | Completed matrix-v3 units and successful receipts → one Run 2 or Run 3 package | Receipt bindings, source hashes, exact physical-target coverage, copied members and metadata | No |
| `build_combined_datacard_package.py build` | Matching Run 2 and Run 3 packages → original combined package | Source package and physical-surface checks; staged and published certification | No |
| `standardize_systematics.py` | Certified combined package → fresh standardized combined package | Package contract, card/ROOT pairing and nuisance collision checks | No; the output is a sibling |
| `build_fit_input_package.py` (optional) | Either valid combined package plus fit config → fit-input package | Metadata hashes, ordered mapping, selected members and copied-byte hashes | No |
| EFTFit/Combine | Ordered packaged cards and fit configuration → `combinedcard.txt`, then workspace and fit products | Consumer-side card, model and physics checks | The fit consumer owns its writable outputs |

Each package is a directory of inputs and provenance, not a workspace or a fit.
The optional fit-input projection prepares portable inputs; it does not combine
cards. Package certification checks structure and identity, not physics.

## Build a per-era package

The maintained builder is
`analysis/topeft_run2/build_per_era_datacard_package.py`. In the normal route,
pass one or more original matrix-v3 manifests for an era. The requested
physical targets are exactly the union of that era's manifest rows, including
restricted subsets. Every requested target must be covered once by a
successful current receipt. The builder checks each receipt against its
original manifest SHA-256, row, attempt, command and runtime binding; verifies
recorded source TXT/ROOT pairs and row-local metadata snapshots; and rejects
duplicate physical targets or scaling identities. Missing and extra completed
targets are reported separately. The builder does not run missing units.

For recovery across overlapping original manifests, repeat
`--selected-unit MANIFEST_SHA256:ROW_ID:ATTEMPT_ID` for every authoritative
successful unit and supply each original manifest with `--matrix-manifest`.
This route requires exact coverage of the maintained `ALL_CH_LST_SR` full-era
target set. It rejects omitted or unknown units and duplicate selected targets.
The SHA-256 names the **original manifest bytes** bound to the receipt; a new
restricted manifest has a different hash and cannot become that receipt's
authority. Without selections, overlapping declarations are an error.

The output path must be absolute and absent. The builder also requires its
private sibling staging path to be absent. It verifies copied files and
metadata in staging, renames that directory to the final output only after
those checks, and reads back publication. It never overwrites an existing
package.

| Published member | Meaning |
| --- | --- |
| `cards/` | One copied TXT card and matching ROOT template per requested physical target. |
| `selectedWCs.txt` | Consolidated selected-WC JSON from row snapshots. |
| `scalings.json` | Consolidated scaling records with channels relabeled to this era's `chN` map. |
| `physical_to_chN.json` | Ordered physical target to per-era `chN` rows. |
| `package-provenance.json` | Analysis/era, source manifest hashes and unit count, builder identity, member hashes and card counts. |

Row-local `scalings-preselect.json`, receipts, matrix manifests, and runner logs
remain source artifacts. There is no `ordered_card_inputs.txt`, combined
`selectedWCs.txt`, `combinedcard.txt`, or workspace at this layer.

## Build the original combined package

`analysis/topeft_run2/build_combined_datacard_package.py build` consumes one
validated package for each era. Their analysis identities and **sets of
physical channel/distribution targets** must match; equal restricted subsets
are valid. Their local `chN` labels need not match. A mismatch identifies
`missing_from_run2` and `missing_from_run3` before publication.

The builder assigns combined `chN` labels deterministically: Run 2 rows in
their per-era order, then Run 3 rows offset by the Run 2 row count. It copies
TXT/ROOT pairs, adjusts the TXT template reference to its combined filename,
and relabels scaling channels. A fresh, absolute destination and absent
private staging directory are required. `build` certifies the staged package
against both inputs, publishes it, then certifies the published directory.
The separate `certify` command reads an existing package against the same two
per-era packages. It checks inventory, mappings, ordered cards, hashes,
scalings, card/template relationships, provenance and the generated README;
it does not run Combine or validate physics.

| Published member | Meaning |
| --- | --- |
| `cards/` | Combined-named copied TXT/ROOT pairs. |
| `scalings.json` | Per-era records relabeled to combined channels. |
| `combined_mapping_manifest.json` | Ordered rows connecting physical, per-era, and combined identities; includes the package root. |
| `ordered_card_inputs.txt` | One `cards/...txt` path per mapping row, in combination order. |
| `package-provenance.json` | Input identities and hashes, assembler identity, output counts and metadata hashes. |
| `README.md` | Package-local consumer instructions. |

There is no combined `selectedWCs.txt`, `combinedcard.txt`, or workspace.

## Card order is an input contract

`ordered_card_inputs.txt` is the **sole card-order authority** for combined-card
construction. It is tied to `combined_order_index` in the mapping and to the
scaling channel labels. The generated README command requires the **combined
package root** as its working directory, so its relative `cards/` paths and
card-local ROOT references resolve. For actual consumption, use an EFTFit-owned
writable copy of that package tree as the working directory:

```bash
cd "$consumer_combined_package"
mapfile -t cards < ordered_card_inputs.txt
combineCards.py "${cards[@]}" > combinedcard.txt
```

Do not glob `*.txt`, sort filenames lexicographically, infer order from `chN`,
or reorder cards manually. The `Run2_`/`Run3_` filenames and `chN` strings
identify members; the ordered file supplies the consumer sequence.

## Three channel identities and their mappings

The **physical identity** names a channel and distribution, such as
`2los_onZ_1tau_3j_ptz`. A **per-era `chN`** identifies it within one Run 2 or
Run 3 package. A **combined `chN`** identifies the era-specific card in the
combined sequence. The same physical target occurs once per era when both
packages cover it. `physical_to_chN.json` exists in each per-era package;
`combined_mapping_manifest.json` exists in a combined package.

For example, this is a row from the accepted original combined package (the
number and name are illustrative of that package, not a required first row):

```json
{
  "era": "run2",
  "physical_name": "2los_onZ_1tau_3j_ptz",
  "per_era_chN": "ch1",
  "combined_chN": "ch1",
  "combined_order_index": 1,
  "destination_txt_name": "Run2_ttx_multileptons-2los_onZ_1tau_3j_ptz.txt",
  "destination_root_name": "Run2_ttx_multileptons-2los_onZ_1tau_3j_ptz.root"
}
```

The matching ordered-file entry is
`cards/Run2_ttx_multileptons-2los_onZ_1tau_3j_ptz.txt`. For Run 3, the
combined channel uses the Run 2 row-count offset, even when its per-era label
has the same spelling as a Run 2 label.

## EFT scaling records

`DatacardMaker` first writes physical-channel scaling records in each
successful matrix unit's `scalings-preselect.json`. The per-era builder
consolidates those snapshots and changes each selected record's channel to
the per-era mapping label. The combined builder relabels it again to the
combined mapping label. Keep the scaling payload with its package and preserve
the ordered card/mapping relationship: a scaling channel must denote the card
the consumer will use. An absent **exact channel/process** record means no
external EFT morph for that pair; it is not a process-wide fallback or a
normalization instruction. Standardization copies `scalings.json` byte for
byte and does not alter EFT coefficients or channels. The fit consumer owns
later interpretation under its maintained contract.

## Standardize a combined package

`analysis/topeft_run2/standardize_systematics.py` accepts a certified
`TOP26006_v1` combined package and a distinct, absent destination outside the
source package. It validates the package metadata, order, card/ROOT pairing,
and nuisance identities before writing. It renames TXT shape and rate nuisance
rows and matching ROOT systematic keys using each mapping row's era. Nuisance
name splits/collisions and ROOT-key collisions fail closed.

The fresh sibling has the same six top-level member names as the original
combined package. `ordered_card_inputs.txt` and `scalings.json` are copied
byte for byte. The logical mapping rows are preserved, while the manifest's
package root is updated. Provenance is regenerated with the new package root,
metadata hashes, version/date, source-package link, standardizer identity and
member inventory. ROOT files are rewritten, so serialization bytes can differ.

**DatacardMaker has already realized the correlation topology before
standardization.** This transformation changes final names consistently; it
does not manufacture correlations or reconstruct them from PKLs. It creates
neither a combined card nor a workspace or fit result.

| Property | Original combined package | Standardized combined package |
| --- | --- | --- |
| Physical target surface | From matching per-era inputs | Same targets |
| Card order | `ordered_card_inputs.txt` | Same bytes |
| EFT scalings | Combined-channel records | Same bytes |
| Mapping rows | Physical/per-era/combined identities | Same logical rows; package root updated |
| TXT nuisance names | Producer names | Standardized final names |
| ROOT systematic keys | Producer names | Corresponding standardized names; ROOT bytes may differ |
| Package provenance | Original assembler and source identities | Regenerated, with standardization lineage |
| Scientific correlation topology | Already realized in cards | Preserved by consistent renaming |
| Workspace ownership | EFTFit/Combine | EFTFit/Combine |
| Source mutability | Built from unchanged per-era sources | Original combined package remains unchanged |

### Example: accepted TOP-26-006 full package, October 2026

The accepted original `top26006_combined_package_261005_v1` and standardized
`top26006_standardized_package_261006_c04b4c82_v1` each contain 258 TXT and
258 ROOT files in `cards/`, 258 ordered card entries, and 258 combined mapping
rows. Their ordered-file and scaling-file SHA-256 values match across the two
packages. The standardized mapping retains the logical rows and records a new
package root and provenance. Accepted comparison established that its 258 TXT
cards match the previously accepted standardized derivative byte for byte;
ROOT scientific histogram content was equivalent although serialization bytes
need not match. These are observations for these releases, not package-format
cardinality or universal byte-identity requirements. Neither is a workspace.

## Optional fit-input package

`analysis/topeft_run2/build_fit_input_package.py` takes either valid combined
package and a fit YAML config. It validates the combined mapping, ordered
inputs, hashes, selected card members and config, then copies the selected
TXT/ROOT members under `datacards/cards/`. It also preserves
`datacards/ordered_card_inputs.txt` and `datacards/scalings.json` byte for byte.
The fresh output contains `config/TOP_26_006.yml`,
`fit-input-manifest.json`, and `README.md` in addition to `datacards/`.
The manifest records the selected file inventory, ordered channel mapping,
input snapshot hash, config hash, and source package provenance. Package
metadata are represented there rather than copied wholesale into `datacards/`.

This projection does not run `combineCards.py` or construct a workspace.
EFTFit owns its writable card directory and subsequent Combine products.
Follow the fit-input README when consuming that projection; its paths are
relative to `datacards/`.

## Inspect before handoff

**Structural/package validation**

1. Before using a per-era package, confirm its original manifest/receipt
   identities, exact requested physical coverage, paired TXT/ROOT files,
   `physical_to_chN.json`, scaling identities and provenance hashes. Use a
   fresh output; a runner's last shared metadata files are not an era package.
2. Before combining, confirm both eras declare the same physical target set
   and analysis identity. The combined builder certifies staging and final
   output against those exact inputs.
3. Before standardizing, run `certify` with the original two per-era inputs;
   confirm the destination is absent and outside the source package. Inspect
   the new provenance and ordered-file/scalings identities afterward.
4. Before fit handoff, check the combined package's order, mapping, metadata
   hashes and complete TXT/ROOT pairs. The fit-input builder enforces its
   selected consumer contract and records the copied-byte inventory.

**Scientific validation** is separate: review card rates, shapes, nuisance
effects/correlations, EFT scaling content, and the intended physics model with
the appropriate analysis and fit owners. A successful schema/hash/package
certification does not establish scientific validity.

## Common failure modes

| Anti-pattern | Why it fails | Correct action |
| --- | --- | --- |
| Glob or sort TXT cards | Filename order is not the consumer order | Read `ordered_card_inputs.txt` in sequence |
| Edit a package in place | Breaks recorded identity and provenance | Build a fresh sibling and revalidate |
| Mix TXT from one package with ROOT from another | Shape references and nuisance keys may disagree | Keep each package's paired TXT/ROOT files together |
| Copy only TXT cards | Shape templates are required inputs | Copy the selected ROOT templates too; use the fit-input builder |
| Combine unequal Run 2/Run 3 physical surfaces | Era pairings and mapping are incomplete | Build matching target sets in both eras |
| Regenerate a restricted manifest for old receipts | Receipt hashes bind the original manifest bytes | Supply original manifests and exact `--selected-unit` keys |
| Treat certification as physics validation | Hashes and schema do not test scientific correctness | Perform separate physics review |
| Require standardized ROOT byte identity | ROOT rewriting can change serialization | Compare scientific histogram content when needed |
| Assume a package contains a combined card/workspace | Package builders stop at pre-workspace inputs | Run the consumer-side card and workspace steps |

## Minimal command recipes

Run the Python entrypoints from the TOPEFT repository root with its supported
environment. Set these shell variables to existing inputs and **fresh absolute**
output paths at your site. Repeat `--matrix-manifest` for each contributing
original manifest and `--selected-unit` for each chosen recovery receipt.

```bash
python analysis/topeft_run2/build_per_era_datacard_package.py build \
  --era run2 --matrix-manifest "$run2_manifest" \
  --output "$run2_package" --analysis TOP-26-006

python analysis/topeft_run2/build_per_era_datacard_package.py build \
  --era run3 --matrix-manifest "$run3_manifest" \
  --output "$run3_package" --analysis TOP-26-006

# Recovery example: supply all original manifests and all selected unit keys.
python analysis/topeft_run2/build_per_era_datacard_package.py build \
  --era run2 --matrix-manifest "$original_manifest_a" \
  --matrix-manifest "$original_manifest_b" \
  --selected-unit "$manifest_sha_a:$row_id_a:$attempt_id_a" \
  --selected-unit "$manifest_sha_b:$row_id_b:$attempt_id_b" \
  --output "$recovered_run2_package" --analysis TOP-26-006

python analysis/topeft_run2/build_combined_datacard_package.py build \
  --run2-package "$run2_package" --run3-package "$run3_package" \
  --output "$combined_package" --analysis TOP-26-006 \
  --package-date "$package_date_yymmdd" --package-version "$package_version"

python analysis/topeft_run2/build_combined_datacard_package.py certify \
  --package-root "$combined_package" \
  --run2-package "$run2_package" --run3-package "$run3_package"

python analysis/topeft_run2/standardize_systematics.py \
  --input-package "$combined_package" --output-package "$standardized_package"

python analysis/topeft_run2/build_fit_input_package.py \
  --combined-package "$standardized_package" --fit-config "$fit_config" \
  --output "$fit_input_package"
```

For direct downstream combination, work in a writable consumer copy of the
chosen combined package root. The package README's command is:

```bash
cd "$consumer_combined_package"
mapfile -t cards < ordered_card_inputs.txt
combineCards.py "${cards[@]}" > combinedcard.txt
```

The fit-input README provides its own `datacards/` working-directory recipe.
Workspace creation and fit execution are EFTFit/Combine steps.
