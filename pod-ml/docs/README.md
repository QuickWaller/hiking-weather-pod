# pod-ml design docs

The *why* behind the model — every non-obvious parameter and design choice, with diagrams.
Built up incrementally as the pipeline is implemented.

| Doc | Covers |
|---|---|
| [01-pipeline.md](01-pipeline.md) | The end-to-end pipeline and the skill gate |
| [02-design-decisions.md](02-design-decisions.md) | Why each key parameter/choice was made (with diagrams) |
| [03-datasets.md](03-datasets.md) | Which ERA5 product (and why), variables, what we derive vs download |
| [04-results.md](04-results.md) | Skill-probe results with figures (skill, ranking, feature importance) |

> Diagrams use [Mermaid](https://mermaid.js.org/) — they render on GitHub and stay diffable in git.
> When a choice changes, update the diagram *and* the rationale paragraph next to it.
