"""
Tests for django admin command `send_verification_expiry_email` in the verify_student module
"""

from datetime import datetime, timedelta

import boto
from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from mock import patch
from pytz import UTC
from student.tests.factories import UserFactory
from testfixtures import LogCapture

from common.test.utils import MockS3Mixin
from lms.djangoapps.verify_student.models import SoftwareSecurePhotoVerification
from lms.djangoapps.verify_student.tests.test_models import (
    FAKE_SETTINGS,
    mock_software_secure_post
)

LOGGER_NAME = 'lms.djangoapps.verify_student.management.commands.send_verification_expiry_email'


@patch.dict(settings.VERIFY_STUDENT, FAKE_SETTINGS)
@patch('lms.djangoapps.verify_student.models.requests.post', new=mock_software_secure_post)
class TestPopulateExpiryDate(MockS3Mixin, TestCase):
    """ Tests for django admin command `send_verification_expiry_email` in the verify_student module """

    def setUp(self):
        """ Initial set up for tests """
        super(TestPopulateExpiryDate, self).setUp()
        connection = boto.connect_s3()
        connection.create_bucket(FAKE_SETTINGS['SOFTWARE_SECURE']['S3_BUCKET'])

    def create_and_submit(self, user):
        """ Helper method that lets us create new SoftwareSecurePhotoVerifications """
        attempt = SoftwareSecurePhotoVerification(user=user)
        attempt.upload_face_image("Fake Data")
        attempt.upload_photo_id_image("More Fake Data")
        attempt.mark_ready()
        attempt.submit()
        return attempt

    def test_recent_approved_verification(self):
        """
        Test that the expiry_email_date for most recent approved and expired verification is updated.
        A user can have multiple approved and expired Software Secure Photo Verification over the year
        Only the most recent is considered for course verification
        """
        user = UserFactory.create()
        outdated_verification = self.create_and_submit(user)
        outdated_verification.status = 'approved'
        outdated_verification.expiry_date = datetime.now(UTC) - timedelta(days=1)
        outdated_verification.save()

        recent_verification = self.create_and_submit(user)
        recent_verification.status = 'approved'
        recent_verification.expiry_date = datetime.now(UTC) - timedelta(days=1)
        recent_verification.save()

        call_command('send_verification_expiry_email')

        # Check that the expiry_email_date is not set for the outdated expired verification
        expiry_email_date = SoftwareSecurePhotoVerification.objects.get(
            updated_at=outdated_verification.updated_at
        ).expiry_email_date
        self.assertEqual(expiry_email_date, None)

    def test_send_verification_expiry_email(self):
        user = UserFactory.create()
        verification = self.create_and_submit(user)
        verification.status = 'approved'
        verification.expiry_date = datetime.now(UTC) - timedelta(days=1)
        verification.save()

        call_command('send_verification_expiry_email')

        expected_date = datetime.now(UTC) + timedelta(days=15)
        attempt = SoftwareSecurePhotoVerification.objects.get(user_id=verification.user_id)
        self.assertEquals(attempt.expiry_email_date.date(), expected_date.date())
        self.assertEqual(len(mail.outbox), 1)

    def test_no_verification_found(self):
        """
        Test that if no approved and expired verifications are found the management command terminates gracefully
        """
        with LogCapture(LOGGER_NAME) as logger:
            call_command('send_verification_expiry_email')
            logger.check(
                (LOGGER_NAME,
                 'INFO', "IndexError: No approved expired entries found in SoftwareSecurePhotoVerification")
            )
