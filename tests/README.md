# Running tests in `topeft`

Run tests from the `topeft` repository root.

## Basic usage

```bash
python -m pytest -q
```

Run a single test file:

```bash
python -m pytest -q tests/test_processor_logging.py
```

Run a keyword-selected subset:

```bash
python -m pytest -q -k "futures"
```

## Coverage (optional)

```bash
python -m pytest --cov=. --cov-report=term
python -m pytest --cov=. --cov-report=html
```

## Notes

- Some tests exercise optional integrations (for example TaskVine) and may skip
  automatically when required runtime dependencies are unavailable.
- This repository currently has no global pytest `addopts`/marker policy in
  `pyproject.toml` or `pytest.ini`; use explicit `pytest` flags/selections in
  your command line when you need targeted runs.
