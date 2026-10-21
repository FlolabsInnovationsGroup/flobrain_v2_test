# Release process

1. Freeze the release branch on Sunday.
2. Run the release checklist on staging.
3. Ship on Tuesday morning, never on Thursday.

```
git tag v2.4.0 && git push --tags
```

> If the crash rate goes above 1%, roll back first and ask questions later.
