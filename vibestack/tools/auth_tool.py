"""Generate password hashing, token helpers, and the authentication routes.

This tool runs after the schemas because the auth routes reuse the account
entity's create and read schemas. It does nothing when the blueprint has no
authentication plan.
"""

from vibestack.tools.context import ToolContext


def run(context: ToolContext) -> None:
    """Generate the security helpers and auth router, if auth is enabled."""
    auth_plan = context.blueprint.auth
    if auth_plan is None:
        return

    context.render_to_file(
        template_name="app/security.py.jinja",
        file_path="app/security.py",
        rationale=(
            "Hashes passwords with bcrypt and issues signed tokens, so "
            "credentials are never stored or transmitted in clear text."
        ),
    )

    context.render_to_file(
        template_name="app/routers/auth.py.jinja",
        file_path="app/routers/auth.py",
        rationale=(
            "Provides register, login, and current-user endpoints backed by "
            f"the {auth_plan.entity_plan.names.entity_name} table."
        ),
        user_class=auth_plan.entity_plan.names.class_name,
        user_module=auth_plan.entity_plan.names.module_name,
        login_field=auth_plan.login_field,
        password_field=auth_plan.password_field,
    )
