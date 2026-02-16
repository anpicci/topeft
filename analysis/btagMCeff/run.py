#!/usr/bin/env python
"""Run the b-tagging MC-efficiency Coffea processor.

Purpose:
Launch ``btagMCeff.AnalysisProcessor`` over JSON/CFG sample manifests to build
histograms used for b-tagging efficiency studies.

Inputs/outputs:
- Input: one or more sample JSON/CFG files plus optional redirector prefix.
- Output: a gzip-compressed cloudpickle histogram artifact in ``--outpath``
  (default filename base: ``btagMCeff``).

Side effects:
- Reads sample metadata files and remote/local ROOT files.
- Executes Coffea runners (futures executor) and writes output files.
- Creates the output directory when needed.

How to run:
- ``python analysis/btagMCeff/run.py input_samples/sample_jsons/test_samples/UL17_private_ttH_for_CI.json``
- ``python analysis/btagMCeff/run.py input_samples/sample_jsons/test_samples/UL17_private_ttH_for_CI.json --test --outpath histos``
"""

import json
import time
import cloudpickle
import gzip
import os

import numpy as np
import coffea.processor as processor
from coffea.nanoevents import NanoAODSchema

from analysis.btagMCeff import btagMCeff
from topeft.modules.runner_output import normalise_runner_output, tuple_dict_stats

if __name__ == '__main__':
    from topeft.modules.logging_config import configure_topeft_logging
    configure_topeft_logging("INFO")

    import argparse
    parser = argparse.ArgumentParser(
        description="Run the b-tag MC-efficiency processor and write histogram output."
    )
    parser.add_argument('jsonFiles'        , nargs='?', default='', help = 'JSON or CFG file(s) containing sample metadata')
    parser.add_argument('--prefix', '-r'   , nargs='?', default='', help = 'Redirector prefix prepended to each input file path')
    parser.add_argument('--test','-t'       , action='store_true'  , help = 'Run a fast smoke test with reduced chunks/workers')
    parser.add_argument('--nworkers','-n'   , default=8  , help = 'Number of local workers')
    parser.add_argument('--chunksize','-s'   , default=500000  , help = 'Number of events per chunk')
    parser.add_argument('--nchunks','-c'   , default=None  , help = 'Limit the number of chunks processed')
    parser.add_argument('--outname','-o'   , default='btagMCeff', help = 'Base name for the output histogram file')
    parser.add_argument('--outpath','-p'   , default='histos', help = 'Directory where output files are written')
    parser.add_argument('--treename'   , default='Events', help = 'Tree name inside each input ROOT file')

    args = parser.parse_args()
    jsonFiles  = args.jsonFiles
    prefix     = args.prefix
    dotest     = args.test
    nworkers   = int(args.nworkers)
    chunksize  = int(args.chunksize)
    nchunks    = int(args.nchunks) if not args.nchunks is None else args.nchunks
    outname    = args.outname
    outpath    = args.outpath
    treename   = args.treename

    if dotest:
        nchunks = 2
        chunksize = 10000
        nworkers = 1
        print('Running a fast test with %i workers, %i chunks of %i events'%(nworkers, nchunks, chunksize))

    ### Load samples from json
    samplesdict = {}
    allInputFiles = []

    def LoadJsonToSampleName(jsonFile, prefix):
        sampleName = jsonFile if not '/' in jsonFile else jsonFile[jsonFile.rfind('/')+1:]
        if sampleName.endswith('.json'): sampleName = sampleName[:-5]
        with open(jsonFile) as jf:
            samplesdict[sampleName] = json.load(jf)
            samplesdict[sampleName]['redirector'] = prefix

    if isinstance(jsonFiles, str) and ',' in jsonFiles:
        jsonFiles = jsonFiles.replace(' ', '').split(',')
    elif isinstance(jsonFiles, str):
        jsonFiles = [jsonFiles]
    for jsonFile in jsonFiles:
        if os.path.isdir(jsonFile):
            if not jsonFile.endswith('/'): jsonFile+='/'
            for f in os.path.listdir(jsonFile):
                if f.endswith('.json'): allInputFiles.append(jsonFile+f)
        else:
            allInputFiles.append(jsonFile)

    # Read from cfg files
    for f in allInputFiles:
        if not os.path.isfile(f):
            raise Exception(f'[ERROR] Input file {f} not found!')
        # This input file is a json file, not a cfg
        if f.endswith('.json'):
            LoadJsonToSampleName(f, prefix)
        # Open cfg files
        else:
            with open(f) as fin:
                print(' >> Reading json from cfg file...')
                lines = fin.readlines()
                for l in lines:
                    if '#' in l:
                        l=l[:l.find('#')]
                    l = l.replace(' ', '').replace('\n', '')
                    if l == '': continue
                    if ',' in l:
                        l = l.split(',')
                        for nl in l:
                            if not os.path.isfile(l):
                                prefix = nl
                            else:
                                LoadJsonToSampleName(nl, prefix)
                    else:
                        if not os.path.isfile(l):
                            prefix = l
                        else:
                            LoadJsonToSampleName(l, prefix)


    flist = {}
    nevts_total = 0
    for sname in samplesdict.keys():
        redirector = samplesdict[sname]['redirector']
        flist[sname] = [(redirector+f) for f in samplesdict[sname]['files']]
        samplesdict[sname]['year'] = samplesdict[sname]['year']
        samplesdict[sname]['xsec'] = float(samplesdict[sname]['xsec'])
        samplesdict[sname]['nEvents'] = int(samplesdict[sname]['nEvents'])
        nevts_total += samplesdict[sname]['nEvents']
        samplesdict[sname]['nGenEvents'] = int(samplesdict[sname]['nGenEvents'])
        samplesdict[sname]['nSumOfWeights'] = float(samplesdict[sname]['nSumOfWeights'])
        # Print file info
        print('>> '+sname)
        print('   - isData?      : %s'   %('YES' if samplesdict[sname]['isData'] else 'NO'))
        print('   - year         : %s'   %samplesdict[sname]['year'])
        print('   - xsec         : %f'   %samplesdict[sname]['xsec'])
        print('   - histAxisName : %s'   %samplesdict[sname]['histAxisName'])
        print('   - options      : %s'   %samplesdict[sname]['options'])
        print('   - tree         : %s'   %samplesdict[sname]['treeName'])
        print('   - nEvents      : %i'   %samplesdict[sname]['nEvents'])
        print('   - nGenEvents   : %i'   %samplesdict[sname]['nGenEvents'])
        print('   - SumWeights   : %i'   %samplesdict[sname]['nSumOfWeights'])
        print('   - Prefix       : %s'   %samplesdict[sname]['redirector'])
        print('   - nFiles       : %i'   %len(samplesdict[sname]['files']))
        for fname in samplesdict[sname]['files']: print('     %s'%fname)

    processor_instance = btagMCeff.AnalysisProcessor(samplesdict)

    executor = processor.futures_executor(workers=nworkers)
    runner = processor.Runner(executor, schema=NanoAODSchema, chunksize=chunksize, maxchunks=nchunks)

    tstart = time.time()
    output = runner(flist, treename, processor_instance)
    dt = time.time() - tstart

    serialised_output = normalise_runner_output(output)
    total_bins, filled_bins = tuple_dict_stats(serialised_output if isinstance(serialised_output, dict) else {})
    fill_fraction = (100 * filled_bins / total_bins) if total_bins else 0.0
    print("Filled %.0f bins, nonzero bins: %1.1f %%" % (total_bins, fill_fraction))
    print("Processing time: %1.2f s with %i workers (%.2f s cpu overall)" % (dt, nworkers, dt*nworkers, ))

    # This is taken from the DM photon analysis...
    # Pickle is not very fast or memory efficient, will be replaced by something better soon
    #    with lz4f.open("pods/"+options.year+"/"+dataset+".pkl.gz", mode="xb", compression_level=5) as fout:
    if not outpath.endswith('/'): outpath += '/'
    if not os.path.isdir(outpath): os.system("mkdir -p %s"%outpath)
    print('Saving output in %s...'%(outpath + outname + ".pkl.gz"))
    with gzip.open(outpath + outname + ".pkl.gz", "wb") as fout:
        cloudpickle.dump(serialised_output, fout)
    print('Done!')

