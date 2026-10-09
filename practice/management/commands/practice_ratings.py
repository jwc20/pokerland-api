from django.core.management.base import BaseCommand

from practice.sets import rebuild_ratings


class Command(BaseCommand):
    help = (
        "Rebuild every skill rating and spot difficulty from every graded answer, in the order they were given: for "
        "answers given before there were ratings, or after changing practice.ratings."
    )

    def handle(self, *args, **options):
        self.stdout.write(f"Rated {rebuild_ratings():,} answers.")
