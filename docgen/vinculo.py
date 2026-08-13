"""Vínculo da conta com o Entra ID, com fusão de contas duplicadas.

O problema que isso resolve: metade da base do DOC entra com login e senha, e
boa parte usa e-mail pessoal — gente que não aparece em nenhuma planilha do
DP. Não dá para o RH mapear quem é quem. Mas a própria pessoa consegue provar:
ela entra com a senha antiga e, na sequência, autentica no Entra ID. As duas
identidades ficam ligadas por quem é dono das duas.

Feito o vínculo uma vez, a senha é inutilizada e a conta passa a entrar só
por SSO.

A fusão varre as relações pelo metadado do Django (`_meta.related_objects`)
em vez de listar os modelos à mão: assim nada é esquecido quando alguém
acrescentar um modelo novo apontando para User.
"""

from __future__ import annotations

import logging

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction

from .models import AcessoArquivado, VinculoEntraId

logger = logging.getLogger(__name__)


def _peso(usuario: User) -> tuple:
    """Critério de qual conta sobrevive à fusão.

    Vence quem tem mais registros ligados — move-se menos coisa, e o risco de
    perder algo na transferência cai. Empate desfeito pelo staff e pela conta
    mais antiga.
    """
    total = 0
    for rel in User._meta.related_objects:
        if rel.related_model is VinculoEntraId:
            continue
        acessor = rel.get_accessor_name()
        try:
            gerente = getattr(usuario, acessor, None)
        except Exception:
            continue
        if gerente is None or not hasattr(gerente, 'count'):
            continue
        try:
            total += gerente.count()
        except Exception:
            continue
    return (total, usuario.is_staff, -usuario.id)


def _transferir(origem: User, destino: User) -> int:
    """Move tudo que aponta para `origem` de modo a apontar para `destino`.

    Devolve quantos registros foram movidos. Colisão de unicidade (o caso do
    favorito repetido, que tem unique_together com o modelo) é resolvida
    descartando o registro da origem — o destino já tem o equivalente.
    """
    movidos = 0

    for rel in User._meta.related_objects:
        modelo = rel.related_model
        campo = rel.field.name

        if modelo is VinculoEntraId:
            continue
        if modelo is AcessoArquivado and rel.field.name == 'usuario':
            # OneToOne: o arquivamento pertence à conta, não migra.
            continue

        if rel.many_to_many:
            continue  # tratado depois

        for obj in modelo.objects.filter(**{campo: origem}):
            setattr(obj, campo, destino)
            try:
                with transaction.atomic():
                    obj.save(update_fields=[campo])
                movidos += 1
            except IntegrityError:
                # Duplicata natural (ex.: mesmo template favoritado nas duas
                # contas). O destino já tem, então a da origem é descartada.
                with transaction.atomic():
                    modelo.objects.filter(pk=obj.pk).delete()

    # Relações M2M (equipes: membros e supervisores).
    for campo_m2m in User._meta.many_to_many:
        origem_rel = getattr(origem, campo_m2m.name)
        destino_rel = getattr(destino, campo_m2m.name)
        for item in origem_rel.all():
            destino_rel.add(item)
            movidos += 1
        origem_rel.clear()

    for rel in User._meta.related_objects:
        if not rel.many_to_many:
            continue
        acessor = rel.get_accessor_name()
        origem_rel = getattr(origem, acessor, None)
        destino_rel = getattr(destino, acessor, None)
        if origem_rel is None or destino_rel is None:
            continue
        for item in origem_rel.all():
            destino_rel.add(item)
            movidos += 1
        origem_rel.clear()

    return movidos


@transaction.atomic
def vincular(conta_atual: User, email_corporativo: str) -> dict:
    """Liga `conta_atual` ao e-mail do Entra ID, fundindo se houver duplicata.

    Devolve um resumo com a conta que ficou, a que foi arquivada e quantos
    registros migraram. Tudo numa transação: ou vincula inteiro, ou nada.
    """
    email = (email_corporativo or '').strip().lower()
    if not email:
        raise ValueError("E-mail corporativo vazio.")

    outra = (
        User.objects.filter(email__iexact=email)
        .exclude(pk=conta_atual.pk)
        .order_by('pk')
        .first()
    )

    absorvida_nome = ''
    migrados = 0

    if outra is None:
        sobrevivente = conta_atual
    else:
        sobrevivente, absorvida = sorted(
            [conta_atual, outra], key=_peso, reverse=True
        )
        migrados = _transferir(absorvida, sobrevivente)
        absorvida_nome = absorvida.get_username()

        # A absorvida sai de circulação, mas continua existindo: é o que
        # mantém qualquer vestígio histórico que não migrou.
        absorvida.email = ''
        absorvida.is_active = False
        absorvida.set_unusable_password()
        absorvida.save()
        AcessoArquivado.objects.get_or_create(
            usuario=absorvida,
            defaults={'motivo': f'Fundida em {sobrevivente.get_username()} pelo vínculo Entra ID'},
        )

    sobrevivente.email = email
    sobrevivente.is_active = True
    # É isto que faz a conta passar a entrar só por SSO.
    sobrevivente.set_unusable_password()
    sobrevivente.save()

    VinculoEntraId.objects.update_or_create(
        usuario=sobrevivente,
        defaults={
            'email_corporativo': email,
            'conta_absorvida': absorvida_nome,
            'itens_migrados': migrados,
        },
    )
    # Se a conta absorvida tinha vínculo, ele deixa de valer.
    if outra is not None:
        VinculoEntraId.objects.filter(usuario__pk=absorvida.pk).exclude(
            usuario__pk=sobrevivente.pk
        ).delete()

    logger.info(
        "vinculo entra id: %s -> %s (absorveu=%r, migrados=%d)",
        conta_atual.get_username(), email, absorvida_nome, migrados,
    )

    return {
        'sobrevivente': sobrevivente,
        'absorvida': absorvida_nome,
        'migrados': migrados,
        'fundiu': outra is not None,
    }
