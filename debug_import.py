import os
import sys

# Add current directory to sys.path to ensure examples is discoverable
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

try:
    import examples.models

    print(f"Successfully imported examples.models from {examples.models.__file__}")
except ImportError as e:
    print(f"ImportError: {e}")
    print("sys.path:")
    for p in sys.path:
        print(f"  {p}")
