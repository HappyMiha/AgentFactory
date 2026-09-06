"""Run explicitly authorized qualification for a current approved local route."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from agent_factory.environment_model_probe import main

if __name__ == '__main__':
    raise SystemExit(main())
