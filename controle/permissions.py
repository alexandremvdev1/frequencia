# controle/permissions.py
from __future__ import annotations

from typing import Optional, Callable, Any, Dict, Tuple

from django.contrib import messages
from django.db.models import Q, QuerySet
from django.shortcuts import redirect
from django.urls import reverse

from .models import (
    Prefeitura, Secretaria, Setor, Funcionario, UserScope,
    AcessoPrefeitura, AcessoSecretaria, AcessoSetor,
    HorarioTrabalho, FolhaFrequencia, NivelAcesso,
)

# ==== imports opcionais (novos e legados) ====================================
# Novo: Órgão + AcessoÓrgão (se existirem no seu projeto)
try:
    from .models import Orgao  # type: ignore
except Exception:
    Orgao = None  # type: ignore

try:
    from .models import AcessoOrgao  # type: ignore
    HAS_ACESSO_ORGAO = True
except Exception:
    AcessoOrgao = None  # type: ignore
    HAS_ACESSO_ORGAO = False

# Legado: Escola/Departamento + AcessoEscola (se ainda existirem)
try:
    from .models import Escola, Departamento, AcessoEscola  # type: ignore
    HAS_ESCOLA_DEPARTAMENTO = True
except Exception:
    Escola = None  # type: ignore
    Departamento = None  # type: ignore
    AcessoEscola = None  # type: ignore
    HAS_ESCOLA_DEPARTAMENTO = False

# Suporte opcional a controle por função/cargo
try:
    from .models import FuncaoPermissao  # campos: user, nome_funcao, nivel, secretaria(nullable), setor(nullable)
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
# (novo: orgao→secretaria→prefeitura; legados suportados)
# ============================================================
def _resolve_chain_from_setor(setor: Setor) -> Tuple[Any | None, Secretaria | None, Prefeitura | None]:
    """
    Retorna (orgao, secretaria, prefeitura) a partir de um Setor,
    fazendo fallback para campos legados quando presentes.
    """
    orgao = getattr(setor, "orgao", None) if hasattr(setor, "orgao") else None
    secretaria = None
    prefeitura = None

    # secretaria direta no setor (legado)
    if hasattr(setor, "secretaria") and getattr(setor, "secretaria_id", None):
        secretaria = setor.secretaria

    # secretaria por órgão (novo)
    if not secretaria and orgao is not None and hasattr(orgao, "secretaria"):
        secretaria = getattr(orgao, "secretaria", None)

    # prefeitura direta no setor (se existir)
    if hasattr(setor, "prefeitura") and getattr(setor, "prefeitura_id", None):
        prefeitura = setor.prefeitura

    # prefeitura por secretaria (novo/legado)
    if not prefeitura and secretaria is not None and hasattr(secretaria, "prefeitura"):
        prefeitura = getattr(secretaria, "prefeitura", None)

    # Fallback extra (legado via departamento → escola → secretaria → prefeitura)
    if (not orgao or not secretaria or not prefeitura) and HAS_ESCOLA_DEPARTAMENTO and hasattr(setor, "departamento"):
        dep = getattr(setor, "departamento", None)
        if dep:
            if not orgao and hasattr(dep, "escola"):
                # não há 'orgao' no legado: mantemos None
                pass
            if not secretaria and hasattr(dep, "secretaria"):
                secretaria = getattr(dep, "secretaria", None)
            if not prefeitura and hasattr(dep, "prefeitura"):
                prefeitura = getattr(dep, "prefeitura", None)

    return orgao, secretaria, prefeitura


# ============================================================
# Escopo consolidado do usuário
# ============================================================
def user_scope(user) -> Dict[str, Any]:
    """
    Retorna um dicionário com IDs permitidos por nível.
    Inclui escopos:
      - Admin (all=True)
      - UserScope (prefeitura/secretaria/orgao/setor) [+ legado: escola/departamento]
      - Acesso* (Prefeitura/Secretaria/[Órgão]/Setor e legado Escola)
      - Unidade do próprio funcionário (cadeia do setor)
    """
    scope: Dict[str, Any] = {
        "all": False,
        "prefeituras": set(), "secretarias": set(), "orgaos": set(), "setores": set(),
        # legados (não usados nos filtros novos, mas aceitos se existirem)
        "escolas": set(), "departamentos": set(),
    }

    if not _is_auth(user):
        return scope

    if _user_is_admin(user):
        scope["all"] = True
        return scope

    # --- UserScope (novo + legado)
    try:
        for s in user.scopes.all():
            if getattr(s, "prefeitura_id", None):   scope["prefeituras"].add(s.prefeitura_id)
            if getattr(s, "secretaria_id", None):   scope["secretarias"].add(s.secretaria_id)
            if getattr(s, "orgao_id", None):        scope["orgaos"].add(s.orgao_id)
            if getattr(s, "setor_id", None):        scope["setores"].add(s.setor_id)
            if HAS_ESCOLA_DEPARTAMENTO and getattr(s, "escola_id", None):
                scope["escolas"].add(s.escola_id)
            if HAS_ESCOLA_DEPARTAMENTO and getattr(s, "departamento_id", None):
                scope["departamentos"].add(s.departamento_id)
    except Exception:
        pass

    # --- Acesso* (atuais + legado escola)
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

    if HAS_ACESSO_ORGAO:
        try:
            for x in AcessoOrgao.objects.filter(user=user).select_related("orgao__secretaria__prefeitura"):
                scope["orgaos"].add(x.orgao_id)
                orgao = getattr(x, "orgao", None)
                if orgao and getattr(orgao, "secretaria_id", None):
                    scope["secretarias"].add(orgao.secretaria_id)
                    sec = getattr(orgao, "secretaria", None)
                    if sec and getattr(sec, "prefeitura_id", None):
                        scope["prefeituras"].add(sec.prefeitura_id)
        except Exception:
            pass

    try:
        for x in AcessoSetor.objects.filter(user=user).select_related(
            "setor__orgao__secretaria__prefeitura", "setor__secretaria", "setor__prefeitura"
        ):
            scope["setores"].add(x.setor_id)
            org, sec, pref = _resolve_chain_from_setor(x.setor)
            if org and getattr(org, "id", None):  scope["orgaos"].add(org.id)
            if sec and getattr(sec, "id", None):  scope["secretarias"].add(sec.id)
            if pref and getattr(pref, "id", None): scope["prefeituras"].add(pref.id)
    except Exception:
        pass

    if HAS_ESCOLA_DEPARTAMENTO and AcessoEscola is not None:
        try:
            for x in AcessoEscola.objects.filter(user=user).select_related("escola__secretaria__prefeitura"):
                scope["escolas"].add(x.escola_id)
                esc = getattr(x, "escola", None)
                if esc and getattr(esc, "secretaria_id", None):
                    scope["secretarias"].add(esc.secretaria_id)
                    sec = getattr(esc, "secretaria", None)
                    if sec and getattr(sec, "prefeitura_id", None):
                        scope["prefeituras"].add(sec.prefeitura_id)
        except Exception:
            pass

    # --- cadeia do próprio funcionário
    try:
        f = getattr(user, "funcionario", None)
        if f and f.setor_id:
            scope["setores"].add(f.setor_id)
            org, sec, pref = _resolve_chain_from_setor(f.setor)
            if org and getattr(org, "id", None):  scope["orgaos"].add(org.id)
            if sec and getattr(sec, "id", None):  scope["secretarias"].add(sec.id)
            if pref and getattr(pref, "id", None): scope["prefeituras"].add(pref.id)
    except Exception:
        pass

    return scope


# ============================================================
# Filtros por escopo
# ============================================================
def _q_setor_scope(s: Dict[str, Any]) -> Q:
    cond = (
        Q(pk__in=s["setores"])
        | Q(orgao_id__in=s["orgaos"])
        | Q(secretaria_id__in=s["secretarias"])                  # legado: secretaria no Setor
        | Q(orgao__secretaria_id__in=s["secretarias"])
        | Q(prefeitura_id__in=s["prefeituras"])                  # se houver campo direto
        | Q(secretaria__prefeitura_id__in=s["prefeituras"])
        | Q(orgao__secretaria__prefeitura_id__in=s["prefeituras"])
    )
    # compat extra com legado por Departamento, se houver relação
    if HAS_ESCOLA_DEPARTAMENTO and hasattr(Setor, "departamento"):
        cond = cond | Q(departamento_id__in=s["departamentos"]) \
                    | Q(departamento__secretaria_id__in=s["secretarias"]) \
                    | Q(departamento__prefeitura_id__in=s["prefeituras"])  # noqa
    return cond

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
        | Q(setor__orgao_id__in=s["orgaos"])
        | Q(setor__secretaria_id__in=s["secretarias"])                 # legado
        | Q(setor__orgao__secretaria_id__in=s["secretarias"])
        | Q(setor__prefeitura_id__in=s["prefeituras"])                 # se houver campo direto
        | Q(setor__secretaria__prefeitura_id__in=s["prefeituras"])
        | Q(setor__orgao__secretaria__prefeitura_id__in=s["prefeituras"])
    )
    if HAS_ESCOLA_DEPARTAMENTO and hasattr(Setor, "departamento"):
        cond = cond | Q(setor__departamento_id__in=s["departamentos"]) \
                    | Q(setor__departamento__secretaria_id__in=s["secretarias"]) \
                    | Q(setor__departamento__prefeitura_id__in=s["prefeituras"])  # noqa
    return qs.filter(cond).distinct()

def filter_folhas_by_scope(qs: QuerySet[FolhaFrequencia], user) -> QuerySet[FolhaFrequencia]:
    s = user_scope(user)
    if s["all"]:
        return qs
    cond = (
        Q(funcionario__setor_id__in=s["setores"])
        | Q(funcionario__setor__orgao_id__in=s["orgaos"])
        | Q(funcionario__setor__secretaria_id__in=s["secretarias"])                         # legado
        | Q(funcionario__setor__orgao__secretaria_id__in=s["secretarias"])
        | Q(funcionario__setor__prefeitura_id__in=s["prefeituras"])                         # se houver campo direto
        | Q(funcionario__setor__secretaria__prefeitura_id__in=s["prefeituras"])
        | Q(funcionario__setor__orgao__secretaria__prefeitura_id__in=s["prefeituras"])
    )
    if HAS_ESCOLA_DEPARTAMENTO and hasattr(Setor, "departamento"):
        cond = cond | Q(funcionario__setor__departamento_id__in=s["departamentos"]) \
                    | Q(funcionario__setor__departamento__secretaria_id__in=s["secretarias"]) \
                    | Q(funcionario__setor__departamento__prefeitura_id__in=s["prefeituras"])  # noqa
    return qs.filter(cond).distinct()

def filter_horarios_by_scope(qs: QuerySet[HorarioTrabalho], user) -> QuerySet[HorarioTrabalho]:
    s = user_scope(user)
    if s["all"]:
        return qs
    cond = (
        Q(funcionario__setor_id__in=s["setores"])
        | Q(funcionario__setor__orgao_id__in=s["orgaos"])
        | Q(funcionario__setor__secretaria_id__in=s["secretarias"])                         # legado
        | Q(funcionario__setor__orgao__secretaria_id__in=s["secretarias"])
        | Q(funcionario__setor__prefeitura_id__in=s["prefeituras"])                         # se houver campo direto
        | Q(funcionario__setor__secretaria__prefeitura_id__in=s["prefeituras"])
        | Q(funcionario__setor__orgao__secretaria__prefeitura_id__in=s["prefeituras"])
    )
    if HAS_ESCOLA_DEPARTAMENTO and hasattr(Setor, "departamento"):
        cond = cond | Q(funcionario__setor__departamento_id__in=s["departamentos"]) \
                    | Q(funcionario__setor__departamento__secretaria_id__in=s["secretarias"]) \
                    | Q(funcionario__setor__departamento__prefeitura_id__in=s["prefeituras"])  # noqa
    return qs.filter(cond).distinct()


# ============================================================
# Checagens pontuais
# ============================================================
def assert_can_access_funcionario(user, funcionario: Funcionario) -> bool:
    if _user_is_admin(user):
        return True
    return filter_funcionarios_by_scope(Funcionario.objects.filter(id=funcionario.id), user).exists()

def deny_and_redirect(request, message="Você não tem permissão para acessar este recurso.", to: Optional[str] = None, to_name: Optional[str] = None):
    """
    Aceita 'to=' ou 'to_name='; se nenhum for informado, usa 'controle:painel_controle'.
    """
    messages.error(request, message)
    target = to or to_name or "controle:painel_controle"
    return redirect(reverse(target))


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

        # resolve secretaria (novo ou legado)
        sec = None
        if setor:
            # propriedades utilitárias podem existir no seu Setor; caímos para fallback
            sec = getattr(setor, "secretaria_resolvida", None)
            if not sec:
                sec = getattr(setor, "secretaria_oficial", None) or getattr(setor, "secretaria", None)
            if not sec and getattr(setor, "orgao", None):
                sec = getattr(setor.orgao, "secretaria", None)

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
    # prioridade: helpers novos se existirem
    sec = getattr(setor, "secretaria_resolvida", None)
    if sec:
        return sec
    # compat: oficial/legado
    if hasattr(setor, "secretaria_oficial") and getattr(setor, "secretaria_oficial", None):
        return setor.secretaria_oficial
    if hasattr(setor, "secretaria") and getattr(setor, "secretaria", None):
        return setor.secretaria
    # via órgão
    if hasattr(setor, "orgao") and getattr(setor, "orgao", None):
        return getattr(setor.orgao, "secretaria", None)
    return None

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
    - Aplica escopo por 'alvo' quando informado (Funcionario/Setor/Secretaria/Prefeitura)
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
        # GERENCIA global: precisa ter algum escopo GERENCIA
        if nivel == GERENCIA:
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
            try:
                if AcessoPrefeitura.objects.filter(user=user, nivel=NivelAcesso.GERENCIA).exists():
                    return True
            except Exception:
                pass
            if HAS_ACESSO_ORGAO:
                try:
                    if AcessoOrgao.objects.filter(user=user, nivel=NivelAcesso.GERENCIA).exists():
                        return True
                except Exception:
                    pass
            return False
        # LEITURA: qualquer escopo já basta
        sc = user_scope(user)
        return any(sc[k] for k in ("prefeituras", "secretarias", "orgaos", "setores", "escolas", "departamentos"))

    # Com alvo específico
    if isinstance(alvo, Funcionario):
        return _has_gerencia_em_funcionario(user, alvo) if nivel == GERENCIA else _has_leitura_em_funcionario(user, alvo)
    if isinstance(alvo, Setor):
        return _has_gerencia_em_setor(user, alvo)       if nivel == GERENCIA else _has_leitura_em_setor(user, alvo)
    if isinstance(alvo, Secretaria):
        return _has_gerencia_em_secretaria(user, alvo)  if nivel == GERENCIA else _has_leitura_em_secretaria(user, alvo)
    if isinstance(alvo, Prefeitura):
        if _user_is_admin(user):
            return True
        try:
            if nivel == GERENCIA:
                return user.scopes.filter(prefeitura=alvo, nivel=UserScope.Nivel.GERENCIA).exists()
            return user.scopes.filter(prefeitura=alvo).exists()
        except Exception:
            return False

    # Alvos legados (se ainda existirem no seu projeto)
    if HAS_ESCOLA_DEPARTAMENTO and Escola is not None and isinstance(alvo, Escola):
        return user_can_feature(user, feature, getattr(alvo, "secretaria", None)) if getattr(alvo, "secretaria", None) else _user_is_admin(user)
    if HAS_ESCOLA_DEPARTAMENTO and Departamento is not None and isinstance(alvo, Departamento):
        sec = getattr(alvo, "secretaria", None)
        if sec:
            return user_can_feature(user, feature, sec)
        pref = getattr(alvo, "prefeitura", None)
        if pref:
            return _user_is_admin(user) if nivel == GERENCIA else True
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
