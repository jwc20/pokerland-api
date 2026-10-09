import random

from django.core.management.base import BaseCommand

from practice.models import Scenario
from practice.sets import GENERATED, generated_scenario


class Command(BaseCommand):
    help = (
        "Fill the pool of generated practice spots, shared by every user, so a set never waits on one. Push-or-fold "
        "spots sample their equity, the slowest of them at a few hundredths of a second each locally."
    )

    def add_arguments(self, parser):
        parser.add_argument("--per-skill", type=int, default=50, help="spots each skill's pool should hold")
        parser.add_argument("--skill", choices=sorted(GENERATED), help="only this skill")

    def handle(self, *args, **options):
        rng = random.SystemRandom()
        for skill, (label, topics) in GENERATED.items():
            if options["skill"] and skill != options["skill"]:
                continue
            have = Scenario.objects.filter(source="generated", topic__in=topics).count()
            for _ in range(max(0, options["per_skill"] - have)):
                generated_scenario(skill, rng)
            total = Scenario.objects.filter(source="generated", topic__in=topics).count()
            self.stdout.write(f"{label}: {total} spots")
