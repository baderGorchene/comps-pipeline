import logging

from rich.logging import RichHandler


def setup_logging(level: str = "INFO") -> None:
    """Console logging via rich. Full LLM payloads are only ever logged at DEBUG."""
    logging.basicConfig(
        level=level.upper(),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
        force=True,
    )
