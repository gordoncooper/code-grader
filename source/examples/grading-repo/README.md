# Grading

An example grading repo for the bundled sample code (`examples/sample-repo`), produced with the Code Grading Suite.

```
projects/
└── <project>/                 one folder per graded codebase
    ├── project.toml           settings: preset, answers, zones, targets   (people)
    ├── decisions.json         answers to decision questions               (people)
    ├── dispositions.json      findings accepted as-is                     (people)
    └── reports/
        └── <date>-<commit>/   one folder per report                        (graders, via pull request)
            ├── report.json
            └── report.md
```

- Graders open a pull request per report, on a branch named `report/<project>/<date>-<commit>`.
- Decision answers go on that same pull request, or in a follow-up `decisions/<project>/<date>` pull request.
- `org.toml` at the root (optional) holds house rules shared by every project.
