"""The hybrid index (Phase 22): structural, lexical/vector, and execution — one store, one planner.

`store` holds the rows, `structure` and `lexical` fill the two cheap indices, `execution` fills
the one that costs a sandbox, `build` runs them in order, `query` answers questions from them, and
`specs` turns recorded behaviour into a specification whose every claim cites an observation.
"""
