import time
import logging

from zappa.asynchronous import task
from django.conf import settings

logger = logging.getLogger(__name__)


@task
def dummy_sleep():
    time.sleep(1)


@task
def validate_all_subscriptions():
    """Validate all active subscriptions"""
    from payments.iap_service import IAPService
    
    batch_size = getattr(settings, 'IAP_VALIDATION_BATCH_SIZE', 100)
    
    logger.info("Starting periodic subscription validation task")
    
    try:
        iap_service = IAPService()
        iap_service.validate_all_active_subscriptions(batch_size=batch_size)
        logger.info("Subscription validation task completed successfully")
    except Exception as e:
        logger.error(f"Subscription validation task failed: {str(e)}")
        # Don't raise the exception to ensure the task doesn't fail completely
