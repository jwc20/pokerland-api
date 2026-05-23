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
    """단일 URL에 대한 GET 요청을 비동기적으로 수행"""
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
    Lambda 함수를 웜업하기 위한 비동기 함수

    Args:
        url: 호출할 API endpoint
        num_requests: 총 요청 수
        concurrent_limit: 동시에 처리할 최대 요청 수
    """
    async with aiohttp.ClientSession() as session:
        # URL 리스트 생성
        urls = [url] * num_requests

        # 동시성 제한을 위한 세마포어 생성
        semaphore = asyncio.Semaphore(concurrent_limit)

        # 세마포어를 사용하는 래퍼 함수
        async def fetch_with_semaphore(url: str) -> None:
            async with semaphore:
                await fetch_url(session, url)

        # 시작 시간 기록
        start_time = time.time()

        # 모든 요청을 동시에 실행
        tasks = [fetch_with_semaphore(url) for url in urls]
        await asyncio.gather(*tasks)

        # 총 소요 시간 계산
        elapsed_time = time.time() - start_time
        print(f"Completed {num_requests} requests in {elapsed_time:.2f} seconds")


def keep_hot_dev():
    asyncio.run(keep_hot_async(url="https://api-dev.essentory.net/env_name"))


def keep_hot_prod():
    asyncio.run(keep_hot_async(url="https://api-prod.essentory.net/env_name"))


# TODO: need testing
def cleanup_deleted_accounts():
    """
    30일이 지난 삭제 요청된 계정을 영구적으로 비활성화합니다.
    삭제 요청된 계정 중 30일이 지난 계정은 더 이상 복구할 수 없습니다.
    이 함수는 매일 자정에 실행되도록 예약됩니다.

    Returns:
        int: 처리된 계정 수
    """
    # 30일 이전의 시간 계산
    thirty_days_ago = timezone.now() - timedelta(days=30)

    # 30일 이전에 삭제 요청된 계정 찾기
    expired_accounts = User.objects.filter(
        deletion_requested_at__lt=thirty_days_ago, is_active=False
    )

    # 영구적으로 계정 비활성화
    count = expired_accounts.count()
    if count > 0:
        print(f"Permanently deactivating {count} expired accounts")

    # deletion_requested_at 필드를 유지하여 복구 시도를 방지함
    # 실제 레코드는 삭제하지 않고 영구적으로 비활성 상태로 유지
    # 이 방식으로 사용자는 계정이 완전히 삭제되었다고 인식하지만
    # 필요한 경우 관리자가 수동으로 복구할 수 있음
    return count


# TODO: need testing
def run_subscription_validation():
    """
    모든 활성 구독에 대해 유효성 검증을 실행합니다.
    이 함수는 매일 자정에 실행되도록 예약됩니다.
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
