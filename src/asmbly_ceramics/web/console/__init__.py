"""The staff console (#3 to #7): sign-in, the waiting list and search, one drop-off with
its photos, rejection with its preview and undo, the emails needing attention, kiln
loads, firing notes and their search, the firing log and its CSV, the studio's settings and the weekly counts.

`create_app` adds `console_routes()` when it is given `ConsoleServices` (the console
function's app); the form function's app has none, so it serves no `/console` page.
"""

from starlette.routing import BaseRoute, Route

from asmbly_ceramics.web.console import (
    auth,
    counts,
    dropoffs,
    emails,
    firing_log,
    loads,
    notes,
    settings,
    waiting,
)
from asmbly_ceramics.web.console.services import ConsoleServices

__all__ = ["ConsoleServices", "console_routes"]


def console_routes() -> list[BaseRoute]:
    """Every console path. Each handler checks the token and the `ceramics` group first
    (`auth.require_staff`), except sign-in, its callback and the signed-out page."""
    drop_off = "/console/drop-offs/{id}"
    load = "/console/loads/{load}"
    note = load + "/notes/{note}"
    catalog = "/console/settings/{list}"
    firing_type = "/console/settings/firing-types/{item}"
    kiln = "/console/settings/kilns/{item}"
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
        Route(drop_off + "/delete", dropoffs.delete, methods=["POST"]),
        Route(drop_off + "/emails/{kind}/retry", dropoffs.retry, methods=["POST"]),
        Route("/console/loads", loads.loads_page, methods=["GET"]),
        Route("/console/loads", loads.start_load, methods=["POST"]),
        Route(load, loads.load_page, methods=["GET"]),
        Route(load + "/add", loads.add_to_load, methods=["POST"]),
        Route(load + "/remove", loads.remove_from_load, methods=["POST"]),
        Route(load + "/edit", loads.change_load, methods=["POST"]),
        Route(load + "/start-firing", loads.start_firing, methods=["POST"]),
        Route(load + "/fire", loads.mark_fired, methods=["POST"]),
        Route(load + "/delete", loads.delete_load, methods=["POST"]),
        Route(load + "/record", loads.save_record, methods=["POST"]),
        Route(load + "/steps/{step}/time", loads.correct_step_time, methods=["POST"]),
        Route(load + "/emails/{drop_off}/retry", loads.retry_email, methods=["POST"]),
        Route(load + "/notes", notes.write_note, methods=["POST"]),
        Route(note + "/edit", notes.edit_page, methods=["GET"]),
        Route(note + "/edit", notes.edit_note, methods=["POST"]),
        Route(note + "/remove", notes.remove_note, methods=["POST"]),
        Route("/console/notes", notes.search_page, methods=["GET"]),
        Route("/console/firing-log", firing_log.firing_log_page, methods=["GET"]),
        Route("/console/firing-log.csv", firing_log.firing_log_csv, methods=["GET"]),
        Route("/console/settings", settings.settings_page, methods=["GET"]),
        Route("/console/settings/history", settings.history_page, methods=["GET"]),
        Route("/console/settings/email", settings.save_email_settings, methods=["POST"]),
        Route("/console/settings/test-email", settings.send_test_email, methods=["POST"]),
        Route(firing_type + "/program", settings.set_default_program, methods=["POST"]),
        Route(kiln + "/counts", settings.set_kiln_counts, methods=["POST"]),
        Route(kiln + "/new-elements", settings.record_new_elements, methods=["POST"]),
        Route(catalog + "/add", settings.add_item, methods=["POST"]),
        Route(catalog + "/retire", settings.retire_item, methods=["POST"]),
        Route(catalog + "/restore", settings.restore_item, methods=["POST"]),
        Route(catalog + "/delete", settings.delete_item, methods=["POST"]),
        Route("/console/counts", counts.counts_page, methods=["GET"]),
        Route(auth.SIGN_IN, auth.sign_in, methods=["GET"]),
        Route("/console/auth/callback", auth.callback, methods=["GET"]),
        Route("/console/sign-out", auth.sign_out, methods=["POST"]),
        Route("/console/signed-out", auth.signed_out, methods=["GET"]),
    ]
