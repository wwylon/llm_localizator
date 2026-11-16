"""Module entrypoint for ``python -m llm_localizator``."""

from .cli.main import main


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
