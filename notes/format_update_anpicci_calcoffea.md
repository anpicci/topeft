# Branch notes for `format_update_anpicci_calcoffea`

- Verified the sibling `topcoffea` checkout remained on a coordinated ref for dependency alignment.
- The workflow runner continues to invoke `coffea.processor.Runner` with the `AnalysisProcessor` instance (see `analysis/topeft_run2/workflow.py`).
- Updated `analysis/topeft_run2/analysis_processor.py` so `AnalysisProcessor` directly subclasses `coffea.processor.ProcessorABC`, matching the executor's validation expectations and avoiding ProcessorABC mismatch errors.
