#!/usr/bin/env python

import sys
import traceback

import uproot


def main() -> None:
    from topeft.modules.logging_config import configure_topeft_logging
    configure_topeft_logging("INFO")

    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        # Default to one of the failing files you pasted
        path = (
            "root://skynet013.crc.nd.edu//store/user/awightma/skims/mc/"
            "new-lepMVA-v2/private_UL/FullRun2/v2/UL17_tHq_b1/output_773.root"
        )

    print(f"Trying to open:\n  {path}\n")

    try:
        with uproot.open(path) as f:
            print("✅ File opened successfully.\n")

            print("Top-level keys:")
            for key in f.keys():
                print(f"  {key}")
            print()

            # Try to find an Events tree
            events_key = None
            for key in f.keys():
                if "Events" in key:
                    events_key = key
                    break

            if events_key is not None:
                tree = f[events_key]
                print(f"Using tree: {events_key}")
                print(f"Number of entries: {tree.num_entries}")
            else:
                print("⚠️ No key containing 'Events' found.")
    except Exception:
        print("❌ ERROR: failed to open or inspect the file with uproot.\n")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
