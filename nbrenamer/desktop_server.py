# ABOUTME: Startar den lokale FastAPI-backenden for Electron-skalet på ein gitt port.
# ABOUTME: Avsluttar seg sjølv når stdin fell bort, slik at ingen server-prosess blir liggjande att om Electron døyr brått.
from __future__ import annotations

import argparse
import os
import sys
import threading
from pathlib import Path

import uvicorn


def _add_extra_site_dir() -> None:
    """
    Legg til mappa med GPU-pakkar (torch med CUDA) om ho finst. Desktop-appen installerer
    dei på etterspurnad til ei brukar-skrivbar mappe utanfor programmappa, og sender stien
    i NBR_EXTRA_SITE. Ein `._pth`-fil gjer at PYTHONPATH blir ignorert, så stien må leggjast
    på sys.path her.
    """
    extra = os.environ.get("NBR_EXTRA_SITE")
    if extra and Path(extra).is_dir():
        sys.path.insert(0, extra)


def _shutdown_when_orphaned(server: uvicorn.Server) -> None:
    """
    Electron held stdin open så lenge appen lever. EOF (eller ein lesefeil) tyder at
    foreldreprosessen er borte, og då skal serveren stoppe òg. Utan dette ville ein
    hard avslutting av Electron late uvicorn stå att og halde porten.
    """
    stream = sys.stdin
    if stream is None:
        return
    try:
        while stream.readline():
            pass
    except Exception:  # noqa: BLE001
        pass
    server.should_exit = True


def main() -> None:
    parser = argparse.ArgumentParser(description="Lokal backend for NB foto-namngivar (desktop)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument(
        "--watch-stdin",
        action="store_true",
        help="Stopp serveren når stdin blir lukka (Electron brukar dette).",
    )
    args = parser.parse_args()

    _add_extra_site_dir()

    # Importen ligg her så argument-feil blir rapporterte før me dreg inn heile app-stacken.
    from .webapp import app

    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, log_level="info"))

    if args.watch_stdin:
        threading.Thread(target=_shutdown_when_orphaned, args=(server,), daemon=True).start()

    server.run()


if __name__ == "__main__":
    main()
