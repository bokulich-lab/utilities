#!/bin/bash

# Define the qiime channel version from the tag
channel_version=$(echo "$2" | cut -d'.' -f1-2)

# Define the paths to meta.yaml, env output file, and YAML repo file
template_file="conda-recipe/meta.yaml"
output_file="environment.yml"
repo_yaml_file="$3"
repo_urls_file="repo-urls.txt"

# Extract dependencies from the meta.yaml file
inside_run_section=false
dependencies=""
qiime_dependencies=""
repo_urls=""

while IFS= read -r line; do
    # If we encounter the "run:" line, set flag to true
    if [[ $line =~ ^[[:space:]]*run: ]]; then
        inside_run_section=true
        continue
    fi

    # If we encounter an empty line or a new section header and we're inside the run: section, exit
    if [[ $inside_run_section == true && ( ! $line =~ [[:alnum:]] || $line =~ ^[[:space:]]*[a-zA-Z0-9_-]+: ) ]]; then
        break
    fi

    # If we're inside the "run:" section add line to dependencies
    if [[ $inside_run_section == true ]]; then
        # Replace the pattern " {{ qiime2_epoch }}.*" with the version tag
        line=$(echo "$line" | sed "s/ {{ qiime2_epoch }}.*/==$2*/")
        # Replace the pattern " {{ bowtie2 }}" with "2.5.1"
        line=$(echo "$line" | sed "s/ {{ bowtie2 }}/==2.5.1/")
        dependencies+="$line"$'\n'

        # Check if the line contains qiime2 or q2 and add to qiime_dependencies
        if [[ $line =~ ^[[:space:]]*-[[:space:]]*(q2|qiime2) ]]; then
            package_name=$(echo "$line" | sed -E 's/^[[:space:]]*-[[:space:]]*([^=<>]+).*$/\1/')
            qiime_dependencies+="$package_name"$'\n'
        fi
    fi
done < "$template_file"

# Only add q2cli if it's not already present in dependencies
if [[ "$dependencies" != *"q2cli"* ]]; then
  dependencies+="  - q2cli"$'\n'
fi

# Write the dependencies to the output YAML file
cat <<EOF > "$output_file"
name: conda-env

channels:
    - https://packages.qiime2.org/qiime2/$channel_version/$1/passed/
    - conda-forge
    - bioconda
    - defaults

dependencies:
$dependencies
EOF

# Read the repo YAML file and extract URLs based on the qiime_dependencies
while IFS= read -r package_name; do
    if [[ -n "$package_name" ]]; then
        url=$(yq ".repositories[] | select(.name == \"$package_name\") | .url" "$repo_yaml_file" | tr -d '"')
        if [[ -n "$url" ]]; then
            repo_urls+="git+$url.git"$'\n'
        fi
    fi
done <<< "$qiime_dependencies"

# Write the repo URLs to the repo-urls.txt file
echo "$repo_urls" > "$repo_urls_file"
