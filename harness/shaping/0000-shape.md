+++
id = "0000-shape"
title = "Shape an intent into a plan and draft specs"
kind = "shape"
class = "shaping"
status = "approved"
# What a shaping session may write: draft specs, their checks, and the plan. Nothing else in
# the harness, and never the code: a shaper plans the work, it does not do it.
scope = ["specs/**", "harness/checks/**", "plans/**"]

[checks]
# The Stop hook runs the intake check: valid draft specs, a plan, and checks that fail today.
quick = ["python {harness}/checks/shape_output.py"]

[caps]
max_turns = 40
max_budget_usd = 3.0
continuations = 2
+++

(The body is built by harness/bin/shape.sh from the intent file and the spec format.)
