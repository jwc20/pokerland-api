from rest_framework import status
from rest_framework.exceptions import APIException

from utils.commons import CustomAPIException


class InvalidChannelManager(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "invalid_channel_manager"
    swagger_description = "Not a channel manager"


class ChannelDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "channel_does_not_exist"
    swagger_description = "Channel does not exist"


class ContentDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "content_does_not_exist"
    swagger_description = "Content does not exist."


class CommunityPostDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "community_post_does_not_exist"
    swagger_description = "Community post does not exist."


class NotSubscribingChannel(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "not_subscribing_channel"
    swagger_description = "Not subscribed to this channel"


class AlreadyEnrolledEmail(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "already_enrolled_login_id"
    swagger_description = "Login ID is already registered"


class NotEnrolledEmail(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "not_enrolled_login_id"
    swagger_description = "Login ID is not registered"


class InvalidLoginInfo(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "invalid_login_info"
    swagger_description = "Login information is invalid"
    
class SocialLoginIdentifierNotFound(CustomAPIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "social_login_identifier_not_found"
    swagger_description = "Social login verification info not found."
    
class SocialUserExists(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "social_user_exists"
    swagger_description = "Social account already exists"

class SocialAccessTokenExpired(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "social_access_token_expired"
    swagger_description = "Social account access token has expired"

class TokenAuthenticationFailed(CustomAPIException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "authentication_failed"
    swagger_description = "Token authentication failed (possible in all token-auth endpoints)"


class NotMyCommunityPost(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "not_my_community_post"
    swagger_description = "This is not a community post created by the user"


class CommunityPostCommentDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "community_post_comment_does_not_exist"
    swagger_description = "Community post comment does not exist"


class CommunityPostCommentReplyDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "community_post_comment_reply_does_not_exist"
    swagger_description = "Community post comment reply does not exist"


class NotMyFeed(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "not_my_feed"
    swagger_description = "This is not a feed created by the user"


class FeedCommentDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "feed_comment_does_not_exist"
    swagger_description = "Feed comment does not exist"


class FeedCommentReplyDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "feed_comment_reply_does_not_exist"
    swagger_description = "Feed comment reply does not exist"


class FeedDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "feed_does_not_exist"
    swagger_description = "Feed does not exist."


class ContentCommentDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "content_comment_does_not_exist"
    swagger_description = "Post comment does not exist."


class ContentCommentReplyDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "content_comment_reply_does_not_exist"
    swagger_description = "Post comment reply does not exist."


class AnnouncementDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "announcement_does_not_exist"
    swagger_description = "Announcement does not exist."


class AnnouncementCommentDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "announcement_comment_does_not_exist"
    swagger_description = "Announcement comment does not exist."


class AnnouncementCommentReplyDoesNotExist(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "announcement_comment_reply_does_not_exist"
    swagger_description = "Announcement comment reply does not exist."


class NotMyAnnouncement(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "not_my_announcement"
    swagger_description = "This is not your announcement."


class ApplePaymentVerificationFailed(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "apple_payment_verification_failed"
    swagger_description = "Apple payment verification failed"


class AppleReceiptValidationFailed(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "apple_receipt_valiation_failed"
    swagger_description = "Apple receipt validation failed"


class AndroidPaymentVerificationFailed(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "android_payment_verification_failed"
    swagger_description = "Android payment verification failed"


class PurchaseAcknowledgementFailed(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "purchase_acknowledgement_failed"
    swagger_description = "Purchase acknowledgement failed"


class DuplicatePurchaseError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "duplicate_purchase"
    swagger_description = "Purchase has already been processed"


class PurchaseVerificationFailed(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "purchase_verification_failed"
    swagger_description = "Purchase verification failed"


class AuthTokenDeleteFailed(Exception):
    pass


class InvalidArguments(Exception):
    pass


class EmailVerificationCodeExpired(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "email_verification_code_expired"
    swagger_description = "Email verification code has expired."


class EmailVerificationRateLimited(CustomAPIException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_detail = "email_verification_rate_limited"
    swagger_description = "Too many verification code requests. Please try again later."


class InvalidVerificationCode(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "invalid_verification_code"
    swagger_description = "Invalid verification code."


class ResourceNotFound(CustomAPIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "resource_not_found"
    swagger_description = "Requested resource not found"


class ChannelMemberLimitReached(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "channel_member_limit_reached"
    swagger_description = "Channel subscriber count reached the maximum limit (100)"


class AccountNotMarkedForDeletion(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "account_not_marked_for_deletion"
    swagger_description = "Account is not marked for deletion"


class RecoveryPeriodExpired(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "recovery_period_expired"
    swagger_description = "Account recovery period has expired (30 days)"


class UserDoesNotExist(CustomAPIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "user_does_not_exist"
    swagger_description = "User does not exist"


class CannotBlockYourself(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "cannot_block_yourself"
    swagger_description = "You cannot block yourself"


class UserTagUpdateRestricted(CustomAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "user_tag_update_restricted"
    swagger_description = "Profile tag can be changed only once every 31 days"
