"""The staff console (#3, #5): sign-in, the waiting list and search, one drop-off with its
photos, rejection with its preview and undo, and the emails needing attention.

`create_app` adds `console_routes()` when it is given `ConsoleServices` (the console
function's app); the form function's app has none, so it serves no `/console` page.
"""

from starlette.routing import BaseRoute, Route

from asmbly_ceramics.web.console import auth, dropoffs, emails, waiting
from asmbly_ceramics.web.console.services import ConsoleServices

__all__ = ["ConsoleServices", "console_routes"]


def console_routes() -> list[BaseRoute]:
    """Every console path. Each handler checks the token and the `ceramics` group first
    (`auth.require_staff`), except sign-in, its callback and the signed-out page."""
    drop_off = "/console/drop-offs/{id}"
    return [
        Route("/console", waiting.waiting_page, methods=["GET"]),
        Route("/console/search", waiting.search, methods=["POST"]),
        Route("/console/emails", emails.emails_page, methods=["GET"]),
        Route(drop_off, dropoffs.drop_off_page, methods=["GET"]),
        Route(drop_off + "/photos/{k}", dropoffs.photo, methods=["GET"]),
        Route(drop_off + "/photos/{k}/thumb", dropoffs.thumbnail, methods=["GET"]),
        Route(drop_off + "/reject/preview", dropoffs.preview, methods=["POST"]),
        Route(drop_off + "/reject", dropoffs.reject, methods=["POST"]),
        Route(drop_off + "/undo-reject", dropoffs.undo, methods=["POST"]),
        Route(drop_off + "/emails/{kind}/retry", dropoffs.retry, methods=["POST"]),
        Route(auth.SIGN_IN, auth.sign_in, methods=["GET"]),
        Route("/console/auth/callback", auth.callback, methods=["GET"]),
        Route("/console/sign-out", auth.sign_out, methods=["POST"]),
        Route("/console/signed-out", auth.signed_out, methods=["GET"]),
    ]
