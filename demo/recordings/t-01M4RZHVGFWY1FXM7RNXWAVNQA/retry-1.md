The workbench checked your change and did not accept it. Findings, from processes outside your session:

- router: adversarial review raised findings
- router: Docstring edit puts the new text inside the unclosed '0 minutes' example, which breaks the mkdocstrings-rendered docs
- router: Extends 'zero never gains a sign' to any negative value whose output renders as zero, using a fragile scan for digits 1-9 in the output string, which the spec did not ask for
- router: Unnecessary public-wrapper/private-helper split that repeats _date_and_delta's type checks
- reviewer: Docstring edit puts the new text inside the unclosed '0 minutes' example, which breaks the mkdocstrings-rendered docs
- reviewer: Extends 'zero never gains a sign' to any negative value whose output renders as zero, using a fragile scan for digits 1-9 in the output string, which the spec did not ask for
- reviewer: Unnecessary public-wrapper/private-helper split that repeats _date_and_delta's type checks

Fix the causes within the spec's scope, then finish. Do not weaken or skip any check.
