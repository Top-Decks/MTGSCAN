SHELL := /bin/bash

test:
	set -o allexport; \
	if [ -f azure.env ]; then source azure.env; fi; \
	set +o allexport; \
	python3 tests/test.py

test-azure-fix:
	@echo "运行Azure OCR Base64修复测试..."
	set -o allexport; \
	if [ -f azure.env ]; then source azure.env; fi; \
	set +o allexport; \
	python3 -c "import sys; sys.path.insert(0, '.'); from tests.test import test_azure_base64_fix; test_azure_base64_fix()"

test-all: test-azure-fix test
	@echo "所有测试完成"

example:
	set -o allexport; \
	source azure.env; \
	set +o allexport; \
	poetry run python example.py
