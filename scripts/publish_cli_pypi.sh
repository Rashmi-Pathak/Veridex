#!/usr/bin/env bash
#
# Publish the veridex-sbr CLI to PyPI.
#
# One-time setup (yours):
#   1. create a PyPI account at https://pypi.org/account/register/ and verify the email,
#   2. create an API token at https://pypi.org/manage/account/token/ (scope: entire account for the
#      first upload; you can narrow it to the veridex-sbr project after it exists),
#   3. put it in .env as:  PYPI_TOKEN=pypi-...
#
# Then run once from the repo root:  bash scripts/publish_cli_pypi.sh
# It rebuilds the sdist + wheel, runs twine check, and uploads with the token. A PyPI version can
# never be re-uploaded, so this is intentionally a clean rebuild + validate before upload.

set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "run from the repo root; .env not found"; exit 1; }
set -a; . ./.env; set +a
: "${PYPI_TOKEN:?add PYPI_TOKEN=pypi-... to .env (see the setup steps in the header above)}"

echo "==> Clean build"
rm -rf cli/dist
( cd cli && uvx --from build pyproject-build )

echo "==> Validate"
uvx twine check cli/dist/*

echo "==> Upload to PyPI"
TWINE_USERNAME="__token__" TWINE_PASSWORD="$PYPI_TOKEN" uvx twine upload cli/dist/*

echo ""
echo "Published. Verify in a minute with:"
echo "    pip install veridex-sbr && rooted status"
echo "    https://pypi.org/project/veridex-sbr/"
