"""Set the manifest version to the one a release was tagged with.

The release workflow runs this twice: on the tag, where the result goes into the
`tech.zip` asset, and on the default branch, where the result is committed. It
therefore writes the file the way the repository keeps it -- two-space indent,
keys in the order the file already has them, a trailing newline -- so that the
committed change is the version line and nothing else.
"""

import json
import os
import sys


def update_manifest():
    """Update the manifest file."""
    version = "0.0.0"
    for index, value in enumerate(sys.argv):
        if value in ["--version", "-V"]:
            version = sys.argv[index + 1]

    with open(
        f"{os.getcwd()}/custom_components/tech/manifest.json",
    ) as manifestfile:
        manifest = json.load(manifestfile)

    manifest["version"] = version

    with open(
        f"{os.getcwd()}/custom_components/tech/manifest.json",
        "w",
    ) as manifestfile:
        manifestfile.write(json.dumps(manifest, indent=2, sort_keys=False) + "\n")


update_manifest()
