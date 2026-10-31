"""AI module (docs/ai-pipeline.md): natural language -> validated BuildingSpecification.

The AI produces intent, never geometry (CLAUDE.md rule 2):

    prompt -> AIProvider (mock | anthropic) -> SpecificationDraft (tool output)
           -> Pydantic (tier 1) -> rules spec checks (tier 2) -> [one repair call] -> spec
           -> layout engine -> BuildingModel -> new project version

Vendor SDKs are imported only in `providers/<vendor>.py` (rule 13).
"""
