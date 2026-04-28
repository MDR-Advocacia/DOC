from django.core.management.base import BaseCommand

from ...processos_worker.runner import ProcessosWorker


class Command(BaseCommand):
    help = "Executa o worker de captura de peticao inicial."

    def handle(self, *args, **options):
        ProcessosWorker.from_env().run_forever()
