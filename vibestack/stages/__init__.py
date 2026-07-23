"""Pipeline stages.

Each stage is a small function that reads and updates the shared
``GenerationState``. Phase 0 implements only the first stage: parsing a prompt
into a ``ProjectSpec``.
"""
