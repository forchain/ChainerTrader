.ONESHELL:
ENV_PREFIX=$(shell python -c "if __import__('pathlib').Path('.venv/bin/pip').exists(): print('.venv/bin/')")
USING_UV=$(shell command -v uv >/dev/null 2>&1 && echo "yes")

.PHONY: help
help:             ## Show the help.
	@echo "Usage: make <target>"
	@echo ""
	@echo "Targets:"
	@fgrep "##" Makefile | fgrep -v fgrep


.PHONY: show
show:             ## Show the current environment.
	@echo "Current environment:"
	@if [ "$(USING_UV)" ]; then uv --version; else echo "Running using $(ENV_PREFIX)"; $(ENV_PREFIX)python -V; $(ENV_PREFIX)python -m site; fi

.PHONY: install
install:          ## Install the project in dev mode.
	@if [ "$(USING_UV)" ]; then uv sync --dev; else echo "Don't forget to run 'make virtualenv' if you got errors."; $(ENV_PREFIX)pip install -e .[dev] -i https://pypi.tuna.tsinghua.edu.cn/simple; fi

.PHONY: fmt
fmt:              ## Format code using black & isort.
	@if [ "$(USING_UV)" ]; then uv run isort trader/ && uv run black -l 79 trader/ && uv run black -l 79 tests/; else $(ENV_PREFIX)isort trader/; $(ENV_PREFIX)black -l 79 trader/; $(ENV_PREFIX)black -l 79 tests/; fi

.PHONY: lint
lint:             ## Run pep8, black, mypy linters.
	@if [ "$(USING_UV)" ]; then uv run flake8 trader/ && uv run black -l 79 --check trader/ && uv run black -l 79 --check tests/ && uv run mypy --ignore-missing-imports trader/; else $(ENV_PREFIX)flake8 trader/; $(ENV_PREFIX)black -l 79 --check trader/; $(ENV_PREFIX)black -l 79 --check tests/; $(ENV_PREFIX)mypy --ignore-missing-imports trader/; fi

.PHONY: test
test: lint        ## Run tests and generate coverage report.
	@if [ "$(USING_UV)" ]; then uv run pytest -v --cov-config .coveragerc --cov=trader -l --tb=short --maxfail=1 tests/ && uv run coverage xml && uv run coverage html; else $(ENV_PREFIX)pytest -v --cov-config .coveragerc --cov=trader -l --tb=short --maxfail=1 tests/; $(ENV_PREFIX)coverage xml; $(ENV_PREFIX)coverage html; fi

.PHONY: watch
watch:            ## Run tests on every change.
	@if [ "$(USING_UV)" ]; then ls **/**.py | entr uv run pytest -s -vvv -l --tb=long --maxfail=1 tests/; else ls **/**.py | entr $(ENV_PREFIX)pytest -s -vvv -l --tb=long --maxfail=1 tests/; fi

.PHONY: clean
clean:            ## Clean unused files.
	@find ./ -name '*.pyc' -exec rm -f {} \;
	@find ./ -name '__pycache__' -exec rm -rf {} \;
	@find ./ -name 'Thumbs.db' -exec rm -f {} \;
	@find ./ -name '*~' -exec rm -f {} \;
	@rm -rf .cache
	@rm -rf .pytest_cache
	@rm -rf .mypy_cache
	@rm -rf build
	@rm -rf dist
	@rm -rf *.egg-info
	@rm -rf htmlcov
	@rm -rf .tox/
	@rm -rf docs/_build
	@rm -rf .uv/

.PHONY: virtualenv
virtualenv:       ## Create a virtual environment using uv.
	@if [ "$(USING_UV)" ]; then if [ -d ".venv" ]; then echo "Virtual environment .venv already exists. Exiting."; exit 0; fi; echo "Creating virtual environment with uv..." && uv venv && uv sync --dev && echo "Virtual environment created successfully with uv!" && echo "Run 'uv shell' to activate the environment"; else echo "creating virtualenv ..."; rm -rf .venv; python3 -m venv .venv; ./.venv/bin/pip install -U pip -i https://pypi.tuna.tsinghua.edu.cn/simple; ./.venv/bin/pip install -e .[dev] -i https://pypi.tuna.tsinghua.edu.cn/simple; echo; echo "!!! Please run 'source .venv/bin/activate' to enable the environment !!!"; fi

.PHONY: release
release:          ## Create a new tag for release.
	@echo "WARNING: This operation will create s version tag and push to github"
	@read -p "Version? (provide the next x.y.z semver) : " TAG
	@echo "$${TAG}" > trader/VERSION
	@$(ENV_PREFIX)gitchangelog > HISTORY.md
	@git add trader/VERSION HISTORY.md
	@git commit -m "release: version $${TAG} 🚀"
	@echo "creating git tag : $${TAG}"
	@git tag $${TAG}
	@git push -u origin HEAD --tags
	@echo "Github Actions will detect the new tag and release the new version."

.PHONY: docs
docs:             ## Build the documentation.
	@echo "building documentation ..."
	@if [ "$(USING_UV)" ]; then uv run mkdocs build && URL="site/index.html"; xdg-open $$URL || sensible-browser $$URL || x-www-browser $$URL || gnome-open $$URL || open $$URL; else $(ENV_PREFIX)mkdocs build; URL="site/index.html"; xdg-open $$URL || sensible-browser $$URL || x-www-browser $$URL || gnome-open $$URL || open $$URL; fi

.PHONY: switch-to-uv
switch-to-uv:     ## Switch to uv package manager.
	@echo "Switching to uv ..."
	@if ! uv --version > /dev/null; then echo 'uv is required, install from https://docs.astral.sh/uv/getting-started/installation/'; exit 1; fi
	@rm -rf .venv
	@uv init --name trader --author "Your Name <your.email@example.com>"
	@echo "" >> pyproject.toml
	@echo "[project.optional-dependencies]" >> pyproject.toml
	@echo "dev = [" >> pyproject.toml
	@echo '    "pytest>=7.0.0",' >> pyproject.toml
	@echo '    "pytest-cov>=4.0.0",' >> pyproject.toml
	@echo '    "black>=23.0.0",' >> pyproject.toml
	@echo '    "isort>=5.0.0",' >> pyproject.toml
	@echo '    "flake8>=6.0.0",' >> pyproject.toml
	@echo '    "mypy>=1.0.0",' >> pyproject.toml
	@echo '    "coverage>=7.0.0",' >> pyproject.toml
	@echo '    "mkdocs>=1.0.0",' >> pyproject.toml
	@echo '    "mkdocs-material>=9.0.0",' >> pyproject.toml
	@echo '    "gitchangelog>=3.0.0",' >> pyproject.toml
	@echo "]" >> pyproject.toml
	@echo "" >> pyproject.toml
	@echo "[project.scripts]" >> pyproject.toml
	@echo 'trader = "trader.__main__:main"' >> pyproject.toml
	@uv sync --dev
	@mkdir -p .github/backup
	@mv requirements* .github/backup 2>/dev/null || true
	@mv setup.py .github/backup 2>/dev/null || true
	@echo "You have switched to https://docs.astral.sh/uv/ package manager."
	@echo "Please run 'uv shell' or 'uv run trader'"

.PHONY: add-deps
add-deps:         ## Add dependencies using uv.
	@if [ "$(USING_UV)" ]; then read -p "Package name: " PKG && uv add "$${PKG}"; else echo "uv is not available, using pip instead"; read -p "Package name: " PKG && $(ENV_PREFIX)pip install "$${PKG}"; fi

.PHONY: add-dev-deps
add-dev-deps:     ## Add development dependencies using uv.
	@if [ "$(USING_UV)" ]; then read -p "Package name: " PKG && uv add --dev "$${PKG}"; else echo "uv is not available, using pip instead"; read -p "Package name: " PKG && $(ENV_PREFIX)pip install "$${PKG}"; fi

.PHONY: update-deps
update-deps:      ## Update dependencies using uv.
	@if [ "$(USING_UV)" ]; then uv lock --upgrade && uv sync; else echo "uv is not available, using pip instead"; $(ENV_PREFIX)pip install --upgrade -r requirements.txt; fi

.PHONY: init
init:             ## Initialize the project based on an application template.
	@./.github/init.sh
