"""ComfyUI-FileManaty: read-only file viewer extension.

ComfyUI imports this package during custom_nodes discovery. Importing
filemanaty.api as a side effect attaches HTTP routes to
PromptServer.instance.app at startup.
"""
import os
import sys

# ComfyUI loads this __init__.py via importlib.util.spec_from_file_location,
# which does NOT add the custom-node directory to sys.path.  We add it here so
# that `import filemanaty.*` resolves correctly whether the package is installed
# as an editable install or loaded via the bind-mount / Docker setup.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

# Side-effect import: registers /filemanaty/api/v1/* routes when ComfyUI loads us.
import filemanaty.api  # noqa: F401, E402

WEB_DIRECTORY = "./web"

# ComfyUI looks for these even when empty
NODE_CLASS_MAPPINGS: dict = {}
NODE_DISPLAY_NAME_MAPPINGS: dict = {}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
