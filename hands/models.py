from django.conf import settings
from django.db import models


class Hand(models.Model):
    """One hand from a user's hand histories, parsed from a stream their tracker uploaded.

    Amounts are integers: chips, or cents when `currency` is set. The columns
    are what the game history lists; `replay` holds the seats, events and
    boards the replay steps through (see tracker.parsing.pokerstars).
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hands")
    stream = models.ForeignKey("tracker.LogStream", on_delete=models.CASCADE, related_name="hands")
    site = models.CharField(max_length=32)  # e.g. "pokerstars"
    hand_id = models.CharField(max_length=32)  # the site's hand number
    played_at = models.DateTimeField()
    game = models.CharField(max_length=64)  # e.g. "Hold'em No Limit"
    currency = models.CharField(max_length=3, blank=True)  # empty for chips
    play_money = models.BooleanField(default=False)
    small_blind = models.BigIntegerField()
    big_blind = models.BigIntegerField()
    tournament_id = models.CharField(max_length=32, blank=True)
    table = models.CharField(max_length=64)
    # The player the history deals cards to: the user, under their screen name on the site.
    hero = models.CharField(max_length=64, blank=True)
    hero_position = models.CharField(max_length=8, blank=True)
    hero_cards = models.JSONField(default=list, blank=True)
    hero_net = models.BigIntegerField(default=0)
    final_street = models.CharField(max_length=32)
    replay = models.JSONField(default=dict)

    class Meta:
        constraints = [
            # A reparse updates its hands in place, so their ids (and replay links) survive it.
            models.UniqueConstraint(fields=("user", "site", "hand_id"), name="unique_hand_per_user"),
        ]
        indexes = [models.Index(fields=("user", "-played_at", "-id"), name="hand_history")]
        ordering = ("-played_at", "-id")

    def __str__(self):
        return f"{self.site} #{self.hand_id}"
