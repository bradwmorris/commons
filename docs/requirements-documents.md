# Development Issue template

Maintainers may use this after reaching a confirmed agreement. Search for an Issue
covering the outcome before creating one. Follow the standalone
[contributor guide](development-guidelines.md). Keep the body concise; 3,000
characters is an editorial default, not a reason to omit an essential decision or
acceptance check. An external operating workflow may use different planning tools.

## Issue template

```markdown
## Outcome
<Who needs what observable result, and the current limitation/failing example.>

## Scope and exclusions
<What changes, what stays unchanged, and what is explicitly out of scope.>

## Decisions and constraints
<Confirmed choices and rationale; exact defaults, terminology and examples that matter.
Link existing product contracts. Record remaining unknowns/blockers explicitly.>

## Acceptance checks
- [ ] <Concrete input/action, expected result, and how to verify it.>
- [ ] <Relevant boundary, denial or recovery case, when needed.>
```

Small changes may combine headings without losing their substance. Each material
requirement needs an observable check; include useful normal and failure examples
from the interview. Preserve negative requirements as well as desired behavior.
Do not turn an unanswered question into an agreed default.

Record the implementation's starting revision and, after verification, its actual
commands, results, limitations and delivered commit. Detailed evidence may live in
comments or linked captures; the body remains the current agreed requirements.
Read back created/updated Issues to verify their content and URL. Close only when
the full agreed outcome is delivered; a partial milestone is not completion.
