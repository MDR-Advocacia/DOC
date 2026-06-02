"""Normaliza tags Jinja de templates já existentes no banco.

Uso:
    python manage.py normalize_templates --dry-run    # mostra o que mudaria
    python manage.py normalize_templates --apply      # aplica as mudanças
    python manage.py normalize_templates --apply --template-id 5   # só um

Sem --dry-run nem --apply: erro.
"""

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from docgen.models import Template
from docgen.template_utils import (
    apply_renames_to_configuracao,
    normalize_jinja_tags_in_docx,
)


class Command(BaseCommand):
    help = "Normaliza tags Jinja com acentos/cedilha em templates existentes."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Apenas reporta o que mudaria, sem salvar.',
        )
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Aplica as mudanças no banco.',
        )
        parser.add_argument(
            '--template-id',
            type=int,
            help='Limita a operação a um único Template por id.',
        )

    def handle(self, *args, **opts):
        if not opts['dry_run'] and not opts['apply']:
            raise CommandError(
                "Informe --dry-run para simular ou --apply para aplicar."
            )
        if opts['dry_run'] and opts['apply']:
            raise CommandError("--dry-run e --apply são mutuamente exclusivos.")

        qs = Template.objects.all().order_by('id')
        if opts['template_id']:
            qs = qs.filter(id=opts['template_id'])

        total = qs.count()
        afetados = 0
        self.stdout.write(f"Analisando {total} template(s)...\n")

        for template in qs:
            if not template.arquivo_template:
                continue
            try:
                template.arquivo_template.open('rb')
                docx_bytes = template.arquivo_template.read()
            finally:
                template.arquivo_template.close()

            try:
                novo_bytes, renames = normalize_jinja_tags_in_docx(docx_bytes)
            except Exception as exc:
                self.stderr.write(self.style.ERROR(
                    f"  [#{template.id}] {template.titulo!r}: erro ao processar — {exc}"
                ))
                continue

            if not renames:
                continue

            afetados += 1
            self.stdout.write(self.style.WARNING(
                f"  [#{template.id}] {template.titulo!r}: {len(renames)} renomeação(ões)"
            ))
            for antigo, novo in renames.items():
                self.stdout.write(f"      {antigo} → {novo}")

            if opts['apply']:
                config_nova = apply_renames_to_configuracao(
                    template.configuracao_campos, renames
                )
                template.configuracao_campos = config_nova
                # Sobrescreve o arquivo no FileField mantendo o nome original.
                nome = template.arquivo_template.name.rsplit('/', 1)[-1]
                template.arquivo_template.save(
                    nome, ContentFile(novo_bytes), save=False
                )
                template.save(update_fields=['arquivo_template', 'configuracao_campos'])
                self.stdout.write(self.style.SUCCESS(f"      → salvo"))

        if opts['dry_run']:
            self.stdout.write(self.style.NOTICE(
                f"\nDry-run: {afetados}/{total} template(s) seriam alterados. "
                f"Use --apply para confirmar."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\nConcluído: {afetados}/{total} template(s) atualizados."
            ))
