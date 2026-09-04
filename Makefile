.ONESHELL:
ENV_PREFIX=".venv/bin/"
USING_UV=$(shell command -v uv >/dev/null 2>&1 && echo "yes")

.PHONY: help
help:             ## Show the help.
	@echo "Usage: make <target>"
	@echo ""
	@echo "Targets:"
	@fgrep "##" Makefile | fgrep -v fgrep


.PHONY: install
install:          ## Install the project in dev mode.
	@if [ "$(USING_UV)" ]; then \
		uv sync --dev; \
	else \
		$(ENV_PREFIX)python -m venv .venv; \
		$(ENV_PREFIX)pip install -e .[dev]; \
	fi

.PHONY: fmt
fmt:              ## Format code using black & isort.
	@if [ "$(USING_UV)" ]; then \
		uv run black .; \
		uv run ruff check . --fix; \
	else \
		$(ENV_PREFIX)black .; \
		$(ENV_PREFIX)ruff check . --fix; \
	fi

.PHONY: lint
lint:             ## Run linters.
	@if [ "$(USING_UV)" ]; then \
		uv run ruff check .; \
		uv run python scripts/check_repo_layout.py $$(git ls-files --cached --others --exclude-standard -- '*.json' 'tests/output/*'); \
	else \
		$(ENV_PREFIX)ruff check .; \
		$(ENV_PREFIX)python scripts/check_repo_layout.py $$(git ls-files --cached --others --exclude-standard -- '*.json' 'tests/output/*'); \
	fi

.PHONY: test
test: lint        ## Run tests
	@if [ "$(USING_UV)" ]; then \
		uv run pytest tests/; \
	else \
		$(ENV_PREFIX)pytest tests/; \
	fi

.PHONY: clean
clean:            ## Clean unused files.
	@find ./ -name '*.pyc' -exec rm -f {} \;
	@find ./ -name '__pycache__' -exec rm -rf {} \;
	@find ./ -name 'Thumbs.db' -exec rm -f {} \;
	@find ./ -name '*~' -exec rm -f {} \;
	@rm -rf .cache
	@rm -rf .pytest_cache
	@rm -rf build
	@rm -rf dist
	@rm -rf *.egg-info
	@rm -rf docs/_build

.PHONY: docs
docs:             ## Build the documentation.
	@echo "building documentation ..."
	@if [ "$(USING_UV)" ]; then \
		uv run mkdocs build && \
		URL="site/index.html"; \
		xdg-open $$URL || \
		sensible-browser $$URL || \
		x-www-browser $$URL || \
		gnome-open $$URL || \
		open $$URL; \
	else \
		$(ENV_PREFIX)mkdocs build; \
		URL="site/index.html"; \
		xdg-open $$URL || \
		sensible-browser $$URL || \
		x-www-browser $$URL || \
		gnome-open $$URL || \
		open $$URL; \
	fi

.env:
	@if [ ! -f .env ]; then \
		cp example.env .env; \
		echo "Created .env from example.env"; \
	else \
		echo ".env already exists, skipping"; \
	fi

.PHONY: serve
serve: .env            ## Run the API server.
	@if [ "$(USING_UV)" ]; then \
		uv run trader; \
	else \
		$(ENV_PREFIX)python -m trader; \
	fi
