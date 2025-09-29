info = {
    "npvs": {
        "regular": (100, 0, 100),
        "label": r"Number of reco primary vertices ",
    },
    "npvsGood": {
        "regular": (100, 0, 100),
        "label": r"Number of Good reco primary vertices ",
    },
    "invmass": {
        "regular": (30, 0, 150),
        "label": r"$m_{\ell\ell}$ (GeV) ",
    },
    "ptbl": {
        "regular": (40, 0, 1000),
        "variable": [0, 100, 200, 400],
        "label": r"$p_{T}^{b\mathrm{-}jet+\ell_{min(dR)}}$ (GeV) ",
    },
    "ptz": {
        "regular": (12, 0, 600),
        "variable": [0, 200, 300, 400, 500],
        "label": r"$p_{T}$ Z (GeV) ",
    },
    "njets": {
        "regular": (10, 0, 10),
        "variable_multi": {
            "2l": [4, 5, 6, 7],
            "3l": [2, 3, 4, 5],
            "4l": [2, 3, 4],
        },
        "label": r"Jet multiplicity ",
    },
    "nbtagsl": {
        "regular": (5, 0, 5),
        "label": r"Loose btag multiplicity "},
    "l0pt": {
        "regular": (25, 0, 250),
        "label": r"Leading lep raw $p_{T}$ (GeV) ",
    },
    "l0ptcorr": {
        "regular": (25, 0, 250),
        "label": r"Leading corrected lep $p_{T}$ (GeV) ",
    },
    "l0conept": {
        "regular": (25, 0, 250),
        "label": r"Leading lep cone-$p_{T}$ (GeV) ",
    },
    "l0eta": {
        "regular": (20, -2.5, 2.5),
        "label": r"Leading lep $\eta$ "
    },
    "l1pt": {
        "regular": (15, 0, 150),
        "label": r"Subleading lep raw $p_{T}$ (GeV) "
    },
    "l1ptcorr": {
        "regular": (15, 0, 150),
        "label": r"Subleading lep corrected $p_{T}$ (GeV) "
    },
    "l1conept": {
        "regular": (15, 0, 150),
        "label": r"Subleading lep cone-$p_{T}$ (GeV) "
    },
    "l1eta": {
        "regular": (20, -2.5, 2.5),
        "label": r"Subleading $\eta$ "
    },
    "j0pt": {
        "regular": (50, 0, 500),
        "label": r"Leading jet  $p_{T}$ (GeV) "
    },
    "b0pt": {
        "regular": (50, 0, 500),
        "label": r"Leading b jet  $p_{T}$ (GeV) "
    },
    "j0eta": {
        "regular": (30, -3, 3),
        "label": r"Leading jet  $\eta$ "
    },
    "ht": {
        "regular": (100, 0, 1000),
        "variable": [0, 300, 500, 800],
        "label": r"H$_{T}$ (GeV) ",
    },
    "met": {"regular": (40, 0, 400), "label": r"MET (GeV)"},
    "ljptsum": {
        "regular": (11, 0, 1100),
        "variable": [0, 400, 600, 1000],
        "label": r"S$_{T}$ (GeV) ",
    },
    "o0pt": {
        "regular": (10, 0, 500),
        "variable": [0, 100, 200, 400],
        "label": r"Leading l or b jet $p_{T}$ (GeV)",
    },
    "bl0pt": {
        "regular": (10, 0, 500),
        "variable": [0, 100, 200, 400],
        "label": r"Leading (b+l) $p_{T}$ (GeV) ",
    },
    "lj0pt": {
        "regular": (12, 0, 600),
        "variable": [0, 150, 250, 500],
        "label": r"Leading pt of pair from l+j collection (GeV) ",
    },
    "ptz_wtau": {
        "regular": (12, 0, 600),
        "variable": [0, 150, 250, 500],
        "label": r"pt of lepton hadronic tau pair (GeV) ",
    },
    "tau0pt": {
        "regular": (60, 0, 600),
        "variable": [0, 150, 250, 500],
        "label": r"pt of leading hadronic tau (GeV) ",
    },
    "lt": {
        "regular": (12, 0, 600),
        "variable": [0,150,250,500],
        "label": r"Scalar sum of met at leading leptons (GeV)",
    },

    "met_vs_ht": {
        "label": r"MET vs $H_{T}$",
        "axes": [
            {
                "name": "met",
                "regular": (40, 0, 400),
                "label": r"MET (GeV)",
            },
            {
                "name": "ht",
                "regular": (40, 0, 1000),
                "label": r"H$_{T}$ (GeV)",
            },
        ],
    },

    "l0_gen_pdgId": {
       "regular": (28, -1.5, 26.5),
       "label": r"pdgid of l0 genparticle",
    },
    "l1_gen_pdgId": {
       "regular": (28, -1.5, 26.5),
       "label": r"pdgid of l1 genparticle",
    },
    "l2_gen_pdgId": {
       "regular": (28, -1.5, 26.5),
       "label": r"pdgid of l2 genparticle",
    },
    "l0_genParent_pdgId": {
       "regular": (28, -1.5, 26.5),
       "label": r"pdgid of l0 genparent",
    },
    "l1_genParent_pdgId": {
       "regular": (28, -1.5, 26.5),
       "label": r"pdgid of l1 genparent",
    },
    "l2_genParent_pdgId": {
       "regular": (28, -1.5, 26.5),
       "label": r"pdgid of l2 genparent",
    },

    "b0l_hFlav": {
       "regular": (28, -1.5, 26.5),
       "label": r"Hadron Flavor of leading loose b jet",
   },
    "b0l_pFlav": {
       "regular": (28, -1.5, 26.5),
       "label": r"Parton Flavor of leading loose b jet",
   },
    "b0m_hFlav": {
       "regular": (28, -1.5, 26.5),
       "label": r"Hadron Flavor of leading medium b jet",
   },
    "b0m_pFlav": {
       "regular": (28, -1.5, 26.5),
       "label": r"Parton Flavor of leading medium b jet",
   },
    "b1l_hFlav": {
       "regular": (28, -1.5, 26.5),
       "label": r"Hadron Flavor of subleading loose b jet",
   },
    "b1l_pFlav": {
       "regular": (28, -1.5, 26.5),
       "label": r"Parton Flavor of subleading loose b jet",
   },
    "b1m_hFlav": {
       "regular": (28, -1.5, 26.5),
       "label": r"Hadron Flavor of subleading medium b jet",
   },
    "b1m_pFlav": {
       "regular": (28, -1.5, 26.5),
       "label": r"Parton Flavor of subleading medium b jet",
   },
    "b0l_genhFlav": {
       "regular": (28, -1.5, 26.5),
       "label": r"GenHadron Flavor of leading loose b jet",
   },
    "b0l_genpFlav": {
       "regular": (28, -1.5, 26.5),
       "label": r"GenParton Flavor of leading loose b jet",
   },
    "b0m_genhFlav": {
       "regular": (28, -1.5, 26.5),
       "label": r"GenHadron Flavor of leading medium b jet",
   },
    "b0m_genpFlav": {
       "regular": (28, -1.5, 26.5),
       "label": r"GenParton Flavor of leading medium b jet",
   },
    "b1l_genhFlav": {
       "regular": (28, -1.5, 26.5),
       "label": r"GenHadron Flavor of subleading loose b jet",
   },
    "b1l_genpFlav": {
       "regular": (28, -1.5, 26.5),
       "label": r"GenParton Flavor of subleading loose b jet",
   },
    "b1m_genhFlav": {
       "regular": (28, -1.5, 26.5),
       "label": r"GenHadron Flavor of subleading medium b jet",
   },
    "b1m_genpFlav": {
       "regular": (28, -1.5, 26.5),
       "label": r"GenParton Flavor of subleading medium b jet",
   }
}


def get_dense_axis_specs(hist_name: str) -> list[dict]:
    """Return the dense axis specifications for the histogram ``hist_name``.

    Each specification dictionary contains the keys ``name`` and ``label`` in
    addition to either ``regular`` or ``variable`` describing the binning.  If
    the histogram is one-dimensional the returned list has a single element,
    while multi-dimensional histograms contain one entry per axis.
    """

    if hist_name not in info:
        raise KeyError(f"Histogram '{hist_name}' is not defined in the axes configuration.")

    axis_info = info[hist_name]
    axis_specs = axis_info.get("axes")
    if axis_specs is None:
        axis_specs = [axis_info]

    resolved_specs = []
    for idx, spec in enumerate(axis_specs):
        spec_copy = spec.copy()
        if "name" not in spec_copy:
            spec_copy["name"] = hist_name if len(axis_specs) == 1 else f"{hist_name}_{idx}"
        if "label" not in spec_copy and "label" in axis_info:
            spec_copy["label"] = axis_info["label"]
        resolved_specs.append(spec_copy)

    return resolved_specs


def get_axis_names(hist_name: str) -> list[str]:
    """Return the ordered list of dense axis names for ``hist_name``."""

    return [spec["name"] for spec in get_dense_axis_specs(hist_name)]
