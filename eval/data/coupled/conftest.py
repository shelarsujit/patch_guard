import sys
from pathlib import Path

# The programs under test live in python_programs/ and import each other by
# bare module name, exactly as the QuixBugs tree does.
sys.path.insert(0, str(Path(__file__).parent / "python_programs"))
