"""Local prove shapes: the desktop app points its bundled API at a repo on this machine.

`base` and `head` are git refs (branch, tag, or sha); the endpoint resolves them with
`git rev-parse`, so the created run stores full 40-hex shas exactly like uploaded runs.
"""

from pydantic import BaseModel, Field


class LocalProveRequest(BaseModel):
    repo_path: str = Field(min_length=1)
    base: str = Field(min_length=1, max_length=200)
    head: str = Field(min_length=1, max_length=200)
    max_inputs: int = Field(default=300, ge=1)
