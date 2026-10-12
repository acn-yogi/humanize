The workbench checked your change and did not accept it. Findings, from processes outside your session:

- router: high risk: class packaging is high risk by policy
- router: adversarial review raised findings
- router: intcomma/intword echo non-numeric input (e.g. 'abc') to stdout with exit 0, violating 'errors go to stderr with non-zero exit'
- router: naturaldelta accepts inf/nan and prints them with exit 0
- router: error-path tests cover only naturalsize and naturaldelta, so the gap is untested
- router: adds docs/cli.md and an mkdocs nav entry beyond the spec's scope
- router: pyproject.toml changed but touchesManifests reports false; needs explicit human approval per criterion 4
- reviewer: intcomma/intword echo non-numeric input (e.g. 'abc') to stdout with exit 0, violating 'errors go to stderr with non-zero exit'
- reviewer: naturaldelta accepts inf/nan and prints them with exit 0
- reviewer: error-path tests cover only naturalsize and naturaldelta, so the gap is untested
- reviewer: adds docs/cli.md and an mkdocs nav entry beyond the spec's scope
- reviewer: pyproject.toml changed but touchesManifests reports false; needs explicit human approval per criterion 4

Fix the causes within the spec's scope, then finish. Do not weaken or skip any check.
