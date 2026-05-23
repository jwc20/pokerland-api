import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.hashers import make_password
from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property
from django_extensions.db.models import TimeStampedModel

from utils.choices import SocialLoginProviderChoices


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password, **extra_fields):
        return User.objects.create(
            email=email, password=make_password(password), **extra_fields
        )

    def create_superuser(self, login_id, password=None):
        extra_fields = {
            "is_superuser": True,
            "is_staff": True,
        }
        return self.create_user(login_id, password, **extra_fields)


class User(AbstractBaseUser):
    """사용자 모델, 권한 상관 없이 가질수 있는 기본 데이터"""

    email = models.EmailField(unique=True)
    password = models.CharField("password", max_length=128, null=True, blank=True) # for social login
    name = models.CharField("프로필 이름", max_length=100, db_index=True)
    user_tag = models.CharField("프로필 태그", max_length=100, db_index=True)
    user_tag_changed_at = models.DateTimeField(
        "프로필 태그 변경 일시", default=timezone.now
    )
    bio = models.CharField("한줄 소개", max_length=255, default="")
    profile_image_url = models.URLField(
        "프로필 이미지 URL", default=None, null=True, blank=True, max_length=2048
    )
    is_active = models.BooleanField("활성 사용자 여부", default=True)
    date_joined = models.DateTimeField("회원 가입 일시", default=timezone.now)
    last_login = models.DateTimeField("마지막 로그인 일시", auto_now=True)
    password_changed_at = models.DateTimeField(
        "비밀번호 변경 일시", default=timezone.now
    )
    deletion_requested_at = models.DateTimeField(
        "계정 삭제 요청 일시", null=True, blank=True
    )

    # 권한 정보
    is_creator = models.BooleanField("크리에이터 여부", default=False)
    is_staff = models.BooleanField("운영자 여부", default=False)
    is_superuser = models.BooleanField("시스템 관리자 여부", default=False)

    USERNAME_FIELD = "email"

    objects = UserManager()

    @property
    def subscribing_channel_ids(self):
        from channels.utils import ChannelHandler

        return list(
            ChannelHandler()
            .get_subscribing_channels(customer=self)
            .values_list("id", flat=True)
        )

    @property
    def managing_channel_ids(self):
        from channels.utils import ChannelHandler

        return list(
            ChannelHandler()
            .get_managing_channels(manager=self)
            .values_list("id", flat=True)
        )

    @cached_property
    def creator_links(self):
        return self.creatorlink_set.filter(is_deleted=False).order_by("sort_order")


class Device(TimeStampedModel):
    """앱 설치 사용자에 대한 기기 정보"""

    # TODO - FCM 토큰 수집 로직

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    push_token = models.CharField(max_length=255, blank=True, null=True)


class CustomerManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_creator=False, is_staff=False)


class Customer(User):
    class Meta:
        proxy = True

    objects = CustomerManager()


class AdAgreement(TimeStampedModel):
    """광고성 수신 동의"""

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="ad_agreement"
    )
    is_agreed = models.BooleanField(default=False, null=True, blank=True)


class AdNightAgreement(TimeStampedModel):
    """야간 광고성 수신 동의"""

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="ad_night_agreement"
    )
    is_agreed = models.BooleanField(default=False, null=True, blank=True)


class CreatorManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_creator=True)


class Creator(User):
    class Meta:
        proxy = True

    objects = CreatorManager()


class StaffManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_staff=True)


class Staff(User):
    class Meta:
        proxy = True


class CreatorLink(TimeStampedModel):
    """크리에이터용 링크 정보"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(
        "링크명", max_length=255, default=None, blank=True, null=True
    )
    url = models.URLField()
    sort_order = models.PositiveIntegerField(default=0)
    is_deleted = models.BooleanField(default=False)

    # TODO - 나중에 타입 (ex.인스타, 유튜브, 링크드인 등) 추가하기

    class Meta:
        ordering = ["sort_order"]


class ConfirmEmail(TimeStampedModel):
    """이메일 인증 정보"""

    email = models.EmailField()
    confirm_code = models.CharField("인증코드", max_length=6)
    is_confirmed = models.BooleanField(default=False)


class SocialLoginIdentifier(TimeStampedModel):
    """소셜 로그인 식별 정보"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    provider = models.CharField(
        "소셜 로그인 제공자", max_length=10, choices=SocialLoginProviderChoices
    )
    identifier = models.CharField(max_length=255)
    temp_access_token = models.CharField(max_length=255)
    email = models.EmailField()


class UserBlock(TimeStampedModel):
    """사용자 차단 정보"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="blocking")
    blocked_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="blocked_by")

    class Meta:
        unique_together = (("user", "blocked_user"),)
        verbose_name = "사용자 차단"
        verbose_name_plural = "사용자 차단"