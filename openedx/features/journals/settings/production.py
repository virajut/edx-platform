'''AWS Settings for Journals'''


def plugin_settings(settings):
    """
    Settings for Production
    """
    settings.JOURNALS_URL_ROOT = settings.get('JOURNALS_URL_ROOT', settings.JOURNALS_URL_ROOT)
    settings.JOURNALS_FRONTEND_URL = settings.get('JOURNALS_FRONTEND_URL', settings.JOURNALS_FRONTEND_URL)
    settings.JOURNALS_API_URL = settings.get('JOURNALS_API_URL', settings.JOURNALS_API_URL)
    settings.COURSE_CATALOG_URL_BASE = settings.get(
        'COURSE_CATALOG_URL_BASE', settings.COURSE_CATALOG_URL_BASE)
