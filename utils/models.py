import uuid
from functools import cached_property

from django.contrib.auth import get_user_model
from django.db import models

from utils.aws_utils import CloudfrontHandler

User = get_user_model()


class CommentModelMixin(models.Model):
    """댓글 모델 Mixin"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_deleted = models.BooleanField("삭제 여부", default=False)
    body = models.TextField("본문", blank=True, default=None, null=True)
    replied_cnt = models.PositiveIntegerField(default=0)
    like_cnt = models.PositiveIntegerField("좋아요 수", default=0)

    @cached_property
    def user_tag(self):
        return self.user.username

    @cached_property
    def profile_image_url(self):
        return self.user.profile_image_url

    @cached_property
    def user_name(self):
        return self.user.profile_name

    class Meta:
        abstract = True


class CommentLikeModelMixin(models.Model):
    """댓글 좋아요 모델 Mixin"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True


class CommentReplyModelMixin(models.Model):
    """댓글 대댓글 모델 Mixin"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_deleted = models.BooleanField("삭제 여부", default=False)
    body = models.TextField("본문", blank=True, default=None, null=True)
    like_cnt = models.PositiveIntegerField("좋아요 수", default=0)

    @cached_property
    def user_tag(self):
        return self.user.username

    @cached_property
    def profile_image_url(self):
        return self.user.profile_image_url

    @cached_property
    def user_name(self):
        return self.user.profile_name

    class Meta:
        abstract = True


class CommentReplyLikeModelMixin(models.Model):
    """댓글 대댓글 좋아요 모델 Mixin"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True


class ImageModelMixin(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sort_order = models.PositiveSmallIntegerField(default=0)
    original_image_url = models.URLField("원본 이미지 url", max_length=2048)
    is_deleted = models.BooleanField("삭제 여부", default=False)
    is_public = models.BooleanField("공개 이미지 여부", default=False)

    @cached_property
    def signed_original_image_url(self):
        if self.is_public:
            return self.original_image_url
        return CloudfrontHandler.get_signed_url(url=self.original_image_url)

    class Meta:
        abstract = True


class AudioModelMixin(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sort_order = models.PositiveSmallIntegerField(default=0)
    original_audio_url = models.URLField("원본 오디오 url", max_length=2048)
    duration = models.CharField(
        "오디오 재생시간(초)", null=True, blank=True, default=None
    )
    is_deleted = models.BooleanField("삭제 여부", default=False)
    # 오디오는 항상 private이므로 is_public 필드 불필요

    @cached_property
    def signed_original_audio_url(self):
        return CloudfrontHandler.get_signed_url(url=self.original_audio_url)

    class Meta:
        abstract = True


class BookmarkModelMixin(models.Model):
    """즐겨찾기 모델 Mixin"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True


class LikeModelMixin(models.Model):
    """좋아요 모델 Mixin"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True


class ReportModelMixin(models.Model):
    """신고 모델 Mixin"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    reason = models.TextField("신고사유", default=None, null=True, blank=True)

    class Meta:
        abstract = True
