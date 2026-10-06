"""Constants for the Amazon Bestellungen integration."""

from __future__ import annotations

DOMAIN = "amazon_bestellungen"

CONF_DOMAIN = "amazon_domain"
CONF_OTP_SECRET = "otp_secret"
CONF_RETENTION_DAYS = "retention_days"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_MAX_PAGES = "max_pages"

DEFAULT_DOMAIN = "amazon.de"
DEFAULT_RETENTION_DAYS = 7
DEFAULT_SCAN_INTERVAL = 30  # minutes
DEFAULT_MAX_PAGES = 3

AMAZON_DOMAINS = [
    "amazon.de",
    "amazon.at",
    "amazon.com",
    "amazon.co.uk",
    "amazon.fr",
    "amazon.it",
    "amazon.es",
    "amazon.nl",
]

STORAGE_VERSION = 1
