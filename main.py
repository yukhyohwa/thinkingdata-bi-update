import argparse
import re
from pathlib import Path
from urllib.parse import urlparse

from src.config import settings
from src.core.engines.ta_engine import ThinkingDataEngine
from src.utils.logger import logger


# A block comment commonly puts `URL:` on its own line, without a leading `*`.
URL_HEADER = re.compile(r"^\s*(?:(?:--|/\*|\*)\s*)?URL\s*:\s*(https?://\S+)", re.IGNORECASE)
PROJECT_DIR = Path(__file__).resolve().parent
INPUT_DIR = PROJECT_DIR / "input"


def read_sql_task(sql_file: str) -> tuple[str, str]:
    requested = Path(sql_file).expanduser()
    if requested.is_absolute():
        candidates = [requested]
    elif requested.parent == Path("."):
        # File names are resolved from input/ first, so report SQL stays separate from app code.
        candidates = [INPUT_DIR / requested, PROJECT_DIR / requested]
    else:
        candidates = [PROJECT_DIR / requested]
    path = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
    if path is None:
        searched = ", ".join(str(candidate) for candidate in candidates)
        raise FileNotFoundError(f"SQL file not found. Searched: {searched}")
    sql = path.read_text(encoding="utf-8-sig")
    # The URL must be in the opening comment block, before the first SQL statement.
    for line in sql.splitlines()[:80]:
        match = URL_HEADER.match(line)
        if match:
            return sql, match.group(1).rstrip("*/;,)")
    raise ValueError("No SQL IDE URL found in the opening comments. Add: -- URL: https://...")


def build_engine(sql_url: str) -> ThinkingDataEngine:
    region = settings.region_for_sql_url(sql_url)
    config = settings.TA_CREDENTIALS[region]
    if not config.user or not config.password:
        raise ValueError(f"Missing ThinkingData credentials for {region}; fill TA_USER/TA_PASS in .env.")
    logger.info("Target: %s (%s ThinkingData)", urlparse(sql_url).hostname, "China" if region == "china" else "international")
    return ThinkingDataEngine(config, sql_url, settings.session_dir_for(region))


def main() -> None:
    parser = argparse.ArgumentParser(description="Update a ThinkingData report from a SQL file.")
    parser.add_argument("sql_file", nargs="?", help="SQL file name in input/, or a relative/absolute SQL path")
    parser.add_argument("--login", metavar="SQL_FILE", help="Log in and save a session for the SQL file's target instance")
    parser.add_argument("--show", action="store_true", help="Show the browser window while running")
    parser.add_argument("--inspect", metavar="OUTPUT_DIR", help="Read saved SQL and page state in background without saving")
    parser.add_argument("--panel-url", help="Optionally inspect a known parent dashboard after reading saved SQL")
    args = parser.parse_args()

    file_name = args.login or args.sql_file
    if not file_name:
        parser.error("provide a SQL file, e.g. python main.py report.sql")
    sql, sql_url = read_sql_task(file_name)
    engine = build_engine(sql_url)
    if args.inspect:
        engine.inspect_report(args.inspect, panel_url=args.panel_url)
        return
    if args.login:
        engine.login()
        return
    engine.save_report(sql, show_window=args.show)


if __name__ == "__main__":
    main()
