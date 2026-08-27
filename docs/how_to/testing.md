# Run focused validation

Run tests from the `topeft` repository root in the supported project
environment. Do not install packages ad hoc to make one command pass; resolve
environment changes through the project setup process.

Use the narrowest test that owns the contract you changed:

```bash
python -m pytest -q tests/test_axis_binning.py
python -m pytest -q tests/test_sumw2_policy.py
python -m pytest -q tests/test_fullr3_run_wrapper.py
```

For CLI-facing documentation or option changes, use the corresponding help or
preflight test. For example, `tests/test_run_analysis_cli_help.py` protects the
direct analysis help surface, while `tests/test_run_analysis_preflight.py`
checks important fail-before-execution paths.

## Match changes to test owners

| Change surface | Start with |
| --- | --- |
| `run_cr.sh` production profiles/state | `test_run3_full_production_profile.py`, plus the profile-specific resume test |
| `fullR3_run.sh` forwarding | `test_fullr3_run_wrapper.py` |
| `run_analysis.py` CLI/preflight | `test_run_analysis_cli_help.py`, `test_run_analysis_preflight.py` |
| artifact/sidecar publication | `test_histogram_artifact_sidecars.py` and the affected producer/consumer test |
| nonprompt transformation | `test_run_data_driven*.py`, `test_data_driven_products.py`, policy tests |
| sumw2 modes/defaults | `test_sumw2_policy.py` and affected producer/consumer tests |
| processing/fitting binning | `test_axis_binning.py`, `test_datacard_late_rebin.py`, affected plotting tests |
| plotting metadata or CLI | `test_make_cr_and_sr_plots*.py` |
| cards/multi-PKL merge | `test_make_cards*.py`, selective-sumw2 and split-boundary tests |

A focused passing test establishes only its asserted contract. It does not
replace source review, cross-document link checks, or a representative
downstream validation when a change affects produced artifacts.

See each reference page's **Validation owner** entry for the exact tests tied
to a component or symbol.
