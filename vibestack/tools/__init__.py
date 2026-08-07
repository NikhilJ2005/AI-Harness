"""The tools the generation agent calls.

Each tool takes the shared :class:`~vibestack.tools.context.ToolContext`, reads
the blueprint, and adds files to the generation state. Tools run in dependency
order — models before schemas, schemas before routers — because later tools rely
on decisions the earlier ones recorded.
"""
