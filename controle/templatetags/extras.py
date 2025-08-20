# controle/templatetags/extras.py
from django import template
from . import controle_filters as cf

register = template.Library()

# Reexporta tudo do controle_filters
for name, f in cf.register.filters.items():
    register.filter(name, f)
for name, t in cf.register.tags.items():
    register.tag(name, t)

# (Opcional) se você também tiver custom_filters, mescla aqui.
try:
    from . import custom_filters as cstm
    for name, f in cstm.register.filters.items():
        register.filter(name, f)
    for name, t in cstm.register.tags.items():
        register.tag(name, t)
except Exception:
    pass
