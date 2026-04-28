from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def param_replace(context, **kwargs):
    """
    Retorna os parametros da URL atual atualizando apenas o que mudou.
    """
    params = context['request'].GET.copy()
    for key, value in kwargs.items():
        params[key] = value
    for key in [key for key, value in params.items() if not value]:
        del params[key]
    return params.urlencode()


@register.filter(name='split')
def split_string(value, key):
    if not value:
        return []
    return value.split(key)


@register.filter(name='strip')
def strip_string(value):
    if not value:
        return ""
    return str(value).strip()


@register.filter(name='get_item')
def get_item(value, key):
    if isinstance(value, dict):
        return value.get(key)
    return None
