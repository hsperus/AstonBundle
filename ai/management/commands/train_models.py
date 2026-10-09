from django.core.management.base import BaseCommand

from ai import forecast, recommender


class Command(BaseCommand):
    help = "Train the recommendation model and the demand forecast, and store their evaluation results."

    def add_arguments(self, parser):
        parser.add_argument("--only", choices=["recs", "forecast"])

    def handle(self, *args, **opts):
        if opts.get("only") in (None, "recs"):
            run = recommender.train()
            self.stdout.write(f"Recommender {run.version}: {run.metrics}")
        if opts.get("only") in (None, "forecast"):
            run = forecast.train()
            if run is None:
                self.stdout.write("Forecast: no order history yet.")
            else:
                m = {k: v for k, v in run.metrics.items() if k != "backtest"}
                self.stdout.write(f"Forecast {run.version}: {m}")
