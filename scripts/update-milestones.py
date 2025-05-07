#!/usr/bin/env python3

import argparse
import os
import requests
import logging
from datetime import datetime

# GitHub API URL
GITHUB_API = "https://api.github.com"

# ANSI color codes
COLOR_RESET = "\033[0m"
COLOR_INFO = "\033[32m"  # Green
COLOR_WARNING = "\033[33m"  # Yellow
COLOR_ERROR = "\033[31m"  # Red
COLOR_DEBUG = "\033[36m"  # Cyan


class ColorFormatter(logging.Formatter):
    def __init__(self, no_color=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.no_color = no_color

    def format(self, record):
        if not self.no_color:
            color = ""
            if record.levelno == logging.INFO:
                color = COLOR_INFO
            elif record.levelno == logging.WARNING:
                color = COLOR_WARNING
            elif record.levelno == logging.ERROR:
                color = COLOR_ERROR
            elif record.levelno == logging.DEBUG:
                color = COLOR_DEBUG
            record.msg = f"{color}{record.msg}{COLOR_RESET}"
        return super().format(record)


def setup_logger(no_color):
    handler = logging.StreamHandler()
    handler.setFormatter(ColorFormatter(no_color=no_color, fmt="%(levelname)s: %(message)s"))
    logger = logging.getLogger(__name__)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


def get_headers():
    # Fetch GitHub token from environment variable
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise EnvironmentError("Please set GITHUB_TOKEN in your environment.")
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }


def create_or_edit_milestone(repo, args):
    url = f"{GITHUB_API}/repos/{repo}/milestones"
    payload = {"title": args.name}

    if args.due:
        payload["due_on"] = args.due
    if args.desc:
        payload["description"] = args.desc

    if args.verbose:
        logger.debug(f"[{repo}] Target URL: {url}")
        logger.debug(f"[{repo}] Initial payload: {payload}")

    if args.edit or args.close:
        # Fetch existing milestones
        milestones = requests.get(url, headers=get_headers()).json()
        if args.verbose:
            logger.debug(f"[{repo}] Retrieved {len(milestones)} existing milestones.")

        milestone = next((m for m in milestones if m["title"] == args.name), None)
        if not milestone:
            logger.warning(f"[{repo}] Milestone '{args.name}' not found.")
            return
        # Update URL to specific milestone
        url = f"{url}/{milestone['number']}"
        payload = {}
        if args.edit:
            if args.due: payload["due_on"] = args.due
            if args.desc: payload["description"] = args.desc
        if args.close:
            payload["state"] = "closed"

        if args.verbose:
            logger.debug(f"[{repo}] Updated URL for PATCH: {url}")
            logger.debug(f"[{repo}] Updated payload for PATCH: {payload}")

    if args.dry_run:
        logger.info(f"[DRY RUN] Would POST/PATCH {url} with {payload}")
    else:
        # Actually call GitHub API
        method = requests.patch if (args.edit or args.close) else requests.post
        r = method(url, headers=get_headers(), json=payload)
        if args.verbose:
            logger.debug(f"[{repo}] HTTP {r.status_code} response: {r.text}")
        if r.ok:
            logger.info(f"[{repo}] Success: {r.json()['title']}")
        else:
            logger.error(f"[{repo}] Failed: {r.text}")


def main():
    parser = argparse.ArgumentParser(description="Manage GitHub milestones across multiple repos.")
    parser.add_argument("--name", required=True, help="Milestone title")
    parser.add_argument("--repos", required=True, help="Comma-separated list of repositories (owner/repo)")
    parser.add_argument("--due", help="Due date (format: YYYYMMDDhhmmss)")
    parser.add_argument("--desc", help="Milestone description")
    parser.add_argument("--edit", action="store_true", help="Edit existing milestone")
    parser.add_argument("--close", action="store_true", help="Close milestone")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")

    args = parser.parse_args()

    global logger
    logger = setup_logger(no_color=args.no_color)

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    if args.due:
        try:
            # Parse and reformat due date to ISO 8601
            dt = datetime.strptime(args.due, "%Y%m%d%H%M%S")
            args.due = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            raise ValueError("Due date must be in format YYYYMMDDhhmmss, e.g., 20250630123000")

    for repo in args.repos.split(","):
        create_or_edit_milestone(repo.strip(), args)


if __name__ == "__main__":
    main()
