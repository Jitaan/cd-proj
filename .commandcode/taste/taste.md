# Taste

- Prefers complete implementations over incremental/short-term patches: when a request spans multiple features, wants the full scope done properly (e.g. all requested capabilities plus the correct underlying redesign) rather than deferring parts or hacking around limitations. Confidence: 0.6
- Values correctness/robustness over minimal churn — favors the design that fixes root causes (e.g. a proper rewrite) even when it touches more files, as long as existing behavior is protected by tests. Confidence: 0.5
- Expects UI changes (theming, rendering, presentation) to be applied consistently across every related surface of the app, not just the element originally pointed at — will explicitly follow up asking for sibling blocks/panes to get the same treatment (e.g. dark scrollbars everywhere, both the Trace and Features blocks rendered as readable tables rather than raw JSON). Confidence: 0.6
- Prefers structured, human-readable presentation of data in the UI (tables/grouped rows with clear labels) over dumping raw JSON or empty placeholders — and wants such blocks to always render with a sensible fallback rather than disappearing. Confidence: 0.4
