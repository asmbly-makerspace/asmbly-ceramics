"""The composition root: the AWS adapters and the use cases each deployed function runs,
built from `Settings`.

Each function's clients are built once per container (`adapters.aws.clients`'
`FormClients.build` and `MailerClients.build`, cached), with their configs; the tests
pass stubbed clients instead. Nothing here, and nothing it imports, imports
`web.local`: that module builds the in-memory fakes and is only for a laptop. Phase 8
adds `build_console_services` and phase 9 `build_closer`.
"""

from asmbly_ceramics.adapters.aws.clients import FormClients, MailerClients
from asmbly_ceramics.adapters.aws.ids import DynamoDbIdNumbers
from asmbly_ceramics.adapters.aws.mailer import SesMailer
from asmbly_ceramics.adapters.aws.photos import S3PhotoStore
from asmbly_ceramics.adapters.aws.rate_limit import DynamoDbRateLimiter
from asmbly_ceramics.adapters.aws.records import DynamoDbRecords
from asmbly_ceramics.adapters.aws.secrets import SsmSecrets
from asmbly_ceramics.adapters.clock import SystemClock
from asmbly_ceramics.adapters.images import PillowPhotoInspector
from asmbly_ceramics.mail.compose import JinjaComposer
from asmbly_ceramics.ports.secrets import SecretName
from asmbly_ceramics.settings import Settings
from asmbly_ceramics.use_cases.emails import SendPendingEmail
from asmbly_ceramics.use_cases.keys import KeyHasher
from asmbly_ceramics.use_cases.received import ReceivedSummary
from asmbly_ceramics.use_cases.studio import CurrentStudio, ViewStudioChoices
from asmbly_ceramics.use_cases.submit import SubmitDropOff
from asmbly_ceramics.use_cases.uploads import RequestUploadSlots
from asmbly_ceramics.web.app import WebServices, WebSettings


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
