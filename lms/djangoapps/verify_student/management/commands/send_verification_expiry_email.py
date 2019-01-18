"""
Django admin command to send verification expiry email to learners
"""
import logging
import time
from datetime import datetime, timedelta
from smtplib import SMTPException

from celery import task
from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils.translation import ugettext as _
from edxmako.shortcuts import render_to_string


from lms.djangoapps.verify_student.models import SoftwareSecurePhotoVerification
from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers

ACE_ROUTING_KEY = getattr(settings, 'ACE_ROUTING_KEY', None)
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    This command sends email to learners for which the Software Secure Photo Verification has expired.

    The expiry email is sent when the date represented by SoftwareSecurePhotoVerification's field `expiry_date`
    is in the past implicating that the verification is no longer valid.
    If the email is already sent indicated by field `expiry_email_date` then resend after the specified number of
    days given as command argument `--resend_days` (default = 15 days)

    The task is performed in batches with maximum number of rows to process given in argument `batch_size` and the
    delay between batches is indicated by `sleep_time`

    Default values:
        `resend_days` = 15 days
        `batch_size` = 1000 rows
        `sleep_time` = 10 seconds
    template used for email: 'emails/verification_expiry_email.txt.txt'

    Example usage:
        $ ./manage.py lms send_verification_expiry_email --resend_days=30 --batch_size=2000 --sleep_time=5
    OR
        $ ./manage.py lms send_verification_expiry_email
    """
    help = 'Send email to users for which Software Secure Photo Verification has expired'

    def add_arguments(self, parser):
        parser.add_argument(
            '-d', '--resend_days',
            action='store',
            dest='resend_days',
            type=int,
            default=15,
            help='Desired days after which the email will be resent to learners with expired verification'
        )
        parser.add_argument(
            '--batch_size',
            action='store',
            dest='batch_size',
            type=int,
            default=1000,
            help='Maximum number of database rows to process. '
                 'This helps avoid locking the database while updating large amount of data.')
        parser.add_argument(
            '--sleep_time',
            action='store',
            dest='sleep_time',
            type=int,
            default=10,
            help='Sleep time in seconds between update of batches')

    def __init__(self, *args, **kwargs):
        super(Command, self).__init__(*args, **kwargs)
        self.sspv = SoftwareSecurePhotoVerification.objects.filter(status='approved',
                                                                   expiry_date__lt=datetime.utcnow()
                                                                   ).order_by('-user_id')
        subject = _("Your {platform_name} Verification has Expired").format(
            platform_name=settings.PLATFORM_NAME
        )
        self.verification_expiry_email_vars = {
            'platform_name': settings.PLATFORM_NAME,
            'lms_verification_link': '{}{}'.format(settings.LMS_ROOT_URL, reverse("verify_student_reverify")),
            'help_center_link': settings.ID_VERIFICATION_SUPPORT_LINK
        }
        self.email_context = {
            'subject': subject,
            'template': 'emails/verification_expiry_email.txt',
        }

    def handle(self, *args, **options):
        """
        Handler for the command
        """
        resend_days = options['resend_days']
        batch_size = options['batch_size']
        sleep_time = options['sleep_time']

        date_resend_days_ago = datetime.utcnow() - timedelta(days=resend_days)

        try:
            max_user_id = self.sspv[0].user_id
            batch_start = self.sspv.reverse()[0].user_id
            batch_stop = batch_start + batch_size
        except IndexError:
            logger.info("IndexError: No approved expired entries found in SoftwareSecurePhotoVerification")
            return

        while batch_start <= max_user_id:
            batch_queryset = self.sspv.filter(user_id__gte=batch_start, user_id__lt=batch_stop)
            users = batch_queryset.order_by().values('user_id').distinct()

            for user in users:
                verification = self.find_recent_verification(user['user_id'])
                if not verification.expiry_email_date or verification.expiry_email_date < date_resend_days_ago:
                    user = User.objects.get(id=verification.user_id)
                    self.verification_expiry_email_vars['full_name'] = user.profile.name
                    self.email_context['email_vars'] = self.verification_expiry_email_vars
                    self.email_context['email'] = user.email

                    send_verification_expiry_email.delay(self.email_context, verification, resend_days)

            if batch_stop < max_user_id:
                time.sleep(sleep_time)

            batch_start = batch_stop
            batch_stop += batch_size

    def find_recent_verification(self, user_id):
        """
        Find the most recent expired verification for user.
        """
        return self.sspv.filter(
            user_id=user_id
        ).latest('updated_at')


@task(routing_key=ACE_ROUTING_KEY)
def send_verification_expiry_email(context, verification, days):
    """
    Spins a task to send verification expiry email to the learner
    If the email is successfully sent change the expiry_email_date to reflect when the
    email was sent
    """
    subject = context.get('subject')
    message = render_to_string(context.get('template'), context.get('email_vars'))
    from_addr = configuration_helpers.get_value(
        'email_from_address',
        settings.DEFAULT_FROM_EMAIL
    )
    dest_addr = context.get('email')

    try:
        send_mail(
            subject,
            message,
            from_addr,
            [dest_addr],
            fail_silently=False
        )
        verification.expiry_email_date = datetime.utcnow() + timedelta(days=days)
        verification.save()
    except SMTPException:
        logger.warning("Failure in sending verification expiry e-mail to %s", dest_addr)
