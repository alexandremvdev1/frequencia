# controle/templatetags/controle_filters.py
from datetime import datetime, date

from django import template

from ..models import (
    SabadoLetivo,
    UserScope,
    AcessoSecretaria,
    Secretaria,
)

# tenta importar a checagem por função; define fallback seguro se não existir
try:
    from ..permissions import has_funcao_permission
except Exception:  # pragma: no cover
    def has_funcao_permission(user, funcionario, nivel="LEITURA"):
        # Fallback conservador: só admins podem tudo
        return bool(getattr(user, "is_superuser", False) or getattr(user, "is_staff", False))

register = template.Library()


# =========================
# Helpers internos
# =========================
def _to_date(val):
    if isinstance(val, date):
        return val
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None

def _is_auth(user):
    return bool(getattr(user, "is_authenticated", False))

def _is_root(user):
    return bool(getattr(user, "is_superuser", False) or getattr(user, "is_staff", False))

def _has_access_secretaria(user, secretaria, nivel=None):
    """Checagem via AcessoSecretaria (legado)."""
    if not _is_auth(user) or secretaria is None:
        return False
    if _is_root(user):
        return True
    qs = AcessoSecretaria.objects.filter(user=user, secretaria=secretaria)
    if nivel:
        qs = qs.filter(nivel=str(nivel).upper())
    return qs.exists()

def _resolve_secretaria_from_setor(setor):
    """
    Resolve a Secretaria de um Setor considerando:
    - atributo oficial (secretaria_oficial) se existir
    - atributo legado direto no Setor (secretaria)
    - via Departamento (novo desenho): departamento.secretaria
    - fallback adicional via departamento.escola.secretaria (legado, se existir)
    """
    if not setor:
        return None

    # oficial / utilitários já presentes no seu Setor
    sec = getattr(setor, "secretaria_oficial", None)
    if sec:
        return sec

    # legado direto
    sec = getattr(setor, "secretaria", None)
    if sec:
        return sec

    # via departamento (novo desenho)
    dep = getattr(setor, "departamento", None)
    if dep and getattr(dep, "secretaria", None):
        return dep.secretaria

    # fallback legado via escola → secretaria
    try:
        esc = getattr(dep, "escola", None)
        if esc and getattr(esc, "secretaria", None):
            return esc.secretaria
    except Exception:
        pass

    return None


# =========================
# Filtros utilitários
# =========================
@register.filter(name="format_hora")
def format_hora(value):
    """Formata objetos time como HH:MM; retorna string vazia se None."""
    if not value:
        return ""
    try:
        return value.strftime("%H:%M")
    except Exception:
        return str(value)


# =========================
# Filtros de permissão/escopo (UserScope + legado)
# =========================
@register.filter(name="has_gerencia_global")
def has_gerencia_global(user):
    """
    True se:
      - superuser/staff OU
      - possui algum UserScope em nível GERENCIA OU
      - possui algum AcessoSecretaria em nível GERENCIA (legado)
    """
    if not _is_auth(user):
        return False
    if _is_root(user):
        return True

    try:
        if user.scopes.filter(nivel=UserScope.Nivel.GERENCIA).exists():
            return True
    except Exception:
        pass

    try:
        if AcessoSecretaria.objects.filter(user=user, nivel='GERENCIA').exists():
            return True
    except Exception:
        pass

    return False


@register.filter(name="can_access_secretaria")
def can_access_secretaria(user, secretaria):
    # via UserScope
    try:
        if user.scopes.filter(secretaria=secretaria).exists():
            return True
    except Exception:
        pass
    # legado
    return _has_access_secretaria(user, secretaria)


@register.filter(name="can_manage_secretaria")
def can_manage_secretaria(user, secretaria):
    try:
        if user.scopes.filter(secretaria=secretaria, nivel=UserScope.Nivel.GERENCIA).exists():
            return True
    except Exception:
        pass
    return _has_access_secretaria(user, secretaria, nivel='GERENCIA')


@register.filter(name="can_access_setor")
def can_access_setor(user, setor):
    sec = _resolve_secretaria_from_setor(setor)
    try:
        if user.scopes.filter(setor=setor).exists():
            return True
        if sec and user.scopes.filter(secretaria=sec).exists():
            return True
    except Exception:
        pass
    return _has_access_secretaria(user, sec)


@register.filter(name="can_manage_setor")
def can_manage_setor(user, setor):
    sec = _resolve_secretaria_from_setor(setor)
    try:
        if user.scopes.filter(setor=setor, nivel=UserScope.Nivel.GERENCIA).exists():
            return True
        if sec and user.scopes.filter(secretaria=sec, nivel=UserScope.Nivel.GERENCIA).exists():
            return True
    except Exception:
        pass
    return _has_access_secretaria(user, sec, nivel='GERENCIA')


@register.filter(name="can_access_funcionario")
def can_access_funcionario(user, funcionario):
    setor = getattr(funcionario, "setor", None)
    sec = _resolve_secretaria_from_setor(setor)
    try:
        if setor and user.scopes.filter(setor=setor).exists():
            return True
        if sec and user.scopes.filter(secretaria=sec).exists():
            return True
    except Exception:
        pass
    return _has_access_secretaria(user, sec)


@register.filter(name="can_manage_funcionario")
def can_manage_funcionario(user, funcionario):
    setor = getattr(funcionario, "setor", None)
    sec = _resolve_secretaria_from_setor(setor)
    try:
        if setor and user.scopes.filter(setor=setor, nivel=UserScope.Nivel.GERENCIA).exists():
            return True
        if sec and user.scopes.filter(secretaria=sec, nivel=UserScope.Nivel.GERENCIA).exists():
            return True
    except Exception:
        pass
    return _has_access_secretaria(user, sec, nivel='GERENCIA')


@register.filter(name="can_manage_folha")
def can_manage_folha(user, folha):
    func = getattr(folha, "funcionario", None)
    return can_manage_funcionario(user, func)


@register.simple_tag(takes_context=True, name="escopos_do_usuario")
def escopos_do_usuario(context):
    """
    Retorna rótulos legíveis do escopo do usuário.
    Preferência: UserScope (multi-nível). Fallback: nomes de Secretarias (legado).
    Uso: {% escopos_do_usuario as meus_escopos %}
    """
    request = context.get("request")
    user = getattr(request, "user", None)
    if not _is_auth(user):
        return []

    # Admin costuma ser tratado no template; aqui retornamos vazio
    if _is_root(user):
        return []

    # Preferir UserScope
    try:
        scopes = (
            user.scopes
            .select_related("prefeitura", "secretaria", "departamento", "setor")
            .all()
        )
        if scopes.exists():
            # Usa os helpers do próprio modelo (alvo_tipo/alvo_nome) para manter labels corretos (inclui 'Órgão' quando aplicável)
            return [f"{s.alvo_tipo()}: {s.alvo_nome()}" for s in scopes]
    except Exception:
        pass

    # Fallback legado: lista de Secretarias
    try:
        return list(
            AcessoSecretaria.objects.filter(user=user)
            .select_related("secretaria__prefeitura")
            .order_by("secretaria__prefeitura__nome", "secretaria__nome")
            .values_list("secretaria__nome", flat=True)
        )
    except Exception:
        return []


# =========================
# Regras pedidas pelo usuário (função e sábados letivos)
# =========================
@register.filter(name="funcao_em_permitidas")
def funcao_em_permitidas(funcao, permitidas=None):
    """
    Ex.: {% if request.user.funcionario.funcao|funcao_em_permitidas %}
         {% if funcionario.funcao|funcao_em_permitidas:"DIRETOR(A),COORDENADOR(A)" %}
    """
    if not funcao:
        return False

    base_permitidas = {
        "diretor(a)", "diretor", "coordenador(a)", "coordenador",
        "secretário(a)", "secretario(a)", "secretaria", "secretário",
        "gestor(a)", "gestor", "admin", "administrador"
    }
    if permitidas:
        lista = {p.strip().lower() for p in str(permitidas).split(",") if p.strip()}
    else:
        lista = base_permitidas

    return str(funcao).strip().lower() in lista


@register.filter(name="filter_sabados_letivos")
def filter_sabados_letivos(value, arg=None):
    """
    MODO A) Lista -> filtra apenas itens marcados como 'sabado_letivo'
       Uso: {% with dias|filter_sabados_letivos as sabados %}...

    MODO B) Coleção de sábados + data -> indica/descrição se a data é sábado letivo
       Uso: {{ sabados_letivos|filter_sabados_letivos:data }}
       - 'sabados_letivos' pode ser dict {date: descricao} ou queryset de SabadoLetivo
       - Retorna descrição (string), True (se sem desc) ou False (se não for)
    """
    # MODO A
    if arg is None:
        try:
            return [
                d for d in (value or [])
                if (hasattr(d, "sabado_letivo") and getattr(d, "sabado_letivo"))
                or (isinstance(d, dict) and d.get("sabado_letivo"))
            ]
        except Exception:
            return []

    # MODO B
    d = _to_date(arg)
    if not d:
        return False

    if isinstance(value, dict):
        desc = value.get(d)
        return (desc or True) if desc is not None else False

    try:
        for s in value or []:
            if getattr(s, "data", None) == d:
                return getattr(s, "descricao", "") or True
    except TypeError:
        pass

    try:
        s = SabadoLetivo.objects.filter(data=d).first()
        if s:
            return s.descricao or True
    except Exception:
        pass

    return False


# =========================
# Permissão por FUNÇÃO (com escopo)
# =========================
@register.simple_tag(takes_context=True)
def pode_por_funcao(context, funcionario, nivel='LEITURA'):
    """
    Uso: {% if pode_por_funcao funcionario 'GERENCIA' %} ... {% endif %}
    Considera request.user do contexto + regra has_funcao_permission.
    """
    user = getattr(context.get('request'), 'user', None)
    return has_funcao_permission(user, funcionario, nivel)


@register.filter
def somente_permitidos_por_funcao(funcionarios, user):
    """
    Filtra uma lista/QuerySet de funcionários para apenas os permitidos por função (nível LEITURA).
    Uso: {% for f in funcionarios|somente_permitidos_por_funcao:request.user %}
    """
    try:
        return [f for f in funcionarios if has_funcao_permission(user, f, 'LEITURA')]
    except Exception:
        return []


# --- labels e leitura dinâmica ----------------------------------------------
@register.filter(name="get_label")
def get_label(campo, campos_disponiveis):
    """
    Retorna o rótulo de 'campo' usando 'campos_disponiveis' (lista de pares ou dict).
    Exemplos:
      {{ 'nome'|get_label:campos_disponiveis }}  -> 'Nome'
      {{ 'matricula'|get_label:campos_disponiveis }} -> 'Matrícula'
    Fallback: formata o nome do campo ('data_nascimento' -> 'Data Nascimento').
    """
    if campo is None:
        return ""
    chave = str(campo)

    # Se vier como dict {'nome': 'Nome', ...}
    if isinstance(campos_disponiveis, dict):
        rotulo = campos_disponiveis.get(chave)
        if rotulo:
            return rotulo

    # Se vier como lista/tupla de pares [('nome','Nome'), ...]
    try:
        for k, v in campos_disponiveis:
            if str(k) == chave:
                return v
    except Exception:
        pass

    # Fallback: humaniza o nome do campo
    return chave.replace("_", " ").strip().title()


@register.filter(name="get_attr")
def get_attr(obj, nome_attr):
    """
    Lê um atributo do objeto dinamicamente no template.
    Ex.: {{ funcionario|get_attr:campo }}
    """
    if not obj or not nome_attr:
        return ""
    try:
        return getattr(obj, str(nome_attr))
    except Exception:
        return ""


MESES_PT = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}

@register.filter(name="mes_extenso")
def mes_extenso(value):
    try:
        m = int(value)
    except (TypeError, ValueError):
        return value
    return MESES_PT.get(m, value)

@register.filter(name="date_br")
def date_br(value, fmt="%d/%m/%Y"):
    try:
        return value.strftime(fmt) if value else ""
    except Exception:
        return value

@register.filter(name="get_item")
def get_item(mapping, key):
    """
    Retorna mapping[key] com fallback seguro.
    Suporta dicionários com chave date, int, str etc.
    """
    try:
        return mapping.get(key, [])
    except AttributeError:
        return []