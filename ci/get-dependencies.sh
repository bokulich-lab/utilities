#!/bin/bash

# Define the qiime channel version from the tag
channel_version="$2"
channel_version="${channel_version%.*.*}"

# Define the paths to meta.yaml and env output file
template_file="ci/recipe/meta.yaml"
output_file=".github/environment.yml"

# Extract dependencies from the meta.yaml file
inside_run_section=false
dependencies=""

while IFS= read -r line; do
    # If we encounter the "run:" line, set flag to true
    if [[ $line =~ ^[[:space:]]*run: ]]; then
        inside_run_section=true
        continue
    fi

    # If we're inside the "run:" section add line to dependencies
    if [[ $inside_run_section == true ]]; then
        # Replace the pattern " {{ qiime2_epoch }}.*" with the version tag
        line=$(echo "$line" | sed "s/ {{ qiime2_epoch }}.*/==$2*/")
        # Replace the pattern " {{ bowtie2 }}" with "2.5.1"
        line=$(echo "$line" | sed "s/ {{ bowtie2 }}/==2.5.1/")
        dependencies+="$line"$'\n'
    fi

    # If we encounter an empty line and we're inside the run: section, exit
    if [[ $inside_run_section == true && ! $line =~ [[:alnum:]] ]]; then
        break
    fi
done < "$template_file"

# Write the dependencies to the output YAML file
cat <<EOF > "$output_file"
name: conda-env

channels:
    - https://packages.qiime2.org/qiime2/$channel_version/$1/staged/
    - conda-forge
    - bioconda
    - defaults

dependencies:
$dependencies
EOF
