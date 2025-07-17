#!/usr/bin/env python

import argparse
import re
import requests
import uuid

import yaml


def fetch_seed_environment(version_tag, distro):
    """
    Fetch the seed-environment-conda.yml file from GitHub and extract the dependencies.

    Args:
        version_tag (str): The version tag (e.g., "2023.5.0")
        distro (str): The distribution type (e.g., "tiny", "moshpit")

    Returns:
        dict: A dictionary mapping package names to their versions
    """
    # Extract channel version from the tag (e.g., 2023.5 from 2023.5.0)
    channel_version = '.'.join(version_tag.split('.')[:2])
    url = f"https://raw.githubusercontent.com/qiime2/distributions/dev/{channel_version}/{distro}/passed/seed-environment-conda.yml"

    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for HTTP errors

        # Parse the YAML content
        seed_env = yaml.safe_load(response.text)

        # Extract dependencies and their versions
        dependencies = {}
        for dep in seed_env.get('dependencies', []):
            if isinstance(dep, str):  # Skip nested dependencies (like pip packages)
                # Extract package name and version
                parts = dep.split("=")
                if len(parts) >= 1:
                    package_name = parts[0]
                    version = parts[1]

                    # Remove the part following a plus symbol (inclusive) from the version
                    # if '+' in version:
                    #     version = version.split('+')[0]

                    dependencies[package_name] = version
        print(dependencies)
        return dependencies
    except (requests.RequestException, yaml.YAMLError) as e:
        print(f"Error fetching or parsing seed environment: {e}")
        return {}


def preprocess_yaml_with_jinja(content):
    """
    Preprocess YAML content by replacing Jinja expressions with placeholders.
    This allows the YAML parser to work with files containing Jinja expressions
    without having to fall back to line-by-line processing.

    Args:
        content (str): The YAML content with Jinja expressions

    Returns:
        tuple: (processed_content, placeholders_map)
            - processed_content (str): The YAML content with placeholders
            - placeholders_map (dict): A mapping of placeholders to original Jinja expressions
    """
    placeholders_map = {}

    # Find all Jinja expressions and replace them with placeholders
    def replace_jinja(match):
        jinja_expr = match.group(0)
        placeholder = f"__JINJA_PLACEHOLDER_{uuid.uuid4().hex}__"
        placeholders_map[placeholder] = jinja_expr
        return placeholder

    # Replace {{ ... }} expressions
    processed_content = re.sub(r'{{[^}]+}}', replace_jinja, content)

    return processed_content, placeholders_map


def process_placeholder(placeholder, seed_dependencies):
    """
    Process a placeholder by replacing underscores with hyphens and looking up the version.

    Args:
        placeholder (str): The placeholder name (without {{ }})
        seed_dependencies (dict): A dictionary mapping package names to their versions

    Returns:
        str: The version string to use for the placeholder
    """
    # Replace underscores with hyphens
    package_name = placeholder.replace('_', '-')

    # Look up the version in the seed dependencies
    if package_name in seed_dependencies and seed_dependencies[package_name]:
        return seed_dependencies[package_name]
    else:
        print(f"Warning: Version for {package_name} not found in seed environment")
        return ">=0.0.0"  # Default version if not found


def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Extract dependencies from a conda recipe.')
    parser.add_argument('--distro', required=True, help='Distribution type (e.g., "tiny", "moshpit")')
    parser.add_argument('--version-tag', required=True, help='Version tag (e.g., "2023.5.0")')
    parser.add_argument('--repositories-yaml', required=True, help='Path to the repositories YAML file')
    parser.add_argument('--conda-recipe', default="conda-recipe/meta.yaml", help='Path to the conda recipe template file (default: conda-recipe/meta.yaml)')

    # Parse arguments
    args = parser.parse_args()

    distro = args.distro
    version_tag = args.version_tag
    repositories_yaml = args.repositories_yaml
    conda_recipe = args.conda_recipe

    # Fetch seed environment dependencies
    seed_dependencies = fetch_seed_environment(version_tag, distro)

    # Define the paths to env output file, and repo-urls file
    output_file = "environment.yml"
    repo_urls_file = "repo-urls.txt"

    # Extract channel version from the tag (e.g., 2023.5 from 2023.5.0)
    channel_version = '.'.join(version_tag.split('.')[:2])

    # Extract dependencies from the meta.yaml file
    dependencies = []
    qiime_dependencies = []

    # Read and parse the conda recipe
    with open(conda_recipe, 'r') as f:
        # Read the file as text first to handle Jinja2 templates
        content = f.read()

        # Parse the YAML content
        try:
            # Preprocess the YAML content to handle Jinja expressions
            processed_content, placeholders_map = preprocess_yaml_with_jinja(content)

            # Try to parse the preprocessed content as YAML
            recipe = yaml.safe_load(processed_content)

            # Restore Jinja expressions in the parsed data
            def restore_jinja_expressions(obj):
                if isinstance(obj, str):
                    for placeholder, jinja_expr in placeholders_map.items():
                        if placeholder in obj:
                            obj = obj.replace(placeholder, jinja_expr)
                    return obj
                elif isinstance(obj, list):
                    return [restore_jinja_expressions(item) for item in obj]
                elif isinstance(obj, dict):
                    return {k: restore_jinja_expressions(v) for k, v in obj.items()}
                else:
                    return obj

            recipe = restore_jinja_expressions(recipe)

            # Extract dependencies from the run section
            if 'requirements' in recipe and 'run' in recipe['requirements']:
                run_deps = recipe['requirements']['run']

                for dep in run_deps:
                    # Replace Jinja2 templates
                    # Find all placeholders in the format {{ placeholder }}
                    placeholders = re.findall(r'{{ ([^}]+) }}', dep)
                    for placeholder in placeholders:
                        version = process_placeholder(placeholder, seed_dependencies)
                        # Check if there's already an operator before the placeholder
                        operator_match = re.search(r'([=<>]+)\s*{{ ' + re.escape(placeholder) + r' }}', dep)
                        if operator_match:
                            # If there's already an operator, use it
                            operator = operator_match.group(1)
                            dep = re.sub(r'[=<>]+\s*{{ ' + re.escape(placeholder) + r' }}', f"{operator}{version}", dep)
                        else:
                            # Otherwise, add the >= operator
                            dep = re.sub(r' {{ ' + re.escape(placeholder) + r' }}', f">={version}", dep)

                    dependencies.append(dep)

                    # Check if the dependency is a QIIME2 package
                    if re.match(r'^(q2|qiime2)', dep.strip().split()[0]):
                        package_name = dep.strip().split()[0]
                        qiime_dependencies.append(package_name)
        except yaml.YAMLError as e:
            # Provide a meaningful error message for YAML parsing issues
            error_message = f"Error parsing YAML in conda recipe '{conda_recipe}':\n{e}\n"
            error_message += "Please check the YAML syntax in the conda recipe file."
            raise RuntimeError(error_message)

    # Only add q2cli if it's not already present in dependencies
    q2cli_present = any("q2cli" in dep for dep in dependencies)
    if not q2cli_present:
        dependencies.append("  - q2cli")

    # Create a dictionary to hold the YAML data
    yaml_data = {
        'name': 'conda-env',
        'channels': [
            f'https://packages.qiime2.org/qiime2/{channel_version}/{distro}/passed/',
            'conda-forge',
            'bioconda',
            'rischv',
            'defaults'
        ],
        'dependencies': []
    }

    # Process dependencies to ensure they're in the correct format
    for dep in dependencies:
        # Remove any existing indentation and dash
        dep = dep.strip()
        if dep.startswith('-'):
            dep = dep[1:].strip()
        yaml_data['dependencies'].append(dep)

    # Write the YAML data to the output file
    with open(output_file, 'w') as f:
        yaml.dump(yaml_data, f, default_flow_style=False, sort_keys=False)

    # Read the repo YAML file and extract URLs based on the qiime_dependencies
    repo_urls = []

    with open(repositories_yaml, 'r') as f:
        repos_data = yaml.safe_load(f)

        for package_name in qiime_dependencies:
            if package_name:
                for repo in repos_data.get('repositories', []):
                    if repo.get('name') == package_name:
                        url = repo.get('url')
                        if url:
                            repo_urls.append(f"git+{url}.git")

    # Write the repo URLs to the repo-urls.txt file
    with open(repo_urls_file, 'w') as f:
        f.write('\n'.join(repo_urls) + '\n')

if __name__ == "__main__":
    main()
