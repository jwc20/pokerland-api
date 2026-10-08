from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from hands.sessions import rebuild


class Command(BaseCommand):
    help = "Build every user's sessions afresh from their hands (hands.sessions), or the named users'."

    def add_arguments(self, parser):
        parser.add_argument("usernames", nargs="*", help="default: every user")

    def handle(self, *args, **options):
        users = get_user_model().objects.order_by("pk")
        if options["usernames"]:
            users = users.filter(username__in=options["usernames"])
        for user in users:
            rebuild(user.pk)
            self.stdout.write(f"{user.username}: {user.sessions.count()} sessions")
