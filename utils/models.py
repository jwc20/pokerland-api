import uuid
from functools import cached_property

from django.contrib.auth import get_user_model
from django.db import models

from utils.aws_utils import CloudfrontHandler

User = get_user_model()


class CommentModelMixin(models.Model):
    """Comment model mixin."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_deleted = models.BooleanField("Deleted", default=False)
    body = models.TextField("Body", blank=True, default=None, null=True)
    replied_cnt = models.PositiveIntegerField(default=0)
    like_cnt = models.PositiveIntegerField("Like count", default=0)

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
    """Comment like model mixin."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True


class CommentReplyModelMixin(models.Model):
    """Comment reply model mixin."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_deleted = models.BooleanField("Deleted", default=False)
    body = models.TextField("Body", blank=True, default=None, null=True)
    like_cnt = models.PositiveIntegerField("Like count", default=0)

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
    """Comment reply like model mixin."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True


class ImageModelMixin(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sort_order = models.PositiveSmallIntegerField(default=0)
    original_image_url = models.URLField("Original image URL", max_length=2048)
    is_deleted = models.BooleanField("Deleted", default=False)
    is_public = models.BooleanField("Public image", default=False)

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
    original_audio_url = models.URLField("Original audio URL", max_length=2048)
    duration = models.CharField(
        "Audio duration (seconds)", null=True, blank=True, default=None
    )
    is_deleted = models.BooleanField("Deleted", default=False)
    # Audio is always private, so an is_public field is unnecessary.

    @cached_property
    def signed_original_audio_url(self):
        return CloudfrontHandler.get_signed_url(url=self.original_audio_url)

    class Meta:
        abstract = True


class BookmarkModelMixin(models.Model):
    """Bookmark model mixin."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True


class LikeModelMixin(models.Model):
    """Like model mixin."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True


class ReportModelMixin(models.Model):
    """Report model mixin."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    reason = models.TextField("Report reason", default=None, null=True, blank=True)

    class Meta:
        abstract = True
