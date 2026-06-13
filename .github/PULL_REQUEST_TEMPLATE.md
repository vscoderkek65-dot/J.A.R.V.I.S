## Description

Please include a summary of the change and which issue is fixed.

Fixes #(issue)

## Type of Change

- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update
- [ ] Refactor / performance
- [ ] Test / CI

## Safety Checklist

- [ ] New tools are registered in the central safety registry with a risk class
- [ ] High-risk operations trigger the approval workflow
- [ ] Audit logging covers new operations
- [ ] Untrusted content is properly isolated

## Test Checklist

- [ ] Existing tests pass (`.\test_acceptance.ps1`)
- [ ] New tests cover the change
- [ ] Smoke test succeeds (`run_windows.ps1 -Smoke`)

## Commit Hygiene

- [ ] No runtime data, secrets, or databases are included
- [ ] Changes are scoped to a single logical unit
