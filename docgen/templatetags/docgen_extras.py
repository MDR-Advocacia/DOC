from django import template

register = template.Library()

@register.simple_tag(takes_context=True)
def param_replace(context, **kwargs):
    """
    Retorna os parâmetros da URL atual atualizando apenas o que mudou.
    """
    d = context['request'].GET.copy()
    for k, v in kwargs.items():
        d[k] = v
    for k in [k for k, v in d.items() if not v]:
        del d[k]
    return d.urlencode()

# --- FILTROS NOVOS ---

@register.filter(name='split')
def split_string(value, key):
    """Quebra string em lista."""
    if not value:
        return []
    return value.split(key)

@register.filter(name='strip')
def strip_string(value):
    """Remove espaços."""
    if not value:
        return ""
    return str(value).strip()