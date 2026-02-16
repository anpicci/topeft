# Module Notes

This page is the canonical reference for developer notes that used to live in
`topeft/modules/README.md`.

## `parsejec.py`

- `parsejec.py` combines JES uncertainties in quadrature to produce the final
  categories used in TOP-22-006.
- Inputs are the `RegroupedV2_Summer19UL*` files from the JetMET POG.
- This is typically a one-time preparation step; the resulting payloads are
  committed under `topcoffea/data/JEC/Quad_Summer19UL1*`.

For workflow-level run configuration, use
[Run analysis configuration flow](../run_analysis_configuration.md). For the
full docs map, see [docs/index.md](../index.md).
