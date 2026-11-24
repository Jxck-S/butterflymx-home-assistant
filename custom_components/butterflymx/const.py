"""Constants for the ButterflyMX integration."""

from datetime import timedelta

DOMAIN = "butterflymx"
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_TOKENS = "tokens"
CONF_CODE = "code"
CONF_RESEND = "resend"

# One small GraphQL request per tenant; ButterflyMX allows 350 a minute.
# Short enough that a new call shows up while the visitor is still there.
SCAN_INTERVAL = timedelta(seconds=30)

# Instant call alerts through a ButterflyMX tenant webhook integration
CONF_WEBHOOK_ID = "webhook_id"
CONF_WEBHOOK_SECRET = "webhook_secret"
CONF_WEBHOOK_URL = "webhook_url"
CONF_BMX_INTEGRATIONS = "bmx_integrations"  # {tenant graphql id: ButterflyMX integration id}
WEBHOOK_SECRET_HEADER = "X-Webhook-Secret"
WEBHOOK_TENANT_PARAM = "tenant"
SIGNAL_WEBHOOK_CALL = "butterflymx_webhook_call_{entry_id}_{tenant_id}"
