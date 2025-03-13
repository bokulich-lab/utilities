import requests
import os
import sys


def get_latest_tags(repo):
    url = f'https://api.github.com/repos/{repo}/tags'
    response = requests.get(url)
    response.raise_for_status()
    tags = response.json()
    return [tag['name'] for tag in tags]


def get_latest_dev_and_stable(tags):
    dev_tags = [tag for tag in tags if 'dev' in tag]
    stable_tags = [tag for tag in tags if 'dev' not in tag]

    latest_dev_tag = dev_tags[0] if dev_tags else None
    latest_stable_tag = stable_tags[0] if stable_tags else None

    return latest_dev_tag, latest_stable_tag


def get_previous_dev_and_stable(tags):
    dev_tags = [tag for tag in tags if 'dev' in tag]
    stable_tags = [tag for tag in tags if 'dev' not in tag]

    previous_dev_tag = dev_tags[1] if len(dev_tags) > 1 else None
    previous_stable_tag = stable_tags[1] if len(stable_tags) > 1 else None

    return previous_dev_tag, previous_stable_tag


if __name__ == "__main__":
    # Use the repository name from the command-line argument if provided
    repo = sys.argv[1] if len(sys.argv) > 1 else 'qiime2/qiime2'
    tags = get_latest_tags(repo)
    latest_dev_tag, latest_stable_tag = get_latest_dev_and_stable(tags)
    previous_dev_tag, previous_stable_tag = get_previous_dev_and_stable(tags)

    with open(os.getenv('GITHUB_ENV'), 'a') as env_file:
        if latest_dev_tag:
            env_file.write(f"LATEST_DEV_TAG={latest_dev_tag}\n")
        if latest_stable_tag:
            env_file.write(f"LATEST_STABLE_TAG={latest_stable_tag}\n")
        if previous_dev_tag:
            env_file.write(f"PREVIOUS_DEV_TAG={previous_dev_tag}\n")
        if previous_stable_tag:
            env_file.write(f"PREVIOUS_STABLE_TAG={previous_stable_tag}\n")

    print(f"latest-dev-tag={latest_dev_tag}")
    print(f"latest-stable-tag={latest_stable_tag}")
    print(f"previous-dev-tag={previous_dev_tag}")
    print(f"previous-stable-tag={previous_stable_tag}")
