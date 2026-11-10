# Invocation-local jet correction build reuse

`process(events)` keeps one configured regular-jet factory, created at its
first reached jet request. It reuses one analysis base for nominal, every
advertised JES/JER label and MET unclustered variations. Eligibility comes
from the maintained jet and MET lists; it does not classify labels by spelling.
Cleaning and raw-pT, raw-mass, rho and generator-pT preparation still run for
every request, followed by the maintained systematic selector and consumers.
No JES source or fill is removed.

In 2018 a second base and a separate live lazy cache belong to the full HEM
collection. Each iteration still selects the active full view and evaluates
the HEM event veto at its existing location. Outside 2018, the HEM view remains
an alias of the active analysis view. Tau and muon requests keep their separate
analysis builds, even when their cleaning masks happen to coincide. Type-1
MET, CorrT1 jets and its internal regular-jet build remain separate.

The bases and factory belong only to the invocation. The analysis-base
reference is dropped after the last eligible iteration's consumers; remaining
local references are dropped after the final iteration's consumers. Existing
`events.caches` entries are neither cleared nor removed. Releasing a base
wrapper does not prove that its numerical buffers have been freed.

Every derived view receives a shallow wrapper before selection and annotation.
Field replacement therefore does not annotate the cached root. Numerical
buffers and lazy nodes are shared: consumers must treat those buffers as
read-only. A shallow wrapper does not protect against NumPy in-place writes,
cache eviction or a consumer that regenerates a random node. The implementation
adds no eager materialization, random reseeding or new random algorithm.
The maintained FlavorQCD chained setter is preserved, including its actual
Awkward-1 behavior; this change does not repair or reinterpret it.

## Focused qualification

`tests/test_jet_build_reuse.py` compares native correctionlib/JEC/JER outputs
with verbatim frozen helpers from the declared baseline cut. Their checksum
is checked before use; the tests require no historical Git object or fetch. Fixtures include
hybrid and stochastic JER, Run-3 forward suppression, irregular event offsets,
all advertised views in eight years, repeated/reordered demands, field
annotations, separate full HEM membership, tau threshold and FO-jet membership
counterexamples, data and nominal-only modes, and native empty/partitioned
input behavior. The fully flat-empty JER exception is preserved, not fixed.
The explicit in-place-write probe demonstrates the shared-buffer limitation.

`tests/test_jet_build_reuse_consumers.py` executes the processor's maintained
post-build jet statements and compares real JVM/HEM, good/forward and b-tag
selection, leading jets, native b-tag weights, SparseHist/HistEFT coefficients,
SM evaluation, sumw2 and flow arrays. It serializes and reopens candidate
results before comparison. These are bounded consumer probes, not a full
`process(events)` or production-campaign qualification. Lepton event selection,
trigger weights and the complete analysis category/fill matrix are not covered
by those fixtures. Numerical comparisons in the new tests are exact; existing
oracle tolerances are unchanged.

Build counts include the separate native Type-1 build. For the complete MC
request population with systematics and taus enabled, the conditional counts
are 44 to 22 for 2016APV/2016/2017, 87 to 23 for 2018, and 56 to 30 for Run 3.
Actual observations, resource measurements and any microbenchmark belong to
the qualification evidence. A small-fixture microbenchmark is not production
throughput or proof of a global minimum. Integration and production adoption
require their separate decisions.
