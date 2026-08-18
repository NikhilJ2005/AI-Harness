"""Stage 1 — parse a natural-language prompt into a ``ProjectSpec``."""

from vibestack.llm_protocol import ModelTier, StructuredLLM
from vibestack.spec import ProjectSpec

PARSE_SYSTEM_PROMPT = """
You are the specification parser for VibeStack, a tool that generates FastAPI
backends. Read the user's description of a backend and turn it into a structured
ProjectSpec.

Guidelines:
- Give every entity an integer "id" field marked as the primary key.
- Choose sensible field types from the allowed list.
- Add relationships when the description implies them (for example, a blog post
  belongs to a user).
- Enable JWT authentication whenever the description mentions users, accounts,
  or logging in.
- Keep the project_name short and in snake_case.
""".strip()


def parse_prompt_to_spec(prompt: str, llm: StructuredLLM) -> ProjectSpec:
    spec = llm.structured_completion(
        system_prompt=PARSE_SYSTEM_PROMPT,
        user_prompt=prompt,
        response_model=ProjectSpec,
        tier=ModelTier.MID,
    )
    return spec
