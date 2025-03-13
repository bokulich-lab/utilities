#!/bin/bash

# Script to generate a changelog for a release
# This script is used by the GitHub Actions workflow

# Function to check if a tag is a dev tag
is_dev_tag() {
  [[ "$1" == *".dev"* ]]
}

# Get release tag from environment variable or first argument
RELEASE_TAG=${RELEASE_TAG:-$1}
if [ -z "$RELEASE_TAG" ]; then
  echo "Error: No release tag provided"
  echo "Usage: $0 <release_tag> [<previous_tag>]"
  exit 1
fi

# Get previous tag from environment variable, second argument, or determine it
PREVIOUS_TAG=${PREVIOUS_TAG:-$2}
if [ -z "$PREVIOUS_TAG" ]; then
  # Determine if current tag is a dev or prod tag
  if is_dev_tag "$RELEASE_TAG"; then
    echo "Current tag is a development tag"
    # For dev tags, find the previous dev tag or the last prod tag if it's the first dev after prod

    # Try to find the previous dev tag
    PREVIOUS_DEV_TAG=$(git tag -l | grep "\.dev" | grep -v "$RELEASE_TAG" | sort -V | tail -n 1)

    # Try to find the latest prod tag
    LATEST_PROD_TAG=$(git tag -l | grep -v "\.dev" | sort -V | tail -n 1)

    if [ -z "$PREVIOUS_DEV_TAG" ]; then
      # No previous dev tag, check if there's a prod tag
      if [ -z "$LATEST_PROD_TAG" ]; then
        # No prod tag either, will use first commit as fallback
        PREVIOUS_TAG=""
        echo "No previous dev tag or prod tag found, will use first commit as fallback"
      else
        # Use the latest prod tag
        PREVIOUS_TAG="$LATEST_PROD_TAG"
        echo "No previous dev tag found, using latest prod tag: $PREVIOUS_TAG"
      fi
    else
      # Compare the previous dev tag and latest prod tag to see which is more recent
      if [ -z "$LATEST_PROD_TAG" ] || git merge-base --is-ancestor "$LATEST_PROD_TAG" "$PREVIOUS_DEV_TAG" 2>/dev/null; then
        # Previous dev tag is more recent than latest prod tag (or no prod tag exists)
        PREVIOUS_TAG="$PREVIOUS_DEV_TAG"
        echo "Using previous dev tag: $PREVIOUS_TAG"
      else
        # Latest prod tag is more recent than previous dev tag
        PREVIOUS_TAG="$LATEST_PROD_TAG"
        echo "Using latest prod tag (more recent than previous dev): $PREVIOUS_TAG"
      fi
    fi
  else
    echo "Current tag is a production tag"
    # For prod tags, find the previous prod tag
    PREVIOUS_TAG=$(git tag -l | grep -v "\.dev" | grep -v "$RELEASE_TAG" | sort -V | tail -n 1)
    echo "Previous prod tag: $PREVIOUS_TAG"
  fi

  # If no previous tag was found, use the first commit
  if [ -z "$PREVIOUS_TAG" ]; then
    PREVIOUS_TAG=$(git rev-list --max-parents=0 HEAD)
    echo "No previous tag found, using first commit: $PREVIOUS_TAG"
  fi
fi

echo "Generating changelog between $PREVIOUS_TAG and $RELEASE_TAG..."

# Get all commits between the previous tag and the current release
COMMITS=$(git log --pretty=format:"%h|%an|%ae|%s" $PREVIOUS_TAG..$RELEASE_TAG)

# Initialize changelog sections
NEW_FEATURES=""
BUG_FIXES=""
MAINTENANCE=""
DOCUMENTATION=""
OTHER_CHANGES=""

# Function to format commit message with commit link
format_commit_message() {
  local message="$1"
  local hash="$2"

  # Create commit link
  local commit_link="https://github.com/bokulich-lab/q2-ena-uploader/commit/${hash}"

  # Format the message with commit link
  echo "${message} ([${hash}](${commit_link}))"
}

# Function to process a commit message and add it to the appropriate section
process_commit_message() {
  local commit_message="$1"
  local hash="$2"
  local section_var="$3"
  local has_prefix="$4"

  if [ "$has_prefix" = true ]; then
    # Extract the original prefix from the commit message
    prefix=$(echo "$commit_message" | grep -o "^[^:]*:")
    prefix=${prefix%:}

    # Extract the commit message without the prefix
    message="${commit_message#$prefix: }"
  else
    # No prefix to remove
    message="$commit_message"
  fi

  # Make first letter lowercase
  first_char=$(echo "${message:0:1}" | tr '[:upper:]' '[:lower:]')
  rest_of_message="${message:1}"

  # Format the message with commit link
  formatted_message=$(format_commit_message "${first_char}${rest_of_message}" "${hash}")

  # Add to the appropriate section using indirect variable reference
  eval "$section_var+=\"- \$formatted_message\n\""
}

# Process each commit and categorize by prefix
while IFS= read -r COMMIT; do
  # Extract the commit message (fourth field)
  COMMIT_MESSAGE=$(echo "$COMMIT" | cut -d'|' -f4)

  # Extract hash
  hash=$(echo "$COMMIT" | cut -d'|' -f1)

  # Convert to uppercase for case-insensitive comparison
  COMMIT_UPPER=$(echo "$COMMIT_MESSAGE" | tr '[:lower:]' '[:upper:]')

  # New features (ENH, IMP, ADD)
  if [[ "$COMMIT_UPPER" =~ ^ENH: ]] || [[ "$COMMIT_UPPER" =~ ^IMP: ]] || [[ "$COMMIT_UPPER" =~ ^ADD: ]]; then
    process_commit_message "$COMMIT_MESSAGE" "$hash" "NEW_FEATURES" true
  # Bug fixes (BUG, FIX)
  elif [[ "$COMMIT_UPPER" =~ ^BUG: ]] || [[ "$COMMIT_UPPER" =~ ^FIX: ]]; then
    process_commit_message "$COMMIT_MESSAGE" "$hash" "BUG_FIXES" true
  # Maintenance (MAINT, CI, TEST)
  elif [[ "$COMMIT_UPPER" =~ ^MAINT: ]] || [[ "$COMMIT_UPPER" =~ ^CI: ]] || [[ "$COMMIT_UPPER" =~ ^TEST: ]]; then
    process_commit_message "$COMMIT_MESSAGE" "$hash" "MAINTENANCE" true
  # Documentation (DOC)
  elif [[ "$COMMIT_UPPER" =~ ^DOC: ]]; then
    process_commit_message "$COMMIT_MESSAGE" "$hash" "DOCUMENTATION" true
  # Other changes (everything else)
  else
    process_commit_message "$COMMIT_MESSAGE" "$hash" "OTHER_CHANGES" false
  fi
done <<< "$COMMITS"

# Extract release name from tag (e.g., 2024.10 from 2024.10.0)
RELEASE_NAME=$(echo "$RELEASE_TAG" | grep -o "^[0-9]\{4\}\.[0-9]\{1,2\}")

# Create the changelog with release name
CHANGELOG="# 📋 ${RELEASE_NAME} Changelog\n\n"

if [ ! -z "$NEW_FEATURES" ]; then
  CHANGELOG+="## ✨ New features\n$NEW_FEATURES\n"
fi

if [ ! -z "$BUG_FIXES" ]; then
  CHANGELOG+="## 🐛 Bug fixes\n$BUG_FIXES\n"
fi

if [ ! -z "$MAINTENANCE" ]; then
  CHANGELOG+="## 🔧 Maintenance\n$MAINTENANCE\n"
fi

if [ ! -z "$DOCUMENTATION" ]; then
  CHANGELOG+="## 📚 Documentation\n$DOCUMENTATION\n"
fi

if [ ! -z "$OTHER_CHANGES" ]; then
  CHANGELOG+="## 🔄 Other changes\n$OTHER_CHANGES\n"
fi

# Save changelog to a file
echo -e "$CHANGELOG" > changelog.md

# Output the changelog
echo -e "$CHANGELOG"