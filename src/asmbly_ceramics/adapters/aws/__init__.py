"""The AWS adapters: each port's implementation on DynamoDB, S3, SES v2, Cognito's
public endpoints and SSM Parameter Store.

Each takes its boto3 client (or plain values) in its constructor; nothing creates a
client at import. Phase 7's composition root builds them. Every AWS failure goes through
`errors`: logged and raised by its error code, never by AWS's message, which can quote
what was sent.
"""
