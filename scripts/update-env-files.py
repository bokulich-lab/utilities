#!/usr/bin/env python3
"""
Generate new QIIME 2 environment files across one or more repositories.

For each provided repository path (relative or absolute):
  1) Identify the latest env file in environment-files/ matching:
     <plugin-name>-qiime2-<distribution>-<release>.yml
  2) Explicitly check out the base branch (default: main)
  3) Create (or switch to) a git branch named: env-file-<new_release>
  4) Create a new env file by copying the latest and updating its filename to
     contain <new_release>
  5) Replace all occurrences of the old release token inside the file with the
     new release token
  6) Commit the new file
  7) Optionally push the branch and open a PR (requires GitHub CLI: gh)

Usage examples:
  python update_env_files.py --new-release 2025.8 . ../q2-annotate
  python update_env_files.py --new-release 2025.8 --push --create-pr --base-branch main /path/to/repo

Notes:
- Uses only the Python standard library; PR creation relies on the GitHub CLI (gh) if requested.
- Expects targets to be git repositories with an environment-files/ directory.
- If the branch already exists, the script checks it out.
- If the destination env file already exists, that repo is skipped.
"""
from __future__ import annotations

import argparse
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


ENV_DIR_NAME = "environment-files"
FILENAME_SUFFIX = ".yml"
BRANCH_PREFIX = "env-file-"


@dataclass(frozen=True)
class EnvFileInfo:
    path: Path
    plugin_name: str
    distribution: str
    release: str  # e.g., "2025.7"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate new QIIME 2 env files in repos")
    p.add_argument(
        "repos",
        nargs="+",
        help="Paths to one or more repositories (relative or absolute)",
    )
    p.add_argument(
        "--new-release",
        required=True,
        help="New release token to use (e.g., 2025.8)",
    )
    p.add_argument(
        "--base-branch",
        default="main",
        help="Base branch to branch off of (default: main)",
    )
    p.add_argument(
        "--push",
        action="store_true",
        help="Push the created/updated branch to the primary remote (prefers 'upstream', otherwise 'origin') (default: False)",
    )
    p.add_argument(
        "--force-push",
        action="store_true",
        help="Use --force-with-lease when pushing the branch (default: False)",
    )
    p.add_argument(
        "--create-pr",
        action="store_true",
        help="Create a pull request on GitHub (requires 'gh') (default: False)",
    )
    p.add_argument(
        "--pr-org",
        default=None,
        help="Override PR target organization/owner (e.g., bokulich-lab). If set, PRs are created against <org>/<repo> instead of the fork's owner.",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    p.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (overrides --verbose when provided)",
    )
    return p.parse_args()


def setup_logging(verbose: bool, level_name: Optional[str]) -> None:
    if level_name:
        level = getattr(logging, level_name.upper(), logging.INFO)
    else:
        level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def ensure_git_repo(repo: Path) -> bool:
    try:
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def git_branch_exists(repo: Path, branch: str) -> bool:
    r = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", branch],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return r.returncode == 0


def git_checkout(repo: Path, ref: str) -> None:
    subprocess.run(["git", "-C", str(repo), "checkout", ref], check=True)


def git_checkout_new_branch_from_current(repo: Path, branch: str) -> None:
    subprocess.run(["git", "-C", str(repo), "checkout", "-b", branch], check=True)


def git_fetch(repo: Path, remote: str = "origin", refspec: Optional[str] = None) -> None:
    cmd = ["git", "-C", str(repo), "fetch", remote]
    if refspec:
        cmd.append(refspec)
    subprocess.run(cmd, check=True)


def git_pull_ff_only(repo: Path, remote: str, branch: str) -> None:
    subprocess.run(["git", "-C", str(repo), "pull", "--ff-only", remote, branch], check=True)


def git_push_u(repo: Path, remote: str, branch: str, force: bool = False) -> None:
    cmd = ["git", "-C", str(repo), "push"]
    if force:
        cmd.append("--force-with-lease")
    cmd += ["-u", remote, branch]
    subprocess.run(cmd, check=True)


def find_env_files(env_dir: Path) -> Iterable[Path]:
    # Pattern: anything-qiime2-<distribution>-<release>.yml
    yield from env_dir.glob("*-qiime2-*-*.yml")


def parse_env_filename(path: Path) -> Optional[EnvFileInfo]:
    name = path.name
    if not name.endswith(FILENAME_SUFFIX):
        return None

    # Split at "-qiime2-" to isolate plugin name safely (plugin name may contain dashes).
    parts = name[:-len(FILENAME_SUFFIX)].split("-qiime2-")
    if len(parts) != 2:
        return None
    plugin_name = parts[0]
    rest = parts[1]  # e.g., "tiny-2025.7"

    if "-" not in rest:
        return None
    distribution, release = rest.split("-", 1)

    # Validate release token like 2025.7 (digits '.' digits)
    if not re.fullmatch(r"\d+\.\d+", release):
        return None

    return EnvFileInfo(path=path, plugin_name=plugin_name, distribution=distribution, release=release)


def release_key(release: str) -> Tuple[int, int]:
    major, minor = release.split(".")
    return int(major), int(minor)


def select_latest_envs(env_dir: Path) -> List[EnvFileInfo]:
    """
    Return the env files belonging to the most recent release, grouped by (plugin, distribution).
    When both "moshpit" and "metagenome" distributions exist for a plugin, prefer "moshpit".
    """
    latest_release_key: Optional[Tuple[int, int]] = None
    envs_for_latest: Dict[Tuple[str, str], EnvFileInfo] = {}

    for p in find_env_files(env_dir):
        info = parse_env_filename(p)
        if info is None:
            continue
        release_tuple = release_key(info.release)
        if latest_release_key is None or release_tuple > latest_release_key:
            latest_release_key = release_tuple
            envs_for_latest = {(info.plugin_name, info.distribution): info}
            continue
        if release_tuple == latest_release_key:
            envs_for_latest[(info.plugin_name, info.distribution)] = info
            continue

    if not envs_for_latest:
        return []

    # Prefer moshpit over metagenome when both exist for the same plugin.
    filtered_envs: List[EnvFileInfo] = []
    for info in envs_for_latest.values():
        if info.distribution == "metagenome":
            moshpit_key = (info.plugin_name, "moshpit")
            if moshpit_key in envs_for_latest:
                continue
        filtered_envs.append(info)

    # Sort to keep deterministic ordering for downstream processing.
    return sorted(
        filtered_envs,
        key=lambda e: (e.plugin_name, e.distribution, release_key(e.release)),
    )


def write_new_env_file(latest: EnvFileInfo, new_release: str) -> Path:
    new_name = f"{latest.plugin_name}-qiime2-{latest.distribution}-{new_release}{FILENAME_SUFFIX}"
    new_path = latest.path.parent / new_name

    if new_path.exists():
        raise FileExistsError(f"Destination env file already exists: {new_path}")

    text = latest.path.read_text(encoding="utf-8")
    updated = text.replace(latest.release, new_release)

    new_path.write_text(updated, encoding="utf-8")
    logging.info("Wrote new env file: %s", new_path)
    return new_path


def git_add_and_commit(repo: Path, file_paths: Iterable[Path], new_release: str) -> None:
    rel_paths = [path.relative_to(repo) for path in file_paths]
    if not rel_paths:
        return

    add_cmd = ["git", "-C", str(repo), "add"] + [str(rel) for rel in rel_paths]
    subprocess.run(add_cmd, check=True)

    msg = f"Add {len(rel_paths)} env file(s) for QIIME 2 {new_release}"

    subprocess.run(["git", "-C", str(repo), "commit", "-m", msg], check=True)
    rel_display = ", ".join(str(rel) for rel in rel_paths)
    logging.info("Committed %s with message: %s", rel_display, msg)


def gh_available() -> bool:
    return shutil.which("gh") is not None


def gh_create_pr(repo: Path, repo_slug: str, base: str, head: str, title: str, body: str) -> Optional[str]:
    if not gh_available():
        logging.error("'gh' CLI not found; cannot create PR for %s", repo)
        return None
    try:
        # gh prints the URL on stdout on success
        res = subprocess.run(
            [
                "gh", "pr", "create",
                "--repo", repo_slug,  # explicit OWNER/REPO
                "--base", base,
                "--head", head,
                "--title", title,
                "--body", body,
            ],
            cwd=str(repo),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        url = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else None
        if url:
            logging.info("Created PR: %s", url)
        else:
            logging.warning("PR created but no URL captured for %s", repo)
        return url
    except subprocess.CalledProcessError as e:
        logging.error("Failed to create PR in %s: %s", repo, e.stderr.strip() if e.stderr else e)
        return None


def process_repo(repo: Path, new_release: str, base_branch: str, push: bool, create_pr: bool, pr_org: Optional[str], force_push: bool) -> Optional[str]:
    if not repo.exists() or not repo.is_dir():
        logging.warning("[SKIP] Not a directory: %s", repo)
        return None
    if not ensure_git_repo(repo):
        logging.warning("[SKIP] Not a git repository: %s", repo)
        return None

    env_dir = repo / ENV_DIR_NAME
    if not env_dir.exists() or not env_dir.is_dir():
        logging.warning("[SKIP] Missing '%s/' in %s", ENV_DIR_NAME, repo)
        return None

    latest_envs = select_latest_envs(env_dir)
    if not latest_envs:
        logging.warning("[SKIP] No matching env files in %s", env_dir)
        return None

    planned_latest: List[EnvFileInfo] = []
    already_existing: List[Path] = []
    for latest in latest_envs:
        new_name = f"{latest.plugin_name}-qiime2-{latest.distribution}-{new_release}{FILENAME_SUFFIX}"
        new_path = latest.path.parent / new_name
        if new_path.exists():
            already_existing.append(new_path)
            continue
        planned_latest.append(latest)

    if already_existing:
        for path in already_existing:
            logging.info("[SKIP] Destination env file already exists: %s", path)

    if not planned_latest:
        logging.info("[SKIP] All env files for release %s already exist in %s", new_release, env_dir)
        return None

    branch = f"{BRANCH_PREFIX}{new_release}"

    # Determine primary remote and its GitHub slug (OWNER/REPO)
    remote = get_primary_remote(repo)
    if remote is None:
        logging.error("No git remotes configured in %s", repo)
        return None
    remote_url = get_remote_url(repo, remote)
    repo_slug = github_slug_from_url(remote_url) if remote_url else None
    if create_pr and not repo_slug:
        logging.error("Cannot create PR: remote URL is not a recognized GitHub URL (%s)", remote_url)
        return None

    # Determine PR target slug and head spec
    fork_owner = None
    repo_name = None
    if repo_slug:
        parts = repo_slug.split("/", 1)
        if len(parts) == 2:
            fork_owner, repo_name = parts[0], parts[1]
    target_slug = repo_slug
    if create_pr and pr_org:
        if not repo_name:
            logging.error("Cannot determine repository name from slug '%s' for PR target override", repo_slug)
            return None
        target_slug = f"{pr_org}/{repo_name}"

    head_spec = branch if not fork_owner else f"{fork_owner}:{branch}"

    # Ensure we are on the base branch before creating/updating the feature branch.
    try:
        git_fetch(repo, remote, base_branch)
    except subprocess.CalledProcessError:
        # fetch may fail if refspec doesn't exist remotely; continue to checkout base
        pass
    try:
        git_checkout(repo, base_branch)
    except subprocess.CalledProcessError as e:
        logging.error("Failed to checkout base branch '%s' in %s: %s", base_branch, repo, e)
        return None
    try:
        git_pull_ff_only(repo, remote, base_branch)
    except subprocess.CalledProcessError:
        # If ff-only fails (e.g., no upstream), ignore
        pass

    pr_url: Optional[str] = None
    try:
        # Create or switch to the feature branch
        try:
            if git_branch_exists(repo, branch):
                logging.info("Branch '%s' already exists in %s; checking it out...", branch, repo)
                git_checkout(repo, branch)
            else:
                logging.info("Creating and checking out new branch '%s' in %s...", branch, repo)
                git_checkout_new_branch_from_current(repo, branch)
        except subprocess.CalledProcessError as e:
            logging.error("Failed to create/checkout branch in %s: %s", repo, e)
            return None

        # Create the new env files
        new_env_paths: List[Path] = []
        for latest in planned_latest:
            try:
                new_env_paths.append(write_new_env_file(latest, new_release))
            except FileExistsError as e:
                logging.warning("[SKIP] %s", e)

        if not new_env_paths:
            logging.info("[SKIP] No new env files were generated for %s", repo)
            return None

        # Commit the files
        try:
            git_add_and_commit(repo, new_env_paths, new_release)
        except subprocess.CalledProcessError as e:
            logging.error("Failed to commit in %s: %s", repo, e)
            return None

        # Decide whether to push
        if push or create_pr:
            try:
                git_push_u(repo, remote, branch, force=force_push)
                logging.info("Pushed%s branch '%s' to %s for %s", " (force)" if force_push else "", branch, remote, repo)
            except subprocess.CalledProcessError as e:
                logging.error("Failed to push branch in %s: %s", repo, e)
                return None

        # Optionally create PR
        if create_pr:
            title = f"MAINT: add env file for QIIME 2 {new_release}"
            body = (
                f"This PR adds a new environment file for QIIME 2 {new_release}.\n\n"
                f"Generated from the latest env file in '{ENV_DIR_NAME}/' by updating the release token."
            )
            pr_url = gh_create_pr(repo, target_slug, base_branch, head_spec, title, body)

        created_names = ", ".join(path.name for path in new_env_paths)
        logging.info("[OK] Updated %s -> [%s] on branch %s", repo, created_names, branch)
        return pr_url
    finally:
        # Always switch back to the base branch at the end
        try:
            git_checkout(repo, base_branch)
            logging.info("Switched back to base branch '%s' in %s", base_branch, repo)
        except subprocess.CalledProcessError as e:
            logging.warning("Failed to switch back to base branch '%s' in %s: %s", base_branch, repo, e)


def get_primary_remote(repo: Path) -> Optional[str]:
    try:
        res = subprocess.run(
            ["git", "-C", str(repo), "remote"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        remotes = [r.strip() for r in res.stdout.splitlines() if r.strip()]
        if not remotes:
            return None
        if "upstream" in remotes:
            return "upstream"
        if "origin" in remotes:
            return "origin"
        return remotes[0]
    except subprocess.CalledProcessError:
        return None


def get_remote_url(repo: Path, remote: str) -> Optional[str]:
    try:
        res = subprocess.run(
            ["git", "-C", str(repo), "config", f"remote.{remote}.url"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return res.stdout.strip() or None
    except subprocess.CalledProcessError:
        return None


def github_slug_from_url(url: str) -> Optional[str]:
    # Support typical formats:
    #  - git@github.com:owner/repo.git
    #  - https://github.com/owner/repo.git
    #  - https://github.com/owner/repo
    if not url:
        return None
    url = url.strip()
    owner_repo: Optional[str] = None
    if url.startswith("git@github.com:"):
        owner_repo = url.split(":", 1)[1]
    elif "github.com/" in url:
        owner_repo = url.split("github.com/", 1)[1]
    if not owner_repo:
        return None
    if owner_repo.endswith(".git"):
        owner_repo = owner_repo[:-4]
    # In case there are trailing paths or query params (unlikely)
    owner_repo = owner_repo.split("/")
    if len(owner_repo) < 2:
        return None
    slug = "/".join(owner_repo[:2])
    return slug


def main() -> None:
    args = parse_args()
    setup_logging(args.verbose, args.log_level)

    new_release = args.new_release.strip()

    # Basic validation for new_release format
    if not re.fullmatch(r"\d+\.\d+", new_release):
        raise SystemExit("--new-release must look like 'YYYY.M' (e.g., 2025.8)")

    repos = [Path(p).expanduser().resolve() for p in args.repos]

    pr_links: List[str] = []
    for repo in repos:
        pr_url = process_repo(
            repo,
            new_release,
            base_branch=args.base_branch,
            push=args.push,
            create_pr=args.create_pr,
            pr_org=args.pr_org,
            force_push=args.force_push,
        )
        if pr_url:
            pr_links.append(pr_url)

    if args.create_pr:
        if pr_links:
            logging.info("Summary of created PRs:")
            for url in pr_links:
                logging.info("  %s", url)
        else:
            logging.info("No PRs were created.")


if __name__ == "__main__":
    main()
