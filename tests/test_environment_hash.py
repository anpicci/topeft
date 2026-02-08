from pathlib import Path
import hashlib

EXPECTED_SHA256 = "5d47d3dff9581d78f1c7024e3ed9985e95ab6d7f5149eabbe970426e2edac1a6"


def test_environment_spec_matches_ttbareft():
    """Ensure the local Conda spec mirrors ttbarEFT's coffea2025 baseline."""

    env_path = Path(__file__).resolve().parents[1] / "environment.yml"
    digest = hashlib.sha256(env_path.read_bytes()).hexdigest()

    assert (
        digest == EXPECTED_SHA256
    ), (
        "environment.yml drifted from the ttbarEFT coffea2025 specification. "
        "Update the file and refresh EXPECTED_SHA256 to match upstream. "
        f"Observed {digest}."
    )
