from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from users.models import ClientToken


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_client_token(sender, instance, created, raw, **kwargs):
    # raw: loaddata is restoring a fixture, which brings its own tokens.
    if created and not raw:
        ClientToken.objects.create(user=instance)
