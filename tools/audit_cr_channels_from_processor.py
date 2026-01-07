#!/usr/bin/env python3
import json
from pathlib import Path

import yaml

CH_LST_PATH = Path("topeft/channels/ch_lst.json")
META_YAML_PATH = Path("topeft/params/cr_sr_plots_metadata.yml")


def _construct_cat_name(chan_str, njet_str=None, flav_str=None):
    """Match analysis_processor.construct_cat_name for channel labels."""

    nlep_str = chan_str.split("_")[0]
    chan_str = "_".join(chan_str.split("_")[1:])
    if chan_str == "":
        chan_str = None
    if njet_str is not None:
        njet_str = njet_str[-2:]
        if "j" not in njet_str:
            raise ValueError(
                f"Invalid njet string '{njet_str}' derived from '{njet_str}'"
            )

    ret_str = nlep_str
    for component in [flav_str, chan_str, njet_str]:
        if component is None:
            continue
        ret_str = "_".join([ret_str, component])
    return ret_str


def _jet_cat_to_key(jet_cat):
    jet_cat = str(jet_cat)
    if jet_cat.startswith("="):
        jettag = "exactly_"
    elif jet_cat.startswith("<"):
        jettag = "atmost_"
    elif jet_cat.startswith(">"):
        jettag = "atleast_"
    else:
        raise ValueError(f"jet_cat {jet_cat} misses =,<,>!")

    return jettag + jet_cat.replace("=", "").replace("<", "").replace(">", "") + "j"


def _iter_channel_defs(cat_def):
    lep_chan_lst = cat_def.get("lep_chan_lst", [])
    for entry in lep_chan_lst:
        if isinstance(entry, (list, tuple)):
            if entry:
                yield entry[0]
        else:
            yield entry


def build_channel_labels_from_ch_cfg(ch_cfg: dict) -> dict:
    """
    Reverse-engineered from topeft/analysis_processor.py, but implemented here.

    Returns a mapping:
        base_name -> set of full channel labels

    Only for CR definitions coming from:
      - CH_LST_CR
      - TAU_CH_LST_CR
    in ch_lst.json.

    The returned labels must match the histogram channel labels
    that CR_CHAN_DICT refers to, e.g.:
      - 3l_eee_CR_0j
      - 2los_ee_1tau_Ftau_2j
      - 1l_m_dy_tautau_CR_4j
    """

    out = {}

    for key in ("CH_LST_CR", "TAU_CH_LST_CR"):
        cat_block = ch_cfg.get(key) or {}
        for base_name, cat_def in cat_block.items():
            lep_flavs = list(cat_def.get("lep_flav_lst", []) or [None])
            jet_lst = cat_def.get("jet_lst", [])
            labels = out.setdefault(base_name, set())

            for jet_cat in jet_lst:
                jet_key = _jet_cat_to_key(jet_cat)
                for lep_chan in _iter_channel_defs(cat_def):
                    for lep_flav in lep_flavs:
                        label = _construct_cat_name(
                            lep_chan, njet_str=jet_key, flav_str=lep_flav
                        )
                        labels.add(label)

    return out


def main():
    with CH_LST_PATH.open() as f:
        ch_cfg = json.load(f)
    with META_YAML_PATH.open() as f:
        meta_cfg = yaml.safe_load(f)

    proc_map = build_channel_labels_from_ch_cfg(ch_cfg)

    proc_labels = sorted({lab for labs in proc_map.values() for lab in labs})
    yaml_labels = sorted(
        {lab for labels in meta_cfg["CR_CHAN_DICT"].values() for lab in labels}
    )

    proc_set = set(proc_labels)
    yaml_set = set(yaml_labels)

    only_in_processor = sorted(proc_set - yaml_set)
    only_in_yaml = sorted(yaml_set - proc_set)

    print(
        "=== CR channel labels that the PROCESSOR can build, but are MISSING in YAML CR_CHAN_DICT ==="
    )
    for lab in only_in_processor:
        print(f"  - {lab}")

    print(
        "\n=== YAML CR_CHAN_DICT labels that the PROCESSOR would NEVER produce ==="
    )
    for lab in only_in_yaml:
        print(f"  - {lab}")

    print("\n=== Debug: processor CR bases and their first few channels ===")
    for base, labs in sorted(proc_map.items()):
        labs_sorted = sorted(labs)
        preview = ", ".join(labs_sorted[:5])
        more = "" if len(labs_sorted) <= 5 else f" ... (+{len(labs_sorted)-5} more)"
        print(f"  {base}: {preview}{more}")


if __name__ == "__main__":
    main()
