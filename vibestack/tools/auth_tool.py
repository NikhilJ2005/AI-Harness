"""Generate password hashing, token helpers, and the authentication routes."""

from vibestack.tools.context import ToolContext


def run(context: ToolContext) -> None:
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
