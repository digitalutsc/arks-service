"""Move buffered redirect counts into the database."""

from django.core.management.base import BaseCommand

from core.counters import flush_counters


class Command(BaseCommand):
    help = "Write buffered redirect counts to the database."

    def handle(self, *args, **options):
        moved = flush_counters()
        self.stdout.write(self.style.SUCCESS(f"Flushed {moved} buffered resolution(s)."))
