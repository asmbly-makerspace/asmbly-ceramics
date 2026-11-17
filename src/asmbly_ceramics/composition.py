"""The composition root: the AWS adapters and the use cases each deployed function runs,
built from `Settings`.

Each function's clients are built once per container (`adapters.aws.clients`'
`FormClients.build`, `ConsoleClients.build`, `MailerClients.build` and
`CloserClients.build`, cached), with their configs; the tests pass stubbed clients
instead. Nothing here, and nothing it imports, imports `web.local`: that module builds
the in-memory fakes and is only for a laptop.
"""

from starlette.applications import Starlette

from asmbly_ceramics.adapters.aws.clients import CloserClients, ConsoleClients, FormClients, MailerClients
from asmbly_ceramics.adapters.aws.ids import DynamoDbIdNumbers
from asmbly_ceramics.adapters.aws.mailer import SesMailer
from asmbly_ceramics.adapters.aws.photos import S3PhotoStore
from asmbly_ceramics.adapters.aws.rate_limit import DynamoDbRateLimiter
from asmbly_ceramics.adapters.aws.records import DynamoDbRecords
from asmbly_ceramics.adapters.aws.secrets import SsmSecrets
from asmbly_ceramics.adapters.aws.staff_tokens import CognitoStaffTokens
from asmbly_ceramics.adapters.clock import SystemClock
from asmbly_ceramics.adapters.images import PillowPhotoInspector
from asmbly_ceramics.mail.compose import JinjaComposer
from asmbly_ceramics.ports.secrets import SecretName
from asmbly_ceramics.ports.staff import StaffTokens
from asmbly_ceramics.settings import Settings, StaffSignIn
from asmbly_ceramics.use_cases.close import CloseFinished
from asmbly_ceramics.use_cases.counts import WeeklyCounts
from asmbly_ceramics.use_cases.delete_drop_off import DeleteDropOff
from asmbly_ceramics.use_cases.emails import EmailsNeedingAttention, RetryEmail, SendPendingEmail
from asmbly_ceramics.use_cases.firing_log import FiringLog
from asmbly_ceramics.use_cases.keys import KeyHasher
from asmbly_ceramics.use_cases.loads import (
    AddManyToLoad,
    AddToLoad,
    ChangeLoad,
    CorrectStepTime,
    DeleteLoad,
    ListLoads,
    MarkFired,
    RemoveFromLoad,
    SaveFiringRecord,
    StartFiring,
    StartLoad,
    ViewLoad,
)
from asmbly_ceramics.use_cases.notes import (
    EditNote,
    LoadNotes,
    NoteCounts,
    RemoveNote,
    SearchNotes,
    WriteNote,
)
from asmbly_ceramics.use_cases.photos import ViewPhoto
from asmbly_ceramics.use_cases.received import ReceivedSummary
from asmbly_ceramics.use_cases.reject import PreviewRejection, RejectDropOff, UndoRejection
from asmbly_ceramics.use_cases.settings import (
    AddCatalogItem,
    ChangeEmailSettings,
    DeleteCatalogItem,
    RecordNewElements,
    RestoreCatalogItem,
    RetireCatalogItem,
    SendTestEmail,
    SetDefaultProgram,
    SetKilnCounts,
    ViewStudio,
)
from asmbly_ceramics.use_cases.studio import CurrentStudio, ViewStudioChoices
from asmbly_ceramics.use_cases.submit import SubmitDropOff
from asmbly_ceramics.use_cases.uploads import RequestUploadSlots
from asmbly_ceramics.use_cases.view_drop_off import ViewDropOff
from asmbly_ceramics.use_cases.waiting import FindDropOffs, WaitingList
from asmbly_ceramics.web.app import WebServices, WebSettings, create_app
from asmbly_ceramics.web.console import ConsoleServices


def build_form_services(
    settings: Settings | None = None, clients: FormClients | None = None
) -> tuple[WebServices, WebSettings]:
    """The public form's use cases. Its role reads `hash-key` and `form-key` only."""
    settings = settings or Settings.from_environment()
    clients = clients or FormClients.build(settings.region)
    records = DynamoDbRecords(clients.dynamodb, settings.table_name)
    photos = S3PhotoStore(clients.s3, settings.photo_bucket)
    limiter = DynamoDbRateLimiter(clients.dynamodb, settings.table_name)
    clock = SystemClock()
    keys = SsmSecrets(clients.ssm, settings.app_env)
    hasher = KeyHasher(keys)
    # Seeds the studio from INITIAL_SENDING_ADDRESS the first time anything reads it.
    studio = CurrentStudio(records, clock, settings.initial_sending_address)
    services = WebServices(
        view_studio_choices=ViewStudioChoices(studio),
        request_upload_slots=RequestUploadSlots(photos, limiter, hasher, clock),
        submit_drop_off=SubmitDropOff(
            records,
            DynamoDbIdNumbers(clients.dynamodb, settings.table_name),
            photos,
            PillowPhotoInspector(),
            limiter,
            hasher,
            clock,
            studio,
        ),
        received_summary=ReceivedSummary(records, clock),
        clock=clock,
    )
    web_settings = WebSettings(
        site_url=settings.site_url,
        photo_upload_origin=settings.photo_upload_origin,
        version=settings.version,
        cookie_key=keys.get(SecretName.FORM_KEY),
    )
    return services, web_settings


def build_mailer(settings: Settings | None = None, clients: MailerClients | None = None) -> SendPendingEmail:
    """The outbox's sender. It never seeds the studio (its role can't write it): an email
    exists only after a submit, which read and so seeded the studio first."""
    settings = settings or Settings.from_environment()
    clients = clients or MailerClients.build(settings.region)
    records = DynamoDbRecords(clients.dynamodb, settings.table_name)
    clock = SystemClock()
    return SendPendingEmail(
        records,
        S3PhotoStore(clients.s3, settings.photo_bucket),
        SesMailer(clients.ses),
        clock,
        CurrentStudio(records, clock, settings.initial_sending_address, seed=False),
        JinjaComposer(),
    )


def build_console_services(
    settings: Settings | None = None,
    staff: StaffSignIn | None = None,
    clients: ConsoleClients | None = None,
    staff_tokens: StaffTokens | None = None,
) -> tuple[ConsoleServices, WebSettings]:
    """The console's use cases (#3 to #7, #17 and #42). Its role reads `session-key` only. The only
    email it sends itself is the test email, to the signed-in staff member; every other
    email goes through the outbox. It refuses to start when a `STAFF_*` variable is
    empty, or the session key can't be read."""
    settings = settings or Settings.from_environment()
    staff = staff or StaffSignIn.from_environment()
    clients = clients or ConsoleClients.build(settings.region)
    records = DynamoDbRecords(clients.dynamodb, settings.table_name)
    photos = S3PhotoStore(clients.s3, settings.photo_bucket)
    clock = SystemClock()
    keys = SsmSecrets(clients.ssm, settings.app_env)
    studio = CurrentStudio(records, clock, settings.initial_sending_address)
    ids = DynamoDbIdNumbers(clients.dynamodb, settings.table_name)  # load and note numbers only
    services = ConsoleServices(
        staff_tokens=staff_tokens
        or CognitoStaffTokens(
            issuer=staff.issuer, sign_in_origin=staff.sign_in_url, client_id=staff.client_id
        ),
        secrets=keys,
        clock=clock,
        studio=studio,
        site_url=settings.site_url,
        waiting_list=WaitingList(records, clock, studio),
        find_drop_offs=FindDropOffs(records, clock, studio),
        view_drop_off=ViewDropOff(records, clock, studio),
        view_photo=ViewPhoto(records, photos),
        preview_rejection=PreviewRejection(records, clock, studio, JinjaComposer()),
        reject_drop_off=RejectDropOff(records, clock, studio),
        undo_rejection=UndoRejection(records, clock),
        delete_drop_off=DeleteDropOff(records, photos, clock),
        retry_email=RetryEmail(records, clock),
        emails_needing_attention=EmailsNeedingAttention(records, clock),
        list_loads=ListLoads(records, clock),
        start_load=StartLoad(records, ids, clock, studio),
        view_load=ViewLoad(records, clock, studio),
        change_load=ChangeLoad(records, clock, studio),
        add_to_load=AddToLoad(records),
        add_many_to_load=AddManyToLoad(records),
        remove_from_load=RemoveFromLoad(records),
        start_firing=StartFiring(records, clock),
        mark_fired=MarkFired(records, clock),
        delete_load=DeleteLoad(records, clock),
        save_firing_record=SaveFiringRecord(records, clock, studio),
        correct_step_time=CorrectStepTime(records, clock),
        firing_log=FiringLog(records, clock, studio),
        write_note=WriteNote(records, ids, clock, studio),
        edit_note=EditNote(records, clock, studio),
        remove_note=RemoveNote(records, clock),
        load_notes=LoadNotes(records, studio),
        search_notes=SearchNotes(records, clock, studio),
        note_counts=NoteCounts(records, clock),
        view_studio=ViewStudio(records, studio),
        change_email_settings=ChangeEmailSettings(records, clock, studio),
        send_test_email=SendTestEmail(SesMailer(clients.ses), studio, JinjaComposer()),
        add_item=AddCatalogItem(records, clock, studio),
        retire_item=RetireCatalogItem(records, clock, studio),
        restore_item=RestoreCatalogItem(records, clock, studio),
        delete_item=DeleteCatalogItem(records, clock, studio),
        set_default_program=SetDefaultProgram(records, clock, studio),
        set_kiln_counts=SetKilnCounts(records, clock, studio),
        record_new_elements=RecordNewElements(records, clock, studio),
        weekly_counts=WeeklyCounts(records, clock, studio),
    )
    web_settings = WebSettings(
        site_url=settings.site_url,
        photo_upload_origin=settings.photo_upload_origin,
        version=settings.version,
        cookie_key=keys.get(SecretName.SESSION_KEY),
    )
    return services, web_settings


def build_closer(settings: Settings | None = None, clients: CloserClients | None = None) -> CloseFinished:
    """The daily close (#7). It sends no email and reads no secret, and never seeds the
    studio: a drop-off to close exists only after a submit seeded it."""
    settings = settings or Settings.from_environment()
    clients = clients or CloserClients.build(settings.region)
    records = DynamoDbRecords(clients.dynamodb, settings.table_name)
    clock = SystemClock()
    return CloseFinished(
        records,
        S3PhotoStore(clients.s3, settings.photo_bucket),
        clock,
        CurrentStudio(records, clock, settings.initial_sending_address, seed=False),
    )


def console_app(settings: Settings | None = None) -> Starlette:
    """The console function's app: the console's routes, `/health` and `/static`; no
    form route."""
    services, web_settings = build_console_services(settings)
    return create_app(None, web_settings, services)
