from django.db import models

# Constants
CHANNEL_MAX_MEMBERS = 100


class ChannelWaitlistStatusChoices(models.TextChoices):
    waiting = "WAITING", "대기중"
    subscribed = "SUBSCRIBED", "구독 완료"
    cancelled = "CANCELLED", "취소됨"


class LoginIdDuplicateCheckResultChoices(models.TextChoices):
    duplicated = "DUPLICATED", "중복"
    unique = "UNIQUE", "유일"


class ChannelManagerMappingManagerTypeChoices(models.TextChoices):
    owner = "OWNER", "채널 주인 계정"
    staff = "STAFF", "채널 스태프 계정"


class ExternalLinkTypeChoices(models.TextChoices):
    youtube = "YOUTUBE", "유튜브"
    instagram = "INSTAGRAM", "인스타그램"
    facebook = "FACEBOOK", "페이스북"
    x = "X", "X(구, 트위터)"
    thread = "THREAD", "스레드"
    homepage = "HOMEPAGE", "홈페이지"


class ContentTypeChoices(models.TextChoices):
    video = "VIDEO", "비디오"
    audio = "AUDIO", "오디오"
    article = "ARTICLE", "아티클"
    image = "IMAGE", "사진"


class SubscriptionTypeChoices(models.TextChoices):
    yearly = "YEARLY", "연간"
    monthly = "MONTHLY", "월간"


class CurrencyChoices(models.TextChoices):
    krw = "KRW", "원"
    usd = "UDS", "달러"
    eur = "EUR", "유로"


class SubscriptionEventTypeChoices(models.TextChoices):
    start = "START", "구독 시작"
    extend = "EXTEND", "구독 연장"
    cancel_by_customer = "CANCEL_BY_CUSTOMER", "구독 취소(고객)"
    cancel_by_channel_manager = "CANCEL_BY_CHANNEL_MANAGER", "구독 취소(채널 운영자)"
    pending = "PENDING", "보류"
    expired = "EXPIRED", "구독 기간 만료"


class ImageTypeChoices(models.TextChoices):
    user_profile_image = "USER_PROFILE_IMAGE", "사용자 프로필 이미지"
    channel_cover_image = "CHANNEL_COVER_IMAGE", "채널 배경 이미지"
    channel_community_cover_image = (
        "CHANNEL_COMMUNITY_COVER_IMAGE",
        "채널 커뮤니티 배경 이미지",
    )
    channel_logo_image = "CHANNEL_LOGO_IMAGE", "채널 로고 이미지"
    content_image = "CONTENT_IMAGE", "컨텐츠 이미지"
    content_thumbnail_image = "CONTENT_THUMBNAIL_IMAGE", "컨텐츠 썸네일 이미지"
    feed_image = "FEED_IMAGE", "피드 이미지"
    community_post_image = "COMMUNITY_POST_IMAGE", "커뮤니티 게시글 이미지"
    comment_image = "COMMENT_IMAGE", "댓글 이미지"
    announcement_image = "ANNOUNCEMENT_IMAGE", "공지사항 이미지"


class AudioTypeChoices(models.TextChoices):
    content_audio = "CONTENT_AUDIO", "컨텐츠 오디오"


class FcmDeviceOsTypeChoices(models.TextChoices):
    ios = "IOS", "IOS"
    android = "ANDROID", "ANDROID"
    web = "WEB", "WEB"


class FcmPushNotificationStatusChoices(models.TextChoices):
    success = "SUCCESS", "성공"
    fail = "FAIL", "실패"
    invalid_token = "INVALID_TOKEN", "유효하지 않은 토큰"


# TODO: remove?
class CommunityPostAuthorTypeChoices(models.TextChoices):
    by_customer = "BY_CUSTOMER", "고객이 씀"
    by_creator = "BY_CREATOR", "크리에이터가 씀"


class PaymentStatusChoices(models.TextChoices):
    pending = "pending", "대기중"
    completed = "completed", "완료"
    failed = "failed", "실패"
    cancelled = "cancelled", "취소"
    refunded = "refunded", "환불"


class PurchaseVerificationStateChoices(models.TextChoices):
    pending = "PENDING", "검증 대기중"
    verified = "VERIFIED", "검증됨"
    failed = "FAILED", "검증 실패"
    consumed = "CONSUMED", "소비됨"


# TODO
class SubscriptionStatusChoices(models.TextChoices):
    active = "ACTIVE", "활성"
    inactive = "INACTIVE", "비활성"
    expired = "EXPIRED", "만료됨"
    cancelled = "CANCELLED", "취소됨"
    pending = "PENDING", "대기중"
    grace_period = "GRACE_PERIOD", "유예기간"
    on_hold = "ON_HOLD", "보류중"


# TODO: remove? (DUPLICATE)
class SubscriptionPlanPricePlatformChoices(models.TextChoices):
    apple = "apple", "App Store"
    google = "google", "Google Play Store"


class PaymentPlatformChoices(models.TextChoices):
    apple = "apple", "App Store"
    google = "google", "Google Play Store"


class PaymentTypeChoices(models.TextChoices):
    subscription = "subscription", "구독"
    one_time = "one_time", "일회성"


class AppleReceiptStatusChoices(models.IntegerChoices):
    SUCCESS = 0, "성공"
    INVALID_JSON = 21000, "App Store에서 읽을 수 없는 JSON"
    MISSING_RECEIPT_DATA = 21002, "receipt-data 속성이 잘못되었거나 누락"
    AUTHENTICATION_ERROR = 21003, "영수증이 인증되지 않음"
    SHARED_SECRET_MISMATCH = 21004, "공유된 비밀키가 일치하지 않음"
    SERVER_UNAVAILABLE = 21005, "영수증 서버 일시적 사용 불가"
    SUBSCRIPTION_EXPIRED = 21006, "영수증 유효하지만 구독 만료"
    SANDBOX_RECEIPT_TO_PROD = 21007, "샌드박스 영수증을 프로덕션에 보냄"
    PROD_RECEIPT_TO_SANDBOX = 21008, "프로덕션 영수증을 샌드박스에 보냄"


class ContentListSortOptionChoices(models.TextChoices):
    recent = "recent", "최신순"
    most_liked = "most_liked", "인기순"


class CommunityPostListSortOptionChoices(models.TextChoices):
    recent = "recent", "최신순"
    most_liked = "most_liked", "인기순"


class SocialLoginProviderChoices(models.TextChoices):
    google = "google", "구글"
    apple = "apple", "애플"


class ReportCommentReplyTypeChoices(models.TextChoices):
    comment = "COMMENT", "댓글"
    reply = "REPLY", "대댓글"


class ReportTypeChoices(models.TextChoices):
    spam = "SPAM", "스팸"
    inappropriate = "INAPPROPRIATE", "부적절한 콘텐츠"
    sexual = "SEXUAL", "성적인 콘텐츠"
    violent = "VIOLENT", "폭력 또는 혐오스러운 콘텐츠"
    hate = "HATE", "증오 및 학대 콘텐츠"
    harmful = "HARMFUL", "유해하거나 위험한 콘텐츠"
    illegal = "ILLEGAL", "불법적인 콘텐츠"
    copyright = "COPYRIGHT", "저작권 침해"


class FcmPushNotificationTypeChoices(models.TextChoices):
    # Content notifications
    content_upload = "CONTENT_UPLOAD", "콘텐츠 업로드 알림"
    feed_upload = "FEED_UPLOAD", "피드 업로드 알림"
    community_post_upload = "COMMUNITY_POST_UPLOAD", "커뮤니티 게시글 업로드 알림"
    announcement_upload = "ANNOUNCEMENT_UPLOAD", "공지사항 업로드 알림"

    # Subscription notifications
    subscription_complete = "SUBSCRIPTION_COMPLETE", "구독 완료 알림"
    subscription_cancel = "SUBSCRIPTION_CANCEL", "구독 취소 알림"

    # Interaction notifications (for content, feed, and community posts)
    comment_on_my_content = (
        "COMMENT_ON_MY_CONTENT",
        "내가 업로드한 콘텐츠에 댓글 작성 알림",
    )
    # Interaction notifications (for content, feed, and community posts)
    like_on_my_content = "LIKE_ON_MY_CONTENT", "내가 업로드한 콘텐츠에 좋아요 알림"

    # The following types are not currently used but kept for potential future use
    # or backward compatibility with existing data
    invite_on_my_content = "INVITE_ON_MY_CONTENT", "내가 업로드한 콘텐츠에 초대 알림"
    member_add_remove_on_my_channel = (
        "MEMBER_ADD_REMOVE_ON_MY_CHANNEL",
        "내 채널에 멤버 추가/제거 알림",
    )


class NotificationTargetTypeChoices(models.TextChoices):
    content_video = "content_video", "비디오 콘텐츠"
    content_audio = "content_audio", "오디오 콘텐츠"
    content_article = "content_article", "아티클 콘텐츠"
    content_image = "content_image", "이미지 콘텐츠"
    feed = "feed", "피드"
    community_post = "community_post", "커뮤니티 게시글"
    announcement = "announcement", "공지사항"
    content_comment = "content_comment", "콘텐츠 댓글"
    feed_comment = "feed_comment", "피드 댓글"
    community_post_comment = "community_post_comment", "커뮤니티 게시글 댓글"
    announcement_comment = "announcement_comment", "공지사항 댓글"
    channels = "channels", "채널"
    subscriptions = "subscriptions", "구독"
