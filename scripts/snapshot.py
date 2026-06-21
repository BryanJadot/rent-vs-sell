#!/usr/bin/env python3
"""Regenerate the committed golden snapshot(s) the test suite diffs against.

Run deliberately (`make snapshot`) AFTER you've verified a numeric change is correct.
The snapshot test then turns any *unintended* future change into a visible diff.
"""

import json
import os

from assumptions import load_property
from model import Model

GOLDEN_DIR = "tests/golden"
# (property TOML, golden filename)
SNAPSHOTS = [
    ("properties/harold-ave.toml", "harold-ave.json"),
    ("properties/test-fixture.toml", "test-fixture.json"),
]


def main():
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    for prop_path, name in SNAPSHOTS:
        data = Model(load_property(prop_path)).compute()
        with open(os.path.join(GOLDEN_DIR, name), "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        print(f"[snapshot] {prop_path} -> {GOLDEN_DIR}/{name}")


if __name__ == "__main__":
    main()
