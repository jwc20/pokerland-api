import asyncio
import time
import logging
from datetime import timedelta

import aiohttp
from django.utils import timezone

from users.models import User
from utils.tasks import validate_all_subscriptions

logger = logging.getLogger(__name__)


async def fetch_url(session: aiohttp.ClientSession, url: str) -> None:
    """Asynchronously perform a GET request for a single URL."""
    try:
        async with session.get(url) as response:
            await response.text()
    except Exception as e:
        print(f"Error fetching {url}: {e}")


async def keep_hot_async(
    url: str,
    num_requests: int = 200,
    concurrent_limit: int = 50,
) -> None:
    """
    Async helper for warming up a Lambda function.

    Args:
        url: API endpoint to call
        num_requests: Total number of requests
        concurrent_limit: Maximum number of concurrent requests
    """
    async with aiohttp.ClientSession() as session:
        # Create URL list
        urls = [url] * num_requests

        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(concurrent_limit)

        # Wrapper function using the semaphore
        async def fetch_with_semaphore(url: str) -> None:
            async with semaphore:
                await fetch_url(session, url)

        # Record start time
        start_time = time.time()

        # Execute all requests concurrently
        tasks = [fetch_with_semaphore(url) for url in urls]
        await asyncio.gather(*tasks)

        # Calculate elapsed time
        elapsed_time = time.time() - start_time
        print(f"Completed {num_requests} requests in {elapsed_time:.2f} seconds")


def keep_hot_dev():
    asyncio.run(keep_hot_async(url="https://api-dev.essentory.net/env_name"))


def keep_hot_prod():
    asyncio.run(keep_hot_async(url="https://api-prod.essentory.net/env_name"))


# TODO: need testing
def cleanup_deleted_accounts():
    """
    Permanently deactivate accounts requested for deletion over 30 days ago.
    Deleted accounts older than 30 days can no longer be recovered.
    This function is scheduled to run daily at midnight.

    Returns:
        int: Number of processed accounts
    """
    # Calculate timestamp from 30 days ago
    thirty_days_ago = timezone.now() - timedelta(days=30)

    # Find accounts requested for deletion more than 30 days ago
    expired_accounts = User.objects.filter(
        deletion_requested_at__lt=thirty_days_ago, is_active=False
    )

    # Permanently deactivate expired accounts
    count = expired_accounts.count()
    if count > 0:
        print(f"Permanently deactivating {count} expired accounts")

    # Keep deletion_requested_at to prevent recovery attempts.
    # Keep records instead of deleting so accounts remain permanently inactive.
    # This behaves like full deletion to users while allowing admin restoration if needed.
    return count


# TODO: need testing
def run_subscription_validation():
    """
    Run validation for all active subscriptions.
    This function is scheduled to run daily at midnight.
    """
    logger.info("Triggering subscription validation job")
    validate_all_subscriptions()
    return "Subscription validation job triggered"


def send_scheduled_push_notifications():
    """trigger scheduled push notifications"""
    from notifications.utils import UnifiedNotificationService

    logger.info("Triggering scheduled push notifications")
    print("Triggering scheduled push notifications")

    UnifiedNotificationService().trigger_scheduled_push_notifications()
    # UnifiedNotificationService().trigger_scheduled_push_notifications_new()
    # UnifiedNotificationService().trigger_scheduled_push_notifications_contents()

    print("Scheduled push notifications triggered")
    return "Scheduled push notifications triggered"

def send_scheduled_push_notifications_contents():
    from notifications.utils import UnifiedNotificationService
    logger.info("Triggering scheduled push notifications for contents")

    UnifiedNotificationService().trigger_scheduled_push_notifications_contents()
    return "Scheduled push notifications for contents triggered"

def send_scheduled_content_notifications():
    """
    Send notifications for contents that are scheduled to be published.
    This function is called by a cron job every 5 minutes.
    """
    from django.utils import timezone
    from datetime import timedelta
    from contents.models import Content
    from notifications.utils import UnifiedNotificationService

    print("Starting scheduled content notifications check")

    logger = logging.getLogger(__name__)
    logger.info("Starting scheduled content notifications check")

    # Get current time
    now = timezone.now()
    
    # Find contents that are scheduled to be published in the last 5 minutes
    # and haven't been published yet
    contents_to_notify = Content.objects.filter(
        datetime_to_publish__isnull=False,
        datetime_to_publish__lte=now,
        datetime_to_publish__gt=now - timedelta(minutes=3),
        is_published=True,
        is_deleted=False
    ).select_related('channel', 'user')

    notification_service = UnifiedNotificationService()
    notified_count = 0

    for content in contents_to_notify:
        try:
            # Send notification for the content
            notification_service.notify_content_upload(
                content=content,
                content_type=content.content_type,
                target_type='content'
            )
            notified_count += 1
            logger.info(f"Sent notification for content {content.id}")
        except Exception as e:
            logger.error(f"Error sending notification for content {content.id}: {str(e)}")

    logger.info(f"Completed scheduled content notifications. Notified {notified_count} contents.")
    print(f"Completed scheduled content notifications. Notified {notified_count} contents.")
    return f"Notified {notified_count} contents"
