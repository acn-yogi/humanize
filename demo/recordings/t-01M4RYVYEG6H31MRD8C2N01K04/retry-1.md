The workbench checked your change and did not accept it. Findings, from processes outside your session:

- router: adversarial review raised findings
- router: The -k example selects all 76 tests in tests/test_filesize.py (same as running the file), so it does not show focusing a test run as the spec intends
- router: The translation-binaries script has to run from the repo root and needs msgfmt on PATH; the page doesn't say so
- router: The skip explanation leaves out the other skip reason in test_i18n.py
- reviewer: The -k example selects all 76 tests in tests/test_filesize.py (same as running the file), so it does not show focusing a test run as the spec intends
- reviewer: The translation-binaries script has to run from the repo root and needs msgfmt on PATH; the page doesn't say so
- reviewer: The skip explanation leaves out the other skip reason in test_i18n.py

Fix the causes within the spec's scope, then finish. Do not weaken or skip any check.
