import requests
import os


def get_latest_tags(repo):
    url = f'https://api.github.com/repos/{repo}/tags'
    response = requests.get(url)
    response.raise_for_status()
    tags = response.json()
    return [tag['name'] for tag in tags]


def get_latest_dev_and_stable(tags):
    dev_tags = [tag for tag in tags if 'dev0' in tag]
    stable_tags = [tag for tag in tags if 'dev0' not in tag]

    latest_dev_tag = dev_tags[0] if dev_tags else None
    latest_stable_tag = stable_tags[0] if stable_tags else None

    return latest_dev_tag, latest_stable_tag


if __name__ == "__main__":
    repo = 'qiime2/qiime2'  # replace with your repository
    tags = get_latest_tags(repo)
    latest_dev_tag, latest_stable_tag = get_latest_dev_and_stable(tags)

    with open(os.getenv('GITHUB_ENV'), 'a') as env_file:
        if latest_dev_tag:
            env_file.write(f"LATEST_DEV_TAG={latest_dev_tag}\n")
        if latest_stable_tag:
            env_file.write(f"LATEST_STABLE_TAG={latest_stable_tag}\n")

    print(f"latest-dev-tag={latest_dev_tag}")
    print(f"latest-stable-tag={latest_stable_tag}")
