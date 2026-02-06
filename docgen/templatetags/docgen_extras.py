from django import template

register = template.Library()

@register.simple_tag(takes_context=True)
def param_replace(context, **kwargs):
    """
    Retorna os parâmetros da URL atual atualizando apenas o que mudou.
    Útil para paginação manter os filtros ativos.
    Ex: ?q=busca&page=2
    """
    d = context['request'].GET.copy()
    for k, v in kwargs.items():
        d[k] = v
    for k in [k for k, v in d.items() if not v]:
        del d[k]
    return d.urlencode()