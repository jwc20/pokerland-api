from rest_framework import status
from rest_framework.exceptions import APIException

from utils.commons import CustomAPIException


class InvalidChannelManager(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "invalid_channel_manager"
    swagger_description = "채널 관리자가 아닙니다"


class ChannelDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "channel_does_not_exist"
    swagger_description = "채널이 존재하지 않습니다"


class ContentDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "content_does_not_exist"
    swagger_description = "해당 컨텐츠가 없습니다."


class CommunityPostDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "community_post_does_not_exist"
    swagger_description = "해당 커뮤니티 게시물이 없습니다."


class NotSubscribingChannel(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "not_subscribing_channel"
    swagger_description = "구독 중인 채널이 아닙니다"


class AlreadyEnrolledEmail(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "already_enrolled_login_id"
    swagger_description = "이미 등록된 login_id"


class NotEnrolledEmail(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "not_enrolled_login_id"
    swagger_description = "등록되지 않은 login_id"


class InvalidLoginInfo(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "invalid_login_info"
    swagger_description = "login 정보가 올바르지 않습니다"
    
class SocialLoginIdentifierNotFound(CustomAPIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "social_login_identifier_not_found"
    swagger_description = "소셜 로그인 검증 정보를 찾을 수 없습니다."
    
class SocialUserExists(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "social_user_exists"
    swagger_description = "이미 소셜 계정이 존재합니다"

class SocialAccessTokenExpired(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "social_access_token_expired"
    swagger_description = "소셜 계정 접근 토큰이 만료되었습니다"

class TokenAuthenticationFailed(CustomAPIException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "authentication_failed"
    swagger_description = "토큰 인증에 실패하였습니다 (모든 Token 인증에서 발생 가능)"


class NotMyCommunityPost(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "not_my_community_post"
    swagger_description = "사용자가 작성한 커뮤니티 게시글이 아닙니다"


class CommunityPostCommentDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "community_post_comment_does_not_exist"
    swagger_description = "커뮤니티 게시글 댓글이 존재하지 않습니다"


class CommunityPostCommentReplyDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "community_post_comment_reply_does_not_exist"
    swagger_description = "커뮤니티 게시글 댓글 대댓글이 존재하지 않습니다"


class NotMyFeed(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "not_my_feed"
    swagger_description = "사용자가 작성한 피드가 아닙니다"


class FeedCommentDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "feed_comment_does_not_exist"
    swagger_description = "피드 댓글이 존재하지 않습니다"


class FeedCommentReplyDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "feed_comment_reply_does_not_exist"
    swagger_description = "피드 댓글 대댓글이 존재하지 않습니다"


class FeedDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "feed_does_not_exist"
    swagger_description = "해당 피드가 없습니다."


class ContentCommentDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "content_comment_does_not_exist"
    swagger_description = "해당 게시글 댓글이 없습니다."


class ContentCommentReplyDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "content_comment_reply_does_not_exist"
    swagger_description = "해당 게시글 대댓글이 없습니다."


class AnnouncementDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "announcement_does_not_exist"
    swagger_description = "해당 공지사항이 없습니다."


class AnnouncementCommentDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "announcement_comment_does_not_exist"
    swagger_description = "공지사항 댓글이 존재하지 않습니다."


class AnnouncementCommentReplyDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "announcement_comment_reply_does_not_exist"
    swagger_description = "공지사항 댓글 대댓글이 존재하지 않습니다."


class NotMyAnnouncement(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "not_my_announcement"
    swagger_description = "자신의 공지사항이 아닙니다."


class ApplePaymentVerificationFailed(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "apple_payment_verification_failed"
    swagger_description = "애플 결제 검증 실패"


class AppleReceiptValidationFailed(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "apple_receipt_valiation_failed"
    swagger_description = "애플 영수증 검증 실패"


class AndroidPaymentVerificationFailed(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "android_payment_verification_failed"
    swagger_description = "안드로이드 결제 검증 실패"


class PurchaseAcknowledgementFailed(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "purchase_acknowledgement_failed"
    swagger_description = "구매 승인에 실패했습니다"


class DuplicatePurchaseError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "duplicate_purchase"
    swagger_description = "이미 처리된 구매입니다"


class PurchaseVerificationFailed(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "purchase_verification_failed"
    swagger_description = "구매 검증에 실패했습니다"


class AuthTokenDeleteFailed(Exception):
    pass


class InvalidArguments(Exception):
    pass


class EmailVerificationCodeExpired(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "email_verification_code_expired"
    swagger_description = "이메일 인증 코드가 만료되었습니다."


class EmailVerificationRateLimited(CustomAPIException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_detail = "email_verification_rate_limited"
    swagger_description = "너무 많은 인증 코드 요청입니다. 잠시 후 다시 시도해주세요."


class InvalidVerificationCode(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "invalid_verification_code"
    swagger_description = "유효하지 않은 인증 코드입니다."


class ResourceNotFound(CustomAPIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "resource_not_found"
    swagger_description = "요청한 리소스를 찾을 수 없습니다"


class ChannelMemberLimitReached(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "channel_member_limit_reached"
    swagger_description = "채널 구독자 수가 최대 한도(100명)에 도달했습니다"


class AccountNotMarkedForDeletion(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "account_not_marked_for_deletion"
    swagger_description = "계정이 삭제 대기중이 아닙니다"


class RecoveryPeriodExpired(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "recovery_period_expired"
    swagger_description = "계정 복구 기간이 만료되었습니다 (30일)"


class UserDoesNotExist(CustomAPIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "user_does_not_exist"
    swagger_description = "해당 사용자가 존재하지 않습니다"


class CannotBlockYourself(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "cannot_block_yourself"
    swagger_description = "자기 자신을 차단할 수 없습니다"


class UserTagUpdateRestricted(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "user_tag_update_restricted"
    swagger_description = "프로필 태그는 31일에 한 번만 변경할 수 있습니다"