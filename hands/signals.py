"""Tells hands.results when the data its kept results read changes outside hands.store: a hand saved on its own (as
the admin does), leak presets and reviews, saved spots, and deleted streams (their hands go with them). Notes aren't
among it: no kept result reads them (only the history, which isn't kept, filters by them).

Deletions that come with a user's own are left alone: their kept results go with them.

A hand's deletion isn't watched: with a receiver, Django would load every hand row, replays and all, to delete a
stream or a user, instead of their ids. Hands go with their stream, which is watched; code that deletes hands any
other way must call hands.results.changed.
"""

from django.contrib.auth import get_user_model
from django.db.models import QuerySet
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from hands import results
from hands.models import CoachPresets, Hand, LeakReview, Spot
from tracker.models import LogStream


def _started_by(origin, model):
    """Whether a deletion started with a `model` row or a query of them."""
    return isinstance(origin, model) or (isinstance(origin, QuerySet) and origin.model is model)


@receiver(post_save, sender=Hand)
@receiver(post_save, sender=CoachPresets)
@receiver(post_save, sender=LeakReview)
@receiver(post_save, sender=Spot)
def saved(sender, instance, **kwargs):
    results.changed(instance.user_id)


@receiver(post_delete, sender=CoachPresets)
@receiver(post_delete, sender=LeakReview)
@receiver(post_delete, sender=Spot)
def deleted(sender, instance, origin=None, **kwargs):
    if not _started_by(origin, get_user_model()):
        results.changed(instance.user_id)


@receiver(post_delete, sender=LogStream)
def stream_deleted(sender, instance, origin=None, **kwargs):
    if not _started_by(origin, get_user_model()):
        results.changed(instance.user_id)
