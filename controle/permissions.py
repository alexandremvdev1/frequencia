# controle/permissions.py
from __future__ import annotations

from typing import Optional, Iterable, Callable, Any, Dict, Set, Tuple

from django.contrib import messages
from django.db.models import Q, QuerySet
from django.shortcuts import redirect
from django.urls import reverse

from .models import (
    Prefeitura, Secretaria, Escola, Departamento, Setor,
    Funcionario, UserScope,
    AcessoPrefeitura, AcessoSecretaria, AcessoEscola, AcessoSetor,
    HorarioTrabalho, FolhaFrequencia, NivelAcesso,
)

# --- suporte opcional a controle por função/cargo (se existir no projeto)
try:
    from .models import FuncaoPermissao  # campos esperados: user, nome_funcao, nivel, secretaria(nullable), setor(nullable)
    HAS_FUNCAO_PERMISSAO = True
except Exception:
    FuncaoPermissao = None  # type: ignore
    HAS_FUNCAO_PERMISSAO = False


# ============================================================
# Helpers básicos
# ============================================================
def _is_auth(user) -> bool:
    return bool(getattr(user, "is_authenticated", False))

def _user_is_admin(user) -> bool:
    return bool(_is_auth(user) and (getattr(user, "is_superuser", False) or getattr(user, "is_staff", False)))

def _norm(s: Any) -> str:
    return str(s or "").strip().lower()

def _nivel_to_int(n: Any) -> int:
    s = _norm(n)
    if s in {"gerencia", _norm(NivelAcesso.GERENCIA)}:
        return 1
    return 0  # leitura / default

LEITURA = "LEITURA"
GERENCIA = "GERENCIA"


# ============================================================
# Cadeia hierárquica a partir do Setor
# (novo por Departamento + legado com secretaria no Setor)
# ============================================================
def _resolve_chain_from_setor(setor: Setor) -> Tuple[Escola | None, Secretaria | None, Prefeitura | None]:
    escola = None
    secretaria = None
    prefeitura = None

    # legado direto no setor
    if hasattr(setor, "secretaria") and getattr(setor, "secretaria_id", None):
        secretaria = setor.secretaria

    # novo: via departamento
    dep = getattr(setor, "departamento", None)
    if dep:
        if getattr(dep, "escola_id", None):
            escola = dep.escola
        if getattr(dep, "secretaria_id", None):
            secretaria = dep.secretaria
        if getattr(dep, "prefeitura_id", None):
            prefeitura = dep.prefeitura

    # escalada
    if escola and not secretaria:
        secretaria = getattr(escola, "secretaria", None)
    if secretaria and not prefeitura:
        prefeitura = getattr(secretaria, "prefeitura", None)
    return escola, secretaria, prefeitura


# ============================================================
# Escopo consolidado do usuário
# ============================================================
def user_scope(user) -> Dict[str, Any]:
    """
    Retorna um dicionário com IDs permitidos por nível.
    Inclui escopos:
      - Admin (all=True)
      - UserScope (prefeitura/secretaria/escola/departamento/setor)
      - Acesso* legado (prefeitura/secretaria/escola/setor)
      - Unidade do próprio funcionário (cadeia do setor)
    """
    scope = {
        "all": False,
        "prefeituras": set(), "secretarias": set(), "escolas": set(),
        "departamentos": set(), "setores": set(),
    }

    if not _is_auth(user):
        return scope

    if _user_is_admin(user):
        scope["all"] = True
        return scope

    # --- UserScope (novo)
    try:
        for s in user.scopes.all():
            if s.prefeitura_id:   scope["prefeituras"].add(s.prefeitura_id)
            if s.secretaria_id:   scope["secretarias"].add(s.secretaria_id)
            if s.escola_id:       scope["escolas"].add(s.escola_id)
            if s.departamento_id: scope["departamentos"].add(s.departamento_id)
            if s.setor_id:        scope["setores"].add(s.setor_id)
    except Exception:
        pass

    # --- Acesso* (legado)
    try:
        for x in AcessoPrefeitura.objects.filter(user=user).values_list("prefeitura_id", flat=True):
            scope["prefeituras"].add(x)
    except Exception:
        pass
    try:
        for x in AcessoSecretaria.objects.filter(user=user).select_related("secretaria__prefeitura"):
            scope["secretarias"].add(x.secretaria_id)
            if x.secretaria and x.secretaria.prefeitura_id:
                scope["prefeituras"].add(x.secretaria.prefeitura_id)
    except Exception:
        pass
    try:
        for x in AcessoEscola.objects.filter(user=user).select_related("escola__secretaria__prefeitura"):
            scope["escolas"].add(x.escola_id)
            if x.escola and x.escola.secretaria_id:
                scope["secretarias"].add(x.escola.secretaria_id)
                if x.escola.secretaria.prefeitura_id:
                    scope["prefeituras"].add(x.escola.secretaria.prefeitura_id)
    except Exception:
        pass
    try:
        for x in AcessoSetor.objects.filter(user=user).select_related(
            "setor__departamento__secretaria__prefeitura", "setor__secretaria"
        ):
            scope["setores"].add(x.setor_id)
            es, sec, pref = _resolve_chain_from_setor(x.setor)
            if es:   scope["escolas"].add(es.id)
            if sec:  scope["secretarias"].add(sec.id)
            if pref: scope["prefeituras"].add(pref.id)
    except Exception:
        pass

    # --- cadeia do próprio funcionário
    try:
        f = getattr(user, "funcionario", None)
        if f and f.setor_id:
            scope["setores"].add(f.setor_id)
            es, sec, pref = _resolve_chain_from_setor(f.setor)
            if es:   scope["escolas"].add(es.id)
            if sec:  scope["secretarias"].add(sec.id)
            if pref: scope["prefeituras"].add(pref.id)
    except Exception:
        pass

    return scope


# ============================================================
# Filtros por escopo
# ============================================================
def _q_setor_scope(s: Dict[str, Any]) -> Q:
    return (
        Q(pk__in=s["setores"])
        | Q(departamento_id__in=s["departamentos"])
        | Q(departamento__escola_id__in=s["escolas"])
        | Q(departamento__secretaria_id__in=s["secretarias"])
        | Q(departamento__prefeitura_id__in=s["prefeituras"])
        | Q(secretaria_id__in=s["secretarias"])              # legado (campo direto no Setor)
    )

def filter_setores_by_scope(qs: QuerySet[Setor], user) -> QuerySet[Setor]:
    s = user_scope(user)
    if s["all"]:
        return qs
    return qs.filter(_q_setor_scope(s)).distinct()

def filter_funcionarios_by_scope(qs: QuerySet[Funcionario], user) -> QuerySet[Funcionario]:
    s = user_scope(user)
    if s["all"]:
        return qs
    cond = (
        Q(setor_id__in=s["setores"])
        | Q(setor__departamento_id__in=s["departamentos"])
        | Q(setor__departamento__escola_id__in=s["escolas"])
        | Q(setor__departamento__secretaria_id__in=s["secretarias"])
        | Q(setor__departamento__prefeitura_id__in=s["prefeituras"])
        | Q(setor__secretaria_id__in=s["secretarias"])  # legado
    )
    return qs.filter(cond).distinct()

def filter_folhas_by_scope(qs: QuerySet[FolhaFrequencia], user) -> QuerySet[FolhaFrequencia]:
    s = user_scope(user)
    if s["all"]:
        return qs
    cond = (
        Q(funcionario__setor_id__in=s["setores"])
        | Q(funcionario__setor__departamento_id__in=s["departamentos"])
        | Q(funcionario__setor__departamento__escola_id__in=s["escolas"])
        | Q(funcionario__setor__departamento__secretaria_id__in=s["secretarias"])
        | Q(funcionario__setor__departamento__prefeitura_id__in=s["prefeituras"])
        | Q(funcionario__setor__secretaria_id__in=s["secretarias"])  # legado
    )
    return qs.filter(cond).distinct()

def filter_horarios_by_scope(qs: QuerySet[HorarioTrabalho], user) -> QuerySet[HorarioTrabalho]:
    s = user_scope(user)
    if s["all"]:
        return qs
    cond = (
        Q(funcionario__setor_id__in=s["setores"])
        | Q(funcionario__setor__departamento_id__in=s["departamentos"])
        | Q(funcionario__setor__departamento__escola_id__in=s["escolas"])
        | Q(funcionario__setor__departamento__secretaria_id__in=s["secretarias"])
        | Q(funcionario__setor__departamento__prefeitura_id__in=s["prefeituras"])
        | Q(funcionario__setor__secretaria_id__in=s["secretarias"])  # legado
    )
    return qs.filter(cond).distinct()


# ============================================================
# Checagens pontuais
# ============================================================
def assert_can_access_funcionario(user, funcionario: Funcionario) -> bool:
    if _user_is_admin(user):
        return True
    return filter_funcionarios_by_scope(Funcionario.objects.filter(id=funcionario.id), user).exists()

def deny_and_redirect(request, message="Você não tem permissão para acessar este recurso.", to_name="painel_controle"):
    messages.error(request, message)
    return redirect(reverse(to_name))


# ============================================================
# Permissão por função/cargo do servidor-alvo
# ============================================================
DEFAULT_FUNCOES_GERENCIA = {
    "diretor", "diretor(a)", "coordenador", "coordenador(a)",
    "secretario", "secretário", "secretario(a)", "secretário(a)", "secretaria",
    "gestor", "gestor(a)", "admin", "administrador",
}

def has_funcao_permission(user, funcionario: Funcionario, required_nivel: str = LEITURA) -> bool:
    """
    True se 'user' puder operar sobre 'funcionario' considerando:
      1) escopo (precisa enxergar o servidor)
      2) nível requerido (LEITURA/GERENCIA)
      3) política por função (explícita via FuncaoPermissao se existir; senão, fallback por DEFAULT_FUNCOES_GERENCIA p/ GERENCIA)
    """
    if not _is_auth(user):
        return False
    if _user_is_admin(user):
        return True

    # 1) precisa ver o servidor
    if not assert_can_access_funcionario(user, funcionario):
        return False

    req = _nivel_to_int(required_nivel)
    funcao_alvo = _norm(getattr(funcionario, "funcao", ""))

    # 2) se existir modelo FuncaoPermissao, ele é a fonte da verdade
    if HAS_FUNCAO_PERMISSAO and funcao_alvo:
        setor = getattr(funcionario, "setor", None)
        sec = None
        if setor:
            # usa secretaria_oficial se existir no seu Setor
            sec = getattr(setor, "secretaria_oficial", None) or getattr(setor, "secretaria", None)

        qs = FuncaoPermissao.objects.filter(
            user=user,
            nome_funcao__iexact=funcao_alvo
        ).filter(
            Q(secretaria__isnull=True, setor__isnull=True) |
            Q(secretaria=sec) |
            Q(setor=setor)
        )
        for p in qs:
            if _nivel_to_int(p.nivel) >= req:
                return True
        # sem permissão explícita → nega
        return False

    # 3) fallback: se não há modelo, permite GERENCIA para funções padrão
    if req >= 1:  # GERENCIA
        minhas_funcoes = {_norm(getattr(getattr(user, "funcionario", None), "funcao", ""))}
        if minhas_funcoes & DEFAULT_FUNCOES_GERENCIA:
            return True
        return False

    # LEITURA: bastou ver pelo escopo
    return True


# ============================================================
# Checagem de nível (por alvo) para o motor de funcionalidades
# ============================================================
def _secretaria_do_setor(setor: Optional[Setor]) -> Optional[Secretaria]:
    if not setor:
        return None
    if getattr(setor, "departamento", None) and setor.departamento.secretaria_id:
        return setor.departamento.secretaria
    return getattr(setor, "secretaria", None)

def _has_leitura_em_secretaria(user, secretaria: Optional[Secretaria]) -> bool:
    if not _is_auth(user) or not secretaria:
        return False
    if _user_is_admin(user):
        return True
    try:
        if user.scopes.filter(Q(secretaria=secretaria) | Q(prefeitura=secretaria.prefeitura)).exists():
            return True
    except Exception:
        pass
    return AcessoSecretaria.objects.filter(user=user, secretaria=secretaria).exists()

def _has_gerencia_em_secretaria(user, secretaria: Optional[Secretaria]) -> bool:
    if not _is_auth(user) or not secretaria:
        return False
    if _user_is_admin(user):
        return True
    try:
        if user.scopes.filter(secretaria=secretaria, nivel=UserScope.Nivel.GERENCIA).exists():
            return True
        if user.scopes.filter(prefeitura=secretaria.prefeitura, nivel=UserScope.Nivel.GERENCIA).exists():
            return True
    except Exception:
        pass
    return AcessoSecretaria.objects.filter(user=user, secretaria=secretaria, nivel=NivelAcesso.GERENCIA).exists()

def _has_leitura_em_setor(user, setor: Optional[Setor]) -> bool:
    if not setor:
        return False
    if _user_is_admin(user):
        return True
    try:
        if user.scopes.filter(setor=setor).exists():
            return True
        sec = _secretaria_do_setor(setor)
        if sec and user.scopes.filter(Q(secretaria=sec) | Q(prefeitura=sec.prefeitura)).exists():
            return True
    except Exception:
        pass
    sec = _secretaria_do_setor(setor)
    return _has_leitura_em_secretaria(user, sec) if sec else False

def _has_gerencia_em_setor(user, setor: Optional[Setor]) -> bool:
    if not setor:
        return False
    if _user_is_admin(user):
        return True
    try:
        if user.scopes.filter(setor=setor, nivel=UserScope.Nivel.GERENCIA).exists():
            return True
    except Exception:
        pass
    return _has_gerencia_em_secretaria(user, _secretaria_do_setor(setor))

def _has_leitura_em_funcionario(user, funcionario: Optional[Funcionario]) -> bool:
    return _has_leitura_em_setor(user, getattr(funcionario, "setor", None))

def _has_gerencia_em_funcionario(user, funcionario: Optional[Funcionario]) -> bool:
    # além da gerência, também respeita a política por função do alvo
    if not _has_gerencia_em_setor(user, getattr(funcionario, "setor", None)):
        return False
    return has_funcao_permission(user, funcionario, GERENCIA)


# ============================================================
# Mapeamento das funcionalidades
# ============================================================
FEATURE_RULES: Dict[str, Dict[str, Any]] = {
    # Painel
    "VER_PAINEL":              {"nivel": LEITURA},

    # Funcionários
    "VER_FUNCIONARIOS":        {"nivel": LEITURA},
    "CAD_FUNCIONARIO":         {"nivel": GERENCIA},
    "EDIT_FUNCIONARIO":        {"nivel": GERENCIA},
    "EXCLUIR_FUNCIONARIO":     {"nivel": GERENCIA},

    # Horários
    "CAD_HORARIO":             {"nivel": GERENCIA},
    "EDIT_HORARIO":            {"nivel": GERENCIA},

    # Feriados
    "VER_FERIADOS":            {"nivel": LEITURA},
    "CAD_FERIADO":             {"nivel": GERENCIA},
    "EDIT_FERIADO":            {"nivel": GERENCIA},
    "EXCLUIR_FERIADO":         {"nivel": GERENCIA},

    # Folhas
    "VER_FOLHAS":              {"nivel": LEITURA},
    "VER_FOLHA":               {"nivel": LEITURA},
    "GERAR_FOLHA":             {"nivel": GERENCIA},
    "GERAR_FOLHAS_LOTE":       {"nivel": GERENCIA},
    "GERAR_FOLHAS_MULTI":      {"nivel": GERENCIA},
    "EXCLUIR_FOLHA":           {"nivel": GERENCIA},

    # Capa de livro
    "CAPA_LIVRO":              {"nivel": LEITURA},

    # Ficha funcional
    "VER_FICHA":               {"nivel": LEITURA},

    # Relatórios
    "REL_PERSONALIZADO":       {"nivel": LEITURA},
    "REL_PROFESSORES":         {"nivel": LEITURA},
    "RELATORIOS":              {"nivel": LEITURA},

    # Importações
    "IMPORTAR_FUNCIONARIOS":   {"nivel": GERENCIA},
    "IMPORTAR_HORARIOS":       {"nivel": GERENCIA},

    # Gestão de Acessos / Scopes (somente superadmin no frontend; aqui validamos nível)
    "ACESSOS_CONCEDER":        {"nivel": GERENCIA, "superuser_only": True},
    "ACESSOS_REVOGAR":         {"nivel": GERENCIA, "superuser_only": True},
    "SCOPES_MANAGER":          {"nivel": GERENCIA, "superuser_only": True},
    "SCOPES_DEBUG":            {"nivel": GERENCIA, "superuser_only": True},
}

def user_can_feature(user, feature: str, alvo: Optional[object] = None) -> bool:
    """
    Verifica se o usuário pode usar 'feature'.
    - Respeita 'superuser_only'
    - Respeita nível (LEITURA/GERENCIA)
    - Aplica escopo por 'alvo' quando informado (Funcionario/Setor/Secretaria/...)
    - Para GERENCIA sobre servidores: inclui regra de função (has_funcao_permission)
    """
    if not _is_auth(user):
        return False

    rule = FEATURE_RULES.get(str(feature).upper())
    if not rule:
        return False

    if rule.get("superuser_only") and not getattr(user, "is_superuser", False):
        return False

    nivel = rule["nivel"]

    # Sem alvo específico → precisa ter algum escopo compatível
    if alvo is None:
        if _user_is_admin(user):
            return True
        sc = user_scope(user)
        if nivel == GERENCIA:
            # tem algum escopo GERENCIA via UserScope ou AcessoSecretaria GERENCIA?
            try:
                if user.scopes.filter(nivel=UserScope.Nivel.GERENCIA).exists():
                    return True
            except Exception:
                pass
            try:
                if AcessoSecretaria.objects.filter(user=user, nivel=NivelAcesso.GERENCIA).exists():
                    return True
            except Exception:
                pass
            return False
        return any(sc[k] for k in ("prefeituras", "secretarias", "escolas", "departamentos", "setores"))

    # Com alvo
    if isinstance(alvo, Funcionario):
        return _has_gerencia_em_funcionario(user, alvo) if nivel == GERENCIA else _has_leitura_em_funcionario(user, alvo)
    if isinstance(alvo, Setor):
        return _has_gerencia_em_setor(user, alvo)       if nivel == GERENCIA else _has_leitura_em_setor(user, alvo)
    if isinstance(alvo, Secretaria):
        return _has_gerencia_em_secretaria(user, alvo)  if nivel == GERENCIA else _has_leitura_em_secretaria(user, alvo)
    if isinstance(alvo, Departamento):
        if alvo.secretaria:
            return user_can_feature(user, feature, alvo.secretaria)
        if alvo.escola and alvo.escola.secretaria:
            return user_can_feature(user, feature, alvo.escola.secretaria)
        if alvo.prefeitura:
            return _user_is_admin(user) if nivel == GERENCIA else True
        return False
    if isinstance(alvo, Escola):
        return user_can_feature(user, feature, alvo.secretaria) if alvo.secretaria else _user_is_admin(user)
    if isinstance(alvo, Prefeitura):
        if _user_is_admin(user):
            return True
        try:
            if nivel == GERENCIA:
                return user.scopes.filter(prefeitura=alvo, nivel=UserScope.Nivel.GERENCIA).exists()
            return user.scopes.filter(prefeitura=alvo).exists()
        except Exception:
            return False

    return False


# Decorator útil para views de ação
def require_feature(
    feature: str,
    resolver: Optional[Callable] = None,
    deny_message: str = "Você não tem permissão para executar esta ação."
):
    """
    Uso:
      @login_required
      @require_feature('GERAR_FOLHAS_LOTE', resolver=lambda req,*a,**kw: Setor.objects.filter(pk=req.POST.get('setor')).first())
      def gerar_folhas_em_lote(...):
          ...
    """
    def _outer(viewfunc):
        def _inner(request, *args, **kwargs):
            alvo = resolver(request, *args, **kwargs) if callable(resolver) else None
            if not user_can_feature(request.user, feature, alvo):
                return deny_and_redirect(request, deny_message)
            return viewfunc(request, *args, **kwargs)
        return _inner
    return _outer
