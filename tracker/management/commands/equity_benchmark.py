import random
import time

from django.core.management.base import BaseCommand

from tracker.parsing import equity

# All-ins the parser meets, from the quickest to work out to the slowest: (what, hands, board, Omaha).
SPOTS = (
    ("hold'em, heads-up, on the turn", [["Ah", "Kh"], ["Qs", "Qd"]], ["2h", "7h", "Tc", "3s"], False),
    ("hold'em, heads-up, on the flop", [["Ah", "Kh"], ["Qs", "Qd"]], ["2h", "7h", "Tc"], False),
    ("hold'em, heads-up, before the flop", [["Ah", "Kh"], ["Qs", "Qd"]], [], False),
    ("hold'em, three-way, before the flop", [["Ah", "Kh"], ["Qs", "Qd"], ["7c", "7d"]], [], False),
    ("Omaha, heads-up, on the flop", [["Ah", "As", "7d", "6c"], ["Ks", "Kd", "Qh", "Jh"]], ["2h", "7h", "Tc"], True),
    ("Omaha, heads-up, before the flop", [["Ah", "As", "7d", "6c"], ["Ks", "Kd", "Qh", "Jh"]], [], True),
)


class Command(BaseCommand):
    help = (
        "Time the all-in equity the parser works out (tracker.parsing.equity), per kind of all-in. Run it where "
        "the parser runs, e.g. `zappa manage dev equity_benchmark`, to see what a reparse will cost there."
    )

    def add_arguments(self, parser):
        parser.add_argument("--repeat", type=int, default=5, help="times to work out each spot (default 5)")

    def handle(self, *args, **options):
        repeat = options["repeat"]
        for name, holes, board, omaha in SPOTS:
            rng = random.Random(1)
            start = time.perf_counter()
            for _ in range(repeat):
                shares, exact = equity.shares(holes, board, omaha=omaha, rng=rng)
            seconds = (time.perf_counter() - start) / repeat
            how = "every run-out" if exact else "sampled"
            self.stdout.write(f"{name}: {seconds * 1000:.0f} ms ({how}; {', '.join(f'{s:.1%}' for s in shares)})")
