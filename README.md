# utilities
A collection of utilities used across repos.

## CI Workflow

The `ci.yaml` workflow provides comprehensive testing and Docker image building capabilities for QIIME 2 plugins and related repositories. It supports both regular testing and containerized deployments with flexible configuration options.

### Features

- **Automated Testing**: Runs tests with conda/mamba environment management
- **Docker Image Building**: Creates both test and production Docker images  
- **Flexible Distribution Support**: Works with different QIIME 2 distributions (tiny, moshpit, etc.)
- **Smart Dependency Management**: Automatically fetches appropriate package versions
- **Commit Message Controls**: Special commit patterns trigger different behaviors
- **Caching**: Optimized conda environment and Docker layer caching

### Usage

#### Basic Testing (without Docker)

```yaml
# In your repository's workflow file
jobs:
  test:
    uses: bokulich-lab/utilities/.github/workflows/ci.yaml@main
    with:
      distro: tiny
      plugin_name: my-qiime2-plugin
```

#### Testing with Docker Build

```yaml
jobs:
  test-and-docker:
    uses: bokulich-lab/utilities/.github/workflows/ci.yaml@main
    with:
      distro: moshpit
      build_docker: true
    secrets: inherit  # Required for Docker registry access
```

### Input Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `distro` | Yes | `tiny` | QIIME 2 distribution to test against (`tiny`, `moshpit`, etc.) |
| `plugin_name` | No | *repository name* | Name of the plugin being tested (auto-detected from repository name) |
| `build_docker` | No | `false` | Whether to enable Docker image building |

### Commit Message Patterns

The workflow responds to special patterns in commit messages:

#### `[stable]` or `[prod]`
Uses stable/production package versions instead of development versions.

```bash
git commit -m "Release version 1.0.0 [stable]"
```

#### `[add:package:commit-hash]`
Installs a specific commit of a dependency package.

```bash
git commit -m "Update feature [add:qiime2:abc123def456]"
```

#### `[build-image]`
Triggers Docker image building during PR commits (useful for testing in staging environments).

```bash
git commit -m "Add new feature [build-image]

This needs containerized testing"
```

### What Gets Built

#### Test Job
- Sets up conda/mamba environment with specified distribution
- Installs development or stable versions based on commit message
- Runs your repository's test suite
- Uploads coverage artifacts

#### Docker Images (when `build_docker: true`)

**Test Image** (`target: test`):
- Built when `build_docker: true` and either:
  - Main branch pushes (merges)
  - PR commits with `[build-image]` in commit message
- Tagged with commit SHA for local testing
- Pushed to registry based on conditions above
- PR images tagged as: `quay.io/repo:pr-123-abc12345`

**Production Image** (`target: prod`):
- Built only on pushes to main branch (PR merges)
- Tagged as: `quay.io/repo:2024.10-abc12345`
- Automatically pushed to registry
- No tests run (assumes test image validation passed)

### Fork-Safe Docker Builds

The workflow is designed to work securely with forked repositories using a two-stage approach:

1. **Stage 1 (Fork-Safe)**: The `ci.yaml` workflow builds and tests Docker images but uploads them as artifacts instead of pushing to registries
2. **Stage 2 (Secure)**: The `docker-push.yaml` workflow downloads artifacts and pushes to registry with secure credentials

#### Setup - Call Docker Push as External Workflow

Instead of copying files to each repository, call the Docker push workflow directly:

```yaml
name: CI/CD Pipeline
on: [push, pull_request]

jobs:
  test-and-build:
    uses: bokulich-lab/utilities/.github/workflows/ci.yaml@main
    with:
      distro: moshpit
      build_docker: true

  push-docker:
    needs: test-and-build
    if: always() && needs.test-and-build.result == 'success'
    uses: bokulich-lab/utilities/.github/workflows/docker-push.yaml@main
    with:
      run_id: ${{ github.run_id }}
      repository: ${{ github.repository }}
    secrets: inherit
```

#### Required Secrets (Upstream Repository Only)

Configure these secrets in your upstream repository:

```yaml
secrets:
  DOCKER_USERNAME: # Quay.io username
  DOCKER_PASSWORD: # Quay.io password/token
```

#### How It Works

- **Forks**: Run tests and build images, upload as artifacts (no secrets needed)
- **Upstream**: Downloads artifacts from the test job and pushes to registry when builds succeed
- **Security**: Forks never have access to registry credentials
- **No File Copying**: Everything handled through callable workflows

### Example Workflows

#### Simple Plugin Testing
```yaml
name: Test Plugin
on: [push, pull_request]

jobs:
  test:
    uses: bokulich-lab/utilities/.github/workflows/ci.yaml@main
    with:
      distro: tiny
      plugin_name: q2-my-plugin
```

#### Full CI/CD with Docker
```yaml
name: CI/CD Pipeline
on: 
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test-and-build:
    uses: bokulich-lab/utilities/.github/workflows/ci.yaml@main
    with:
      distro: moshpit
      build_docker: true

  push-docker:
    needs: test-and-build
    if: always() && needs.test-and-build.result == 'success'
    uses: bokulich-lab/utilities/.github/workflows/docker-push.yaml@main
    with:
      run_id: ${{ github.run_id }}
      repository: ${{ github.repository }}
    secrets: inherit
```

### Repository Requirements

For the CI workflow to function properly, your repository must have the following structure and files:

#### Required Files

**`Makefile`** - Must include test targets:
```makefile
test:
	pytest

test-cov:
	pytest --cov=your_package --cov-report=xml
	
# If using Docker builds, also include:
test-docker:
	qiime dev refresh-cache
	pytest
```

**`setup.py` or `pyproject.toml`** - Standard Python package configuration:
```python
# setup.py example
from setuptools import setup, find_packages

setup(
    name="q2-your-plugin",
    # ... other configuration
)
```

**Test files** - PyTest-compatible test structure:
```
your_repo/
├── your_package/
│   ├── __init__.py
│   └── your_code.py
├── tests/
│   ├── __init__.py
│   └── test_your_code.py
├── setup.py
└── Makefile
```

#### For Docker Builds (when `build_docker: true`)

**`Dockerfile`** - Must have both `test` and `prod` targets:
```dockerfile
FROM quay.io/qiime2/tiny:2024.10 as base

# Install your package
COPY . /plugin
WORKDIR /plugin
RUN pip install .

# Test target - includes dev dependencies
FROM base as test
RUN pip install pytest pytest-cov coverage parameterized pytest-xdist
CMD ["make", "test-cov"]

# Production target - minimal runtime image
FROM base as prod
# Add any prod-specific configurations
CMD ["qiime", "--help"]
```

**GitHub Repository Secrets** (for Docker registry access):
- `DOCKER_USERNAME`: Your Quay.io username
- `DOCKER_PASSWORD`: Your Quay.io password or access token

#### Optional Configuration

**Plugin Registration** - Add your repository to `ci/repositories.yaml`:
```yaml
repositories:
  - name: q2-your-plugin
    url: https://github.com/your-org/q2-your-plugin.git
```

**Custom Conda Dependencies** - If your plugin has special requirements, they'll be automatically resolved through the dependency management system.

#### Directory Structure Example

```
your-qiime2-plugin/
├── .github/
│   └── workflows/
│       └── ci.yml                 # Your workflow calling utilities/ci.yaml
├── your_plugin/
│   ├── __init__.py
│   ├── plugin_setup.py           # QIIME 2 plugin registration
│   └── your_methods.py
├── tests/
│   ├── __init__.py
│   └── test_your_methods.py
├── Dockerfile                     # Required for Docker builds
├── Makefile                       # Required
├── setup.py                       # Required
├── README.md
└── requirements.txt               # Optional
```

#### Verification Checklist

Before using the CI workflow, ensure:

- [ ] `make test` runs successfully locally
- [ ] `make test-cov` generates `coverage.xml`
- [ ] Your package installs with `pip install .`
- [ ] If using Docker: `docker build --target test .` succeeds
- [ ] If using Docker: `docker build --target prod .` succeeds
- [ ] Repository secrets are configured (for Docker builds)

### Dependencies

The workflow uses several utilities from this repository:

- `ci/get-tags.py`: Fetches latest QIIME 2 release tags
- `ci/get-dependencies.py`: Generates conda environment files
- `ci/repositories.yaml`: Repository configuration
- `ci/condarc`: Conda configuration

### Caching

The workflow implements intelligent caching:

- **Conda environments**: Cached by OS, architecture, date, and environment file hash
- **Docker layers**: Uses GitHub Actions cache for faster builds
- **Cache invalidation**: Automatic when dependencies change

### Troubleshooting

**Tests fail with import errors**: Check that your plugin is properly listed in `repositories.yaml`

**Docker build fails**: Ensure your `Dockerfile` has both `test` and `prod` targets defined

**Registry push fails**: Verify `DOCKER_USERNAME` and `DOCKER_PASSWORD` secrets are set

**Wrong package versions**: Use `[stable]` in commit message for production builds
