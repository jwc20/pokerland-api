from django.db import models

# Constants
CHANNEL_MAX_MEMBERS = 100


class ChannelWaitlistStatusChoices(models.TextChoices):
    waiting = "WAITING", "Waiting"
    subscribed = "SUBSCRIBED", "Subscribed"
    cancelled = "CANCELLED", "Cancelled"


class LoginIdDuplicateCheckResultChoices(models.TextChoices):
    duplicated = "DUPLICATED", "Duplicated"
    unique = "UNIQUE", "Unique"


class ChannelManagerMappingManagerTypeChoices(models.TextChoices):
    owner = "OWNER", "Channel owner account"
    staff = "STAFF", "Channel staff account"


class ExternalLinkTypeChoices(models.TextChoices):
    youtube = "YOUTUBE", "YouTube"
    instagram = "INSTAGRAM", "Instagram"
    facebook = "FACEBOOK", "Facebook"
    x = "X", "X (formerly Twitter)"
    thread = "THREAD", "Threads"
    homepage = "HOMEPAGE", "Homepage"


class ContentTypeChoices(models.TextChoices):
    video = "VIDEO", "Video"
    audio = "AUDIO", "Audio"
    article = "ARTICLE", "Article"
    image = "IMAGE", "Image"


class SubscriptionTypeChoices(models.TextChoices):
    yearly = "YEARLY", "Yearly"
    monthly = "MONTHLY", "Monthly"


class CurrencyChoices(models.TextChoices):
    krw = "KRW", "KRW"
    usd = "UDS", "USD"
    eur = "EUR", "EUR"


class SubscriptionEventTypeChoices(models.TextChoices):
    start = "START", "Subscription started"
    extend = "EXTEND", "Subscription extended"
    cancel_by_customer = "CANCEL_BY_CUSTOMER", "Cancelled by customer"
    cancel_by_channel_manager = "CANCEL_BY_CHANNEL_MANAGER", "Cancelled by channel manager"
    pending = "PENDING", "Pending"
    expired = "EXPIRED", "Subscription expired"


class ImageTypeChoices(models.TextChoices):
    user_profile_image = "USER_PROFILE_IMAGE", "User profile image"
    channel_cover_image = "CHANNEL_COVER_IMAGE", "Channel cover image"
    channel_community_cover_image = (
        "CHANNEL_COMMUNITY_COVER_IMAGE",
        "Channel community cover image",
    )
    channel_logo_image = "CHANNEL_LOGO_IMAGE", "Channel logo image"
    content_image = "CONTENT_IMAGE", "Content image"
    content_thumbnail_image = "CONTENT_THUMBNAIL_IMAGE", "Content thumbnail image"
    feed_image = "FEED_IMAGE", "Feed image"
    community_post_image = "COMMUNITY_POST_IMAGE", "Community post image"
    comment_image = "COMMENT_IMAGE", "Comment image"
    announcement_image = "ANNOUNCEMENT_IMAGE", "Announcement image"


class AudioTypeChoices(models.TextChoices):
    content_audio = "CONTENT_AUDIO", "Content audio"


class FcmDeviceOsTypeChoices(models.TextChoices):
    ios = "IOS", "IOS"
    android = "ANDROID", "ANDROID"
    web = "WEB", "WEB"


class FcmPushNotificationStatusChoices(models.TextChoices):
    success = "SUCCESS", "Success"
    fail = "FAIL", "Failure"
    invalid_token = "INVALID_TOKEN", "Invalid token"


# TODO: remove?
class CommunityPostAuthorTypeChoices(models.TextChoices):
    by_customer = "BY_CUSTOMER", "Written by customer"
    by_creator = "BY_CREATOR", "Written by creator"


class PaymentStatusChoices(models.TextChoices):
    pending = "pending", "Pending"
    completed = "completed", "Completed"
    failed = "failed", "Failed"
    cancelled = "cancelled", "Cancelled"
    refunded = "refunded", "Refunded"


class PurchaseVerificationStateChoices(models.TextChoices):
    pending = "PENDING", "Verification pending"
    verified = "VERIFIED", "Verified"
    failed = "FAILED", "Verification failed"
    consumed = "CONSUMED", "Consumed"


# TODO
class SubscriptionStatusChoices(models.TextChoices):
    active = "ACTIVE", "Active"
    inactive = "INACTIVE", "Inactive"
    expired = "EXPIRED", "Expired"
    cancelled = "CANCELLED", "Cancelled"
    pending = "PENDING", "Pending"
    grace_period = "GRACE_PERIOD", "Grace period"
    on_hold = "ON_HOLD", "On hold"


# TODO: remove? (DUPLICATE)
class SubscriptionPlanPricePlatformChoices(models.TextChoices):
    apple = "apple", "App Store"
    google = "google", "Google Play Store"


class PaymentPlatformChoices(models.TextChoices):
    apple = "apple", "App Store"
    google = "google", "Google Play Store"


class PaymentTypeChoices(models.TextChoices):
    subscription = "subscription", "Subscription"
    one_time = "one_time", "One-time"


class AppleReceiptStatusChoices(models.IntegerChoices):
    SUCCESS = 0, "Success"
    INVALID_JSON = 21000, "Unreadable JSON for App Store"
    MISSING_RECEIPT_DATA = 21002, "receipt-data attribute is malformed or missing"
    AUTHENTICATION_ERROR = 21003, "Receipt could not be authenticated"
    SHARED_SECRET_MISMATCH = 21004, "Shared secret does not match"
    SERVER_UNAVAILABLE = 21005, "Receipt server temporarily unavailable"
    SUBSCRIPTION_EXPIRED = 21006, "Receipt valid but subscription expired"
    SANDBOX_RECEIPT_TO_PROD = 21007, "Sandbox receipt sent to production"
    PROD_RECEIPT_TO_SANDBOX = 21008, "Production receipt sent to sandbox"


class ContentListSortOptionChoices(models.TextChoices):
    recent = "recent", "Most recent"
    most_liked = "most_liked", "Most liked"


class CommunityPostListSortOptionChoices(models.TextChoices):
    recent = "recent", "Most recent"
    most_liked = "most_liked", "Most liked"


class SocialLoginProviderChoices(models.TextChoices):
    google = "google", "Google"
    apple = "apple", "Apple"


class ReportCommentReplyTypeChoices(models.TextChoices):
    comment = "COMMENT", "Comment"
    reply = "REPLY", "Reply"


class ReportTypeChoices(models.TextChoices):
    spam = "SPAM", "Spam"
    inappropriate = "INAPPROPRIATE", "Inappropriate content"
    sexual = "SEXUAL", "Sexual content"
    violent = "VIOLENT", "Violent or hateful content"
    hate = "HATE", "Hate and abusive content"
    harmful = "HARMFUL", "Harmful or dangerous content"
    illegal = "ILLEGAL", "Illegal content"
    copyright = "COPYRIGHT", "Copyright infringement"


class FcmPushNotificationTypeChoices(models.TextChoices):
    # Content notifications
    content_upload = "CONTENT_UPLOAD", "Content upload notification"
    feed_upload = "FEED_UPLOAD", "Feed upload notification"
    community_post_upload = "COMMUNITY_POST_UPLOAD", "Community post upload notification"
    announcement_upload = "ANNOUNCEMENT_UPLOAD", "Announcement upload notification"

    # Subscription notifications
    subscription_complete = "SUBSCRIPTION_COMPLETE", "Subscription completed notification"
    subscription_cancel = "SUBSCRIPTION_CANCEL", "Subscription cancelled notification"

    # Interaction notifications (for content, feed, and community posts)
    comment_on_my_content = (
        "COMMENT_ON_MY_CONTENT",
        "Comment notification on my uploaded content",
    )
    # Interaction notifications (for content, feed, and community posts)
    like_on_my_content = "LIKE_ON_MY_CONTENT", "Like notification on my uploaded content"

    # The following types are not currently used but kept for potential future use
    # or backward compatibility with existing data
    invite_on_my_content = "INVITE_ON_MY_CONTENT", "Invite notification on my uploaded content"
    member_add_remove_on_my_channel = (
        "MEMBER_ADD_REMOVE_ON_MY_CHANNEL",
        "Member add/remove notification on my channel",
    )


class NotificationTargetTypeChoices(models.TextChoices):
    content_video = "content_video", "Video content"
    content_audio = "content_audio", "Audio content"
    content_article = "content_article", "Article content"
    content_image = "content_image", "Image content"
    feed = "feed", "Feed"
    community_post = "community_post", "Community post"
    announcement = "announcement", "Announcement"
    content_comment = "content_comment", "Content comment"
    feed_comment = "feed_comment", "Feed comment"
    community_post_comment = "community_post_comment", "Community post comment"
    announcement_comment = "announcement_comment", "Announcement comment"
    channels = "channels", "Channel"
    subscriptions = "subscriptions", "Subscription"
