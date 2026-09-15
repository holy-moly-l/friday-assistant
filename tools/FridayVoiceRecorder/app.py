from src import friday_voice_recorder as fvr
from src.runtime_fixes import install_hotfixes

install_hotfixes(fvr)

if __name__ == "__main__":
    fvr.main()
