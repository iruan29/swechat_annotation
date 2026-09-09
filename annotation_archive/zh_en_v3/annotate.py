#!/usr/bin/env python3
"""Works both in the source repo and at the root of a portable release."""
from pathlib import Path
import sys

here = Path(__file__).resolve().parent
root = here if (here / 'assignments.json').exists() else here.parent
sys.path.insert(0, str(root / 'src'))
from swe_chat_analysis.human_team import main

if __name__ == '__main__':
    main(root if (root / 'assignments.json').exists() else root / 'annotation_release')
