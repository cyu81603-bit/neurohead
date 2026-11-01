"""Launch the accepted v3 controller, isolated from experimental motion code."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'stable_v3'))
from head_follow_panel import main
if __name__=='__main__':main()
