---
name: dogfood
description: Systematic exploratory QA testing of web applications — find bugs, capture evidence, and generate structured reports using browser_console and annotate-capable browser vision workflows.
version: 1.0.0
metadata:
  henio:
    tags: [qa, testing, browser, web, dogfood]
---

# Dogfood: Systematic Web Application QA Testing

This skill guides systematic exploratory QA testing of web applications using the browser toolset.

## Workflow

1. Plan the pages and flows to test.
2. Navigate and inspect with snapshots.
3. Check `browser_console()` after navigation and significant interactions.
4. Use annotated screenshots (`annotate=true`) to reason about interactive elements.
5. Classify issues by severity and category using `references/issue-taxonomy.md`.
6. Produce the final report using `templates/dogfood-report-template.md`.
