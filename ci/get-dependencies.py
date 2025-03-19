#!/usr/bin/env python

import argparse
import re

import yaml


def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Extract dependencies from a conda recipe.')
    parser.add_argument('--distro', required=True, help='Distribution type (e.g., "staging", "main")')
    parser.add_argument('--version-tag', required=True, help='Version tag (e.g., "2023.5.0")')
    parser.add_argument('--repositories-yaml', required=True, help='Path to the repositories YAML file')
    parser.add_argument('--conda-recipe', default="conda-recipe/meta.yaml", help='Path to the conda recipe template file (default: conda-recipe/meta.yaml)')

    # Parse arguments
    args = parser.parse_args()

    distro = args.distro
    version_tag = args.version_tag
    repositories_yaml = args.repositories_yaml
    conda_recipe = args.conda_recipe

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
            # Try to parse as YAML directly
            recipe = yaml.safe_load(content)

            # Extract dependencies from the run section
            if 'requirements' in recipe and 'run' in recipe['requirements']:
                run_deps = recipe['requirements']['run']

                for dep in run_deps:
                    # Replace Jinja2 templates
                    if "{{ qiime2_epoch }}" in dep:
                        dep = re.sub(r' {{ qiime2_epoch }}.*', f'=={version_tag}*', dep)
                    if "{{ bowtie2 }}" in dep:
                        dep = re.sub(r' {{ bowtie2 }}', '==2.5.1', dep)
                    if "{{ pysam }}" in line:
                        line = re.sub(r' {{ pysam }}', '==0.22.1', line)
                    if "{{ spades }}" in line:
                        line = re.sub(r' {{ spades }}', '==4.0.0', line)

                    dependencies.append(dep)

                    # Check if the dependency is a QIIME2 package
                    if re.match(r'^(q2|qiime2)', dep.strip().split()[0]):
                        package_name = dep.strip().split()[0]
                        qiime_dependencies.append(package_name)
        except yaml.YAMLError:
            # If YAML parsing fails, fall back to line-by-line processing
            inside_run_section = False

            with open(conda_recipe, 'r') as f:
                for line in f:
                    line = line.rstrip()

                    # Check if we're entering the run section
                    if re.match(r'^\s*run:', line):
                        inside_run_section = True
                        continue

                    # Check if we're exiting the run section
                    if inside_run_section and (not re.search(r'[a-zA-Z0-9]', line) or re.match(r'^\s*[a-zA-Z0-9_-]+:', line)):
                        break

                    # Process dependencies in the run section
                    if inside_run_section:
                        # Replace Jinja2 templates
                        if "{{ qiime2_epoch }}" in line:
                            line = re.sub(r' {{ qiime2_epoch }}.*', f'=={version_tag}*', line)
                        if "{{ bowtie2 }}" in line:
                            line = re.sub(r' {{ bowtie2 }}', '==2.5.1', line)
                        if "{{ pysam }}" in line:
                            line = re.sub(r' {{ pysam }}', '==0.22.1', line)
                        if "{{ spades }}" in line:
                            line = re.sub(r' {{ spades }}', '==4.0.0', line)

                        dependencies.append(line)

                        # Check if the dependency is a QIIME2 package
                        if re.match(r'^\s*-\s*(q2|qiime2)', line):
                            package_name = re.sub(r'^\s*-\s*([^=<>]+).*$', r'\1', line)
                            qiime_dependencies.append(package_name)

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
