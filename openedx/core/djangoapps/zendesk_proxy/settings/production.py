""" Production settings for zendesk proxy."""


def plugin_settings(settings):
    settings.ZENDESK_URL = settings.get('ZENDESK_URL', settings.ZENDESK_URL)
    settings.ZENDESK_OAUTH_ACCESS_TOKEN = settings.get("ZENDESK_OAUTH_ACCESS_TOKEN")
