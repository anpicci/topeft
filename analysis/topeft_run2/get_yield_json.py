"""Extract category yields from histogram pickles and save JSON outputs.

Purpose:
- Read tuple-keyed histogram pickles and emit year/category yield summaries for
  regression checks and datacard preparation.

Inputs/outputs:
- Reads one histogram pickle (default ``histos/plotsTopEFT.pkl.gz``).
- Writes a JSON yield file (timestamped by default) and optional table output.

Side effects:
- Creates JSON files in the current working directory.

How to run:
- ``python analysis/topeft_run2/get_yield_json.py --help``
- ``python analysis/topeft_run2/get_yield_json.py -f histos/plotsTopEFT.pkl.gz -y 2018``
"""

import argparse
import json
import datetime

import topcoffea

from topeft.modules.yield_tools import YieldTools

mlt = topcoffea.modules.MakeLatexTable
utils = topcoffea.modules.utils

def main():
    from topeft.modules.logging_config import configure_topeft_logging
    configure_topeft_logging("INFO")


    yt = YieldTools()

    timestamp_tag = datetime.datetime.now().strftime('%Y%m%d_%H%M')

    # Set up the command line parser
    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--pkl-file-path", default="histos/plotsTopEFT.pkl.gz", help = "The path to the pkl file")
    parser.add_argument("-y", "--year", default=None, help = "The year of the sample")
    parser.add_argument("-t", "--tag", default="Sample", help = "A string to describe the pkl file")
    parser.add_argument("-n", "--json-name", default="yields", help = "Name of the json file to save")
    parser.add_argument("-q", "--quiet", action="store_true", help = "Do not print out anything")
    parser.add_argument("-l", "--by-lep-flavor", action="store_true", help = "Do not sum over the lep flavor categories, cannot use unless input file is split by lep flavors")
    parser.add_argument("-j", "--by-njets", action="store_true", help = "Do not sum over the njets categories")
    args = parser.parse_args()

    # Get the histograms, check if split into lep flavors
    hin_dict = utils.get_hist_from_pkl(args.pkl_file_path,allow_empty=False)
    if not yt.is_split_by_lepflav(hin_dict) and args.by_lep_flavor:
        raise Exception("Cannot specify --by-lep-flavor option, the yields file is not split by lepton flavor")

    # Put the yields into a dict
    yld_dict = yt.get_yld_dict(hin_dict,args.year,njets=args.by_njets,lepflav=args.by_lep_flavor)

    # Print info about the file
    if not args.quiet:
        yt.print_hist_info(args.pkl_file_path)
        utils.print_yld_dicts(yld_dict,args.tag)
        if not args.by_lep_flavor and not args.by_njets:
            mlt.print_latex_yield_table(yld_dict,key_order=yt.PROC_MAP.keys(),subkey_order=yt.CAT_LST,tag=args.tag,print_begin_info=True,print_end_info=True)
        else:
            mlt.print_latex_yield_table(yld_dict,tag=args.tag,print_begin_info=True,print_end_info=True,column_variable="keys")

    # Save to a json
    out_json_name = args.json_name
    if args.json_name == parser.get_default("json_name"):
        out_json_name = out_json_name + "_" + timestamp_tag
    with open(out_json_name+".json", "w") as out_file:
        json.dump(yld_dict, out_file, indent=4)
    print(f"Saved json file: {out_json_name}.json\n")

if __name__ == "__main__":
    main()
