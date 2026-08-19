"""The model layer (P1) — every provider Tempest can reach, behind one code path.

`providers` is the registry (data); `client` is the two wire adapters (behaviour). Adding a
provider is a row in the registry, never a change here or in `client` — a property the
`provider_matrix` gate checks rather than assumes.
"""
