# controle/views.py
import calendar
import locale
from calendar import monthrange
from datetime import date, datetime, timedelta

import pandas as pd

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import LoginView, LogoutView
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_GET, require_http_methods
from django.core.paginator import Paginator

from .forms import (
    HorarioTrabalhoForm,
    FeriadoForm,
    ImportacaoFuncionarioForm,   # se não usar, pode remover
    GerarFolhasIndividuaisForm,
    FuncionarioForm,
    RecessoBulkForm,
    RecessoFuncionarioForm,
)

from .models import (
    Prefeitura, Secretaria, Orgao, Setor, Funcionario,
    Feriado, HorarioTrabalho, SabadoLetivo, FolhaFrequencia, UserScope,
    RecessoFuncionario,
)

# ---- permissões/escopo ----
from .permissions import (
    user_scope,
    filter_setores_by_scope,
    filter_funcionarios_by_scope,
    filter_folhas_by_scope,
    filter_horarios_by_scope,
    assert_can_access_funcionario,
    deny_and_redirect,
)

User = get_user_model()

# =====================================================================
# BLOCO: Gestão de Acessos / Escopos (superadmin)
# =====================================================================

def _is_superadmin(user):
    return user.is_authenticated and user.is_superuser

def _only_superuser(user):
    return _is_superadmin(user)

@login_required
@user_passes_test(_only_superuser)
def acessos_conceder(request):
    """
    Concede um escopo para um usuário: Prefeitura OU Secretaria OU Órgão OU Setor (exatamente 1).
    Nível: LEITURA ou GERENCIA.
    """
    if request.method == "POST":
        user_id = request.POST.get("user")
        nivel = (request.POST.get("nivel") or "LEITURA").upper()

        pref_id = request.POST.get("prefeitura") or ""
        sec_id  = request.POST.get("secretaria") or ""
        org_id  = request.POST.get("orgao") or ""
        set_id  = request.POST.get("setor") or ""

        if not user_id:
            messages.error(request, "Selecione um usuário.")
            return redirect("controle:acessos_conceder")

        try:
            alvo_user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            messages.error(request, "Usuário inválido.")
            return redirect("controle:acessos_conceder")

        escolhas = [
            ("prefeitura_id", pref_id),
            ("secretaria_id", sec_id),
            ("orgao_id", org_id),
            ("setor_id", set_id),
        ]
        preenchidas = [(k, v) for k, v in escolhas if v]
        if len(preenchidas) != 1:
            messages.error(request, "Selecione exatamente um nível de alvo (Prefeitura OU Secretaria OU Órgão OU Setor).")
            return redirect("controle:acessos_conceder")

        kwargs = {"user": alvo_user, "nivel": nivel}
        chave, valor = preenchidas[0]
        kwargs[chave] = valor

        scope, created = UserScope.objects.get_or_create(**kwargs)
        if created:
            messages.success(request, "Acesso concedido com sucesso.")
        else:
            messages.info(request, "Este acesso já existia para o usuário.")

        return redirect("controle:acessos_conceder")

    # GET — carrega listas para selects
    contexto = {
        "usuarios": User.objects.order_by("username", "first_name", "last_name"),
        "prefeituras": Prefeitura.objects.order_by("nome"),
        "secretarias": Secretaria.objects.select_related("prefeitura").order_by("prefeitura__nome", "nome"),
        "orgaos": Orgao.objects.select_related("secretaria", "secretaria__prefeitura").order_by("secretaria__prefeitura__nome", "secretaria__nome", "nome"),
        "setores": Setor.objects.select_related("prefeitura", "secretaria", "orgao").order_by("nome"),
        "niveis": [("LEITURA", "Leitura"), ("GERENCIA", "Gerenciar (CRUD)")],
        "escopos_recentes": UserScope.objects.select_related("user", "prefeitura", "secretaria", "orgao", "setor").order_by("-id")[:25],
    }
    return render(request, "controle/acessos_conceder.html", contexto)

@login_required
@user_passes_test(_only_superuser)
def acessos_revogar(request):
    """
    Lista e permite revogar escopos (UserScope) já concedidos.
    Filtro por usuário/entidade via GET ?q=
    """
    qs = UserScope.objects.select_related("user", "prefeitura", "secretaria", "orgao", "setor")
    q = (request.GET.get("q") or "").strip()

    if q:
        qs = qs.filter(
            Q(user__username__icontains=q) |
            Q(user__first_name__icontains=q) |
            Q(user__last_name__icontains=q) |
            Q(prefeitura__nome__icontains=q) |
            Q(secretaria__nome__icontains=q) |
            Q(orgao__nome__icontains=q) |
            Q(setor__nome__icontains=q)
        )

    if request.method == "POST":
        scope_id = request.POST.get("scope_id")
        scope = get_object_or_404(UserScope, pk=scope_id)
        scope.delete()
        messages.success(request, "Acesso revogado.")
        url = reverse("controle:acessos_revogar")
        if q:
            url += f"?q={q}"
        return redirect(url)

    contexto = {
        "q": q,
        "escopos": qs.order_by("user__username", "prefeitura__nome", "secretaria__nome", "orgao__nome", "setor__nome"),
        "usuarios": User.objects.order_by("username", "first_name", "last_name"),
    }
    return render(request, "controle/acessos_revogar.html", contexto)

@login_required
@user_passes_test(_is_superadmin)
def scope_manager(request):
    """
    Tela de gestão de escopos (somente superadmin)
    - Lista escopos existentes
    - Permite adicionar/remover escopos para QUALQUER usuário
    """
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "add":
            user_id   = request.POST.get("user_id")
            nivel     = request.POST.get("nivel") or UserScope.Nivel.GERENCIA
            alvo_tipo = request.POST.get("alvo_tipo")   # prefeitura/secretaria/orgao/setor
            alvo_id   = request.POST.get("alvo_id")

            if not (user_id and alvo_tipo and alvo_id):
                messages.error(request, "Preencha usuário, alvo e nível.")
                return redirect("controle:scope_manager")

            try:
                alvo_id_int = int(alvo_id)
            except ValueError:
                messages.error(request, "ID do alvo inválido.")
                return redirect("controle:scope_manager")

            scope_kwargs = {
                "user_id": user_id,
                "nivel": nivel,
                "prefeitura": None, "secretaria": None, "orgao": None, "setor": None,
            }

            if alvo_tipo == "prefeitura":
                scope_kwargs["prefeitura_id"] = alvo_id_int
            elif alvo_tipo == "secretaria":
                scope_kwargs["secretaria_id"]  = alvo_id_int
            elif alvo_tipo == "orgao":
                scope_kwargs["orgao_id"]       = alvo_id_int
            elif alvo_tipo == "setor":
                scope_kwargs["setor_id"]       = alvo_id_int
            else:
                messages.error(request, "Tipo de alvo inválido.")
                return redirect("controle:scope_manager")

            try:
                UserScope.objects.create(**scope_kwargs)
                messages.success(request, "Escopo adicionado com sucesso.")
            except IntegrityError:
                messages.warning(request, "Esse escopo já existe para o usuário.")
            return redirect("controle:scope_manager")

        elif action == "delete":
            scope_id = request.POST.get("scope_id")
            scope = get_object_or_404(UserScope, id=scope_id)
            scope.delete()
            messages.success(request, "Escopo removido.")
            return redirect("controle:scope_manager")

    scopes = (UserScope.objects
              .select_related("user", "prefeitura", "secretaria", "orgao", "setor")
              .order_by("user__username"))

    prefeituras = Prefeitura.objects.order_by("nome")
    secretarias = Secretaria.objects.select_related("prefeitura").order_by("prefeitura__nome", "nome")
    orgaos      = Orgao.objects.select_related("secretaria", "secretaria__prefeitura").order_by("secretaria__prefeitura__nome", "secretaria__nome", "nome")
    setores     = Setor.objects.select_related("prefeitura", "secretaria", "orgao").order_by("nome")
    users       = User.objects.order_by("username", "first_name", "last_name")

    ctx = {
        "scopes": scopes,
        "users": users,
        "prefeituras": prefeituras,
        "secretarias": secretarias,
        "orgaos": orgaos,
        "setores": setores,
    }
    return render(request, "controle/scope_manager.html", ctx)

@login_required
@user_passes_test(_is_superadmin)
def scope_debug(request):
    meus_scopes = (request.user.scopes
                   .select_related("prefeitura", "secretaria", "orgao", "setor")
                   .all())
    return render(request, "controle/scope_debug.html", {"meus_scopes": meus_scopes})

# =====================================================================
# Autenticação (Login / Logout)
# =====================================================================

class PainelLoginView(LoginView):
    template_name = "controle/login.html"
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Compat: alguns templates podem esperar "escola". Mantemos como None.
        ctx["orgao"] = Orgao.objects.select_related("secretaria", "secretaria__prefeitura").first()
        ctx["escola"] = None
        return ctx

class PainelLogoutView(LogoutView):
    next_page = "login"

# =====================================================================
# Constantes (pt-BR)
# =====================================================================

dias_da_semana_pt = {
    0: 'segunda-feira', 1: 'terça-feira', 2: 'quarta-feira',
    3: 'quinta-feira', 4: 'sexta-feira', 5: 'sábado', 6: 'domingo'
}
meses_pt = {
    1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
    5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
    9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
}

# -------- helper p/ extrair URL de logo (Cloudinary/FileField) --------
def _safe_logo_url(obj, attr='logo'):
    if not obj:
        return None
    try:
        field = getattr(obj, attr, None)
    except Exception:
        return None
    if not field:
        return None
    try:
        return field.url
    except Exception:
        return None

# =====================================================================
# Folha de frequência (individual)
# =====================================================================

@login_required
def gerar_folha_frequencia(request, funcionario_id, mes, ano):
    funcionario = get_object_or_404(Funcionario, id=funcionario_id)

    # --- PERMISSÃO ---
    if not assert_can_access_funcionario(request.user, funcionario):
        return deny_and_redirect(request, "Você não pode gerar/visualizar folhas deste servidor.")

    # Hierarquia resolvida
    setor = getattr(funcionario, "setor", None)
    orgao = getattr(setor, "orgao", None) if setor else None
    secretaria_obj = setor.secretaria_resolvida if setor else None
    prefeitura_obj = setor.prefeitura_resolvida if setor else None

    # Chefe do setor
    chefe_setor_nome = None
    chefe_setor_funcao = None
    if funcionario.setor_id:
        chefe = (Funcionario.objects
                 .only("nome", "funcao", "setor_id", "is_chefe_setor")
                 .filter(setor_id=funcionario.setor_id, is_chefe_setor=True)
                 .first())
        if chefe:
            chefe_setor_nome = chefe.nome
            chefe_setor_funcao = chefe.funcao

    # Cabeçalhos
    header_prefeitura = getattr(prefeitura_obj, "nome", None)
    header_secretaria = getattr(secretaria_obj, "nome", None)
    header_orgao      = getattr(orgao, "nome", None)
    header_setor      = getattr(setor, "nome", None)

    # LOGOS
    logo_orgao      = _safe_logo_url(orgao, 'logo')            # centro
    logo_prefeitura = _safe_logo_url(prefeitura_obj, 'logo')   # lateral
    logo_secretaria = _safe_logo_url(secretaria_obj, 'logo')   # lateral

    # Datas / calendário
    total_dias = monthrange(ano, mes)[1]
    datas_do_mes = [date(ano, mes, d) for d in range(1, total_dias + 1)]
    primeiro_dia_mes = date(ano, mes, 1)
    ultimo_dia_mes = date(ano, mes, total_dias)

    # Feriados / Sábados letivos / Horários
    feriados = Feriado.objects.filter(data__month=mes, data__year=ano)
    feriados_dict = {f.data: f.descricao for f in feriados}

    sabados_letivos = SabadoLetivo.objects.filter(data__month=mes, data__year=ano)
    sabados_letivos_dict = {s.data: s.descricao for s in sabados_letivos}

    horarios = HorarioTrabalho.objects.filter(funcionario=funcionario)
    horario_manha = horarios.filter(turno__iexact='Manhã').first()
    horario_tarde = horarios.filter(turno__iexact='Tarde').first()

    # Recessos
    recessos_qs = RecessoFuncionario.objects.filter(
        funcionario=funcionario,
        data_inicio__lte=ultimo_dia_mes,
        data_fim__gte=primeiro_dia_mes,
    )
    recesso_por_dia = {}
    for r in recessos_qs:
        inicio = max(r.data_inicio, primeiro_dia_mes)
        fim    = min(r.data_fim, ultimo_dia_mes)
        d = inicio
        while d <= fim:
            recesso_por_dia[d] = (r.motivo or "Recesso")
            d += timedelta(days=1)

    # Monta dias
    dias = []
    for data_atual in datas_do_mes:
        dia_semana = dias_da_semana_pt[data_atual.weekday()]

        if data_atual in recesso_por_dia:
            dias.append({
                'data': data_atual, 'dia_semana': dia_semana,
                'manha': horario_manha, 'tarde': horario_tarde,
                'recesso': True, 'descricao': recesso_por_dia[data_atual],
                'feriado': False, 'sabado_letivo': False
            })
        elif data_atual.weekday() == 5 and data_atual in sabados_letivos_dict:
            dias.append({
                'data': data_atual, 'dia_semana': dia_semana,
                'manha': horario_manha, 'tarde': horario_tarde,
                'feriado': False, 'sabado_letivo': True
            })
        elif data_atual in feriados_dict:
            dias.append({
                'data': data_atual, 'dia_semana': dia_semana,
                'manha': horario_manha, 'tarde': horario_tarde,
                'feriado': True, 'descricao': feriados_dict[data_atual]
            })
        else:
            dias.append({
                'data': data_atual, 'dia_semana': dia_semana,
                'manha': horario_manha, 'tarde': horario_tarde,
                'feriado': False
            })

    # Planejamento (segundas)
    planejamento = []
    if (funcionario.funcao or "").lower() == "professor(a)" and funcionario.tem_planejamento:
        for d in datas_do_mes:
            if (d.weekday() == 0) and (d not in feriados_dict) and (d not in recesso_por_dia):
                planejamento.append({
                    'data': d,
                    'dia_semana': dias_da_semana_pt[d.weekday()],
                    'horario': funcionario.horario_planejamento
                })

    context = {
        'funcionario': funcionario,
        'dias': dias,
        'planejamento': planejamento,
        'mes': mes,
        'ano': ano,
        'nome_mes': meses_pt[mes],

        # hierarquia/headers
        'header_prefeitura': header_prefeitura,
        'header_secretaria': header_secretaria,
        'header_orgao': header_orgao,
        'header_setor': header_setor,

        # compat legada (se template ainda usa):
        'header_departamento': header_orgao,
        'escola': None,

        # chefe
        'chefe_setor_nome': chefe_setor_nome,
        'chefe_setor_funcao': chefe_setor_funcao,
        'ultimo_dia_mes': ultimo_dia_mes,

        # logos para a faixa superior
        'logo_prefeitura': logo_prefeitura,
        'logo_secretaria': logo_secretaria,
        'logo_orgao': logo_orgao,
    }

    html_renderizado = render_to_string('controle/folha_frequencia.html', context)

    FolhaFrequencia.objects.update_or_create(
        funcionario=funcionario,
        mes=mes,
        ano=ano,
        defaults={'html_armazenado': html_renderizado}
    )

    return HttpResponse(html_renderizado)

# =====================================================================
# Folhas em lote
# =====================================================================

@login_required
def gerar_folhas_em_lote(request):
    if request.method != 'POST':
        return render(request, 'controle/folhas_em_lote.html', {'folhas': []})

    ids_funcionarios = request.POST.getlist('funcionarios')
    mes_str = request.POST.get('mes')
    ano_str = request.POST.get('ano')

    try:
        mes = int(mes_str) if mes_str else None
        ano = int(ano_str) if ano_str else None
    except ValueError:
        mes = ano = None

    if not ids_funcionarios:
        messages.error(request, "Selecione pelo menos um funcionário.")
        return redirect('controle:selecionar_funcionarios')

    if not mes or not ano:
        messages.error(request, "Informe mês e ano válidos.")
        return redirect('controle:selecionar_funcionarios')

    permitidos_qs = filter_funcionarios_by_scope(
        Funcionario.objects.filter(id__in=ids_funcionarios), request.user
    ).values_list('id', 'nome')
    mapa_nomes = {str(i): (n or '') for i, n in permitidos_qs}
    permitidos = list(mapa_nomes.keys())

    barrados = [pk for pk in ids_funcionarios if str(pk) not in mapa_nomes]
    if barrados:
        messages.warning(request, f"{len(barrados)} funcionário(s) fora do seu escopo foram ignorados.")

    ids_funcionarios_ordenados = sorted(permitidos, key=lambda pk: mapa_nomes.get(str(pk), '').casefold())
    folhas_renderizadas = []

    for id_func in ids_funcionarios_ordenados:
        funcionario = get_object_or_404(Funcionario, id=id_func)

        # Hierarquia resolvida
        setor = getattr(funcionario, "setor", None)
        orgao = getattr(setor, "orgao", None) if setor else None
        secretaria = setor.secretaria_resolvida if setor else None
        prefeitura = setor.prefeitura_resolvida if setor else None

        # Chefia
        chefe = Funcionario.objects.filter(setor=funcionario.setor, is_chefe_setor=True).only("nome", "funcao").first()
        chefe_nome = chefe.nome if chefe else None
        chefe_funcao = chefe.funcao if chefe else None

        # LOGOS
        logo_orgao      = _safe_logo_url(orgao, 'logo')
        logo_prefeitura = _safe_logo_url(prefeitura, 'logo')
        logo_secretaria = _safe_logo_url(secretaria, 'logo')

        # Datas
        total_dias = monthrange(ano, mes)[1]
        datas_do_mes = [date(ano, mes, dia) for dia in range(1, total_dias + 1)]
        primeiro_dia_mes = date(ano, mes, 1)
        ultimo_dia_mes = date(ano, mes, total_dias)

        feriados = Feriado.objects.filter(data__month=mes, data__year=ano)
        feriados_dict = {f.data: f.descricao for f in feriados}

        sabados_letivos = SabadoLetivo.objects.filter(data__month=mes, data__year=ano)
        sabados_letivos_dict = {sab.data: sab.descricao for sab in sabados_letivos}

        horarios = HorarioTrabalho.objects.filter(funcionario=funcionario)
        horario_manha = horarios.filter(turno__iexact='Manhã').first()
        horario_tarde = horarios.filter(turno__iexact='Tarde').first()

        # Recessos
        recessos_qs = RecessoFuncionario.objects.filter(
            funcionario=funcionario,
            data_inicio__lte=ultimo_dia_mes,
            data_fim__gte=primeiro_dia_mes,
        )
        recesso_por_dia = {}
        for r in recessos_qs:
            inicio = max(r.data_inicio, primeiro_dia_mes)
            fim    = min(r.data_fim, ultimo_dia_mes)
            d = inicio
            while d <= fim:
                recesso_por_dia[d] = (r.motivo or "Recesso")
                d += timedelta(days=1)

        # Dias
        dias = []
        for data_atual in datas_do_mes:
            dia_semana = dias_da_semana_pt[data_atual.weekday()]
            if data_atual in recesso_por_dia:
                dias.append({
                    'data': data_atual, 'dia_semana': dia_semana,
                    'manha': horario_manha, 'tarde': horario_tarde,
                    'recesso': True, 'descricao': recesso_por_dia[data_atual],
                    'feriado': False, 'sabado_letivo': False
                })
            elif data_atual.weekday() == 5 and data_atual in sabados_letivos_dict:
                dias.append({
                    'data': data_atual, 'dia_semana': dia_semana,
                    'manha': horario_manha, 'tarde': horario_tarde,
                    'feriado': False, 'sabado_letivo': True
                })
            elif data_atual in feriados_dict:
                dias.append({
                    'data': data_atual, 'dia_semana': dia_semana,
                    'manha': horario_manha, 'tarde': horario_tarde,
                    'feriado': True, 'descricao': feriados_dict[data_atual]
                })
            else:
                dias.append({
                    'data': data_atual, 'dia_semana': dia_semana,
                    'manha': horario_manha, 'tarde': horario_tarde,
                    'feriado': False
                })

        # Planejamento
        planejamento = []
        if (funcionario.funcao or "").lower() == "professor(a)" and funcionario.tem_planejamento:
            for d in datas_do_mes:
                if (d.weekday() == 0) and (d not in feriados_dict) and (d not in recesso_por_dia):
                    planejamento.append({
                        'data': d,
                        'dia_semana': dias_da_semana_pt[d.weekday()],
                        'horario': funcionario.horario_planejamento
                    })

        context = {
            'funcionario': funcionario,
            'dias': dias,
            'planejamento': planejamento,
            'mes': mes,
            'ano': ano,
            'nome_mes': meses_pt[mes],
            'ultimo_dia_mes': ultimo_dia_mes,

            # headers
            'header_prefeitura': getattr(prefeitura, "nome", "") if prefeitura else "",
            'header_secretaria': getattr(secretaria, "nome", "") if secretaria else "",
            'header_orgao': getattr(orgao, "nome", "") if orgao else "",
            'header_setor': getattr(setor, "nome", "") if setor else "",

            # compat
            'header_departamento': getattr(orgao, "nome", "") if orgao else "",
            'escola': None,

            'chefe_setor_nome': chefe_nome,
            'chefe_setor_funcao': chefe_funcao,

            'logo_prefeitura': logo_prefeitura,
            'logo_secretaria': logo_secretaria,
            'logo_orgao': logo_orgao,
        }

        html_folha = render_to_string('controle/folha_frequencia.html', context)

        FolhaFrequencia.objects.update_or_create(
            funcionario=funcionario, mes=mes, ano=ano,
            defaults={'html_armazenado': html_folha}
        )
        folhas_renderizadas.append(mark_safe(html_folha))

    return render(request, 'controle/folhas_em_lote.html', {'folhas': folhas_renderizadas})

# =====================================================================
# Selecionar funcionários para gerar
# =====================================================================

@login_required
def selecionar_funcionarios(request):
    # Meses p/ select
    meses = [
        (1, "Janeiro"), (2, "Fevereiro"), (3, "Março"), (4, "Abril"),
        (5, "Maio"), (6, "Junho"), (7, "Julho"), (8, "Agosto"),
        (9, "Setembro"), (10, "Outubro"), (11, "Novembro"), (12, "Dezembro")
    ]

    # Filtros (GET/POST)
    prefeitura_id = request.GET.get('prefeitura') or request.POST.get('prefeitura') or ""
    secretaria_id = request.GET.get('secretaria') or request.POST.get('secretaria') or ""
    orgao_id      = request.GET.get('orgao')      or request.POST.get('orgao')      or ""
    setor_id      = request.GET.get('setor')      or request.POST.get('setor')      or ""

    user = request.user
    is_admin = bool(user.is_superuser or user.is_staff)

    # ---------------------------
    # Listas de seleção no topo
    # ---------------------------
    if is_admin:
        prefeituras_qs = Prefeitura.objects.all()
        secretarias_qs = Secretaria.objects.select_related("prefeitura").all()
        # Órgãos: se usuário filtrou secretaria, mostra só os dela; senão, todos
        orgaos_qs = (
            Orgao.objects.select_related("secretaria", "secretaria__prefeitura")
            .filter(secretaria_id=secretaria_id) if secretaria_id else
            Orgao.objects.select_related("secretaria", "secretaria__prefeitura").all()
        )
    else:
        # Secretarias no escopo (UserScope + legado)
        secretarias_qs = (
            Secretaria.objects.select_related("prefeitura")
            .filter(
                Q(acessos_secretaria__user=user) | Q(scopes__user=user)
            )
            .distinct()
        )

        # Prefeituras no escopo (UserScope + legado + prefeituras que possuem secretarias no escopo)
        prefeituras_qs = (
            Prefeitura.objects
            .filter(
                Q(acessos_prefeitura__user=user) |
                Q(scopes__user=user) |
                Q(secretarias__in=secretarias_qs)
            )
            .distinct()
        )

        # Órgãos no escopo:
        # - Se houver secretaria selecionada, mostrar os dela
        # - Senão, todos os órgãos:
        #     • com AcessoOrgao / UserScope para o usuário
        #     • OU pertencentes a secretarias do escopo
        #     • OU pertencentes a prefeituras do escopo
        if secretaria_id:
            orgaos_qs = Orgao.objects.select_related("secretaria", "secretaria__prefeitura").filter(secretaria_id=secretaria_id)
        else:
            orgaos_qs = (
                Orgao.objects.select_related("secretaria", "secretaria__prefeitura")
                .filter(
                    Q(acessos_orgao__user=user) |
                    Q(scopes__user=user) |
                    Q(secretaria__in=secretarias_qs) |
                    Q(secretaria__prefeitura__in=prefeituras_qs)
                )
                .distinct()
            )

    # ---------------------------
    # Setores visíveis (escopo)
    # ---------------------------
    setores_qs = filter_setores_by_scope(
        Setor.objects.select_related(
            "prefeitura", "secretaria", "orgao", "orgao__secretaria", "orgao__secretaria__prefeitura"
        ),
        user,
    )

    # Filtros opcionais (cascata apenas como filtro, não como bloqueio)
    if orgao_id:
        setores_qs = setores_qs.filter(orgao_id=orgao_id)
    if secretaria_id:
        setores_qs = setores_qs.filter(
            Q(secretaria_id=secretaria_id) | Q(orgao__secretaria_id=secretaria_id)
        )
    if prefeitura_id:
        setores_qs = setores_qs.filter(
            Q(prefeitura_id=prefeitura_id) |
            Q(secretaria__prefeitura_id=prefeitura_id) |
            Q(orgao__secretaria__prefeitura_id=prefeitura_id)
        )

    setores_qs = setores_qs.order_by('nome')

    # ---------------------------
    # Setores GERENCIÁVEIS (para gerar)
    # ---------------------------
    if is_admin:
        setores_gerenciaveis = setores_qs  # admin pode tudo
    else:
        setores_gerenciaveis = setores_qs.filter(
            Q(scopes__user=user, scopes__nivel='GERENCIA') |
            Q(orgao__scopes__user=user, orgao__scopes__nivel='GERENCIA') |
            Q(secretaria__scopes__user=user, secretaria__scopes__nivel='GERENCIA') |
            Q(prefeitura__scopes__user=user, prefeitura__scopes__nivel='GERENCIA') |
            # legado (nível GERENCIA)
            Q(secretaria__acessos_secretaria__user=user, secretaria__acessos_secretaria__nivel='GERENCIA') |
            Q(prefeitura__acessos_prefeitura__user=user, prefeitura__acessos_prefeitura__nivel='GERENCIA') |
            Q(orgao__acessos_orgao__user=user, orgao__acessos_orgao__nivel='GERENCIA')
        ).distinct()

    # IDs agregados (úteis para destacar o que tem gerência)
    prefeituras_gerenciaveis_ids, secretarias_gerenciaveis_ids, orgaos_gerenciaveis_ids = set(), set(), set()
    for s in setores_gerenciaveis:
        if s.prefeitura_id:
            prefeituras_gerenciaveis_ids.add(s.prefeitura_id)
        sec_res = s.secretaria_resolvida
        if sec_res:
            secretarias_gerenciaveis_ids.add(sec_res.id)
            if sec_res.prefeitura_id:
                prefeituras_gerenciaveis_ids.add(sec_res.prefeitura_id)
        if s.orgao_id:
            orgaos_gerenciaveis_ids.add(s.orgao_id)

    # Setor atual + pode gerenciar?
    setor_atual = setores_qs.filter(id=setor_id).first() if setor_id else None
    pode_gerenciar_setor_selecionado = bool(
        is_admin or (setor_atual and setores_gerenciaveis.filter(id=setor_atual.id).exists())
    )

    # ---------------------------
    # POST → abrir primeira folha
    # ---------------------------
    if request.method == 'POST':
        if setor_id and not setores_qs.filter(id=setor_id).exists():
            return deny_and_redirect(request, "Sem permissão para esse setor.", to_name='controle:painel_controle')

        ids_funcionarios = request.POST.getlist('funcionarios')
        mes_str = request.POST.get('mes')
        ano_str = request.POST.get('ano')

        try:
            mes = int(mes_str) if mes_str else None
            ano = int(ano_str) if ano_str else None
        except ValueError:
            mes = ano = None

        if ids_funcionarios and mes and ano:
            f = get_object_or_404(Funcionario, id=ids_funcionarios[0])
            if not assert_can_access_funcionario(user, f):
                return deny_and_redirect(request, "Sem permissão para este servidor.", to_name='controle:painel_controle')
            return HttpResponseRedirect(reverse('controle:folha_frequencia', args=[f.id, mes, ano]))

    # ---------------------------
    # GET → carregar funcionários do setor selecionado (se houver)
    # ---------------------------
    funcionarios = []
    if request.method == 'GET' and setor_id:
        if not setores_qs.filter(id=setor_id).exists():
            return deny_and_redirect(request, "Sem permissão para esse setor.", to_name='controle:painel_controle')
        funcionarios = filter_funcionarios_by_scope(
            Funcionario.objects.filter(setor_id=setor_id),
            user
        ).order_by('nome')

    context = {
        # Combos (só aparecem no template se tiverem itens)
        'prefeituras': prefeituras_qs.order_by('nome'),
        'secretarias': secretarias_qs.order_by('nome'),
        'orgaos': orgaos_qs.order_by('nome'),

        # Setores
        'setores': setores_qs,
        'setores_gerenciaveis': setores_gerenciaveis,

        # Seleções
        'prefeitura_id': prefeitura_id,
        'secretaria_id': secretaria_id,
        'orgao_id': orgao_id,
        'setor_id': setor_id,

        # Auxiliares para destacar o que tem gerência
        'prefeituras_gerenciaveis_ids': list(prefeituras_gerenciaveis_ids),
        'secretarias_gerenciaveis_ids': list(secretarias_gerenciaveis_ids),
        'orgaos_gerenciaveis_ids': list(orgaos_gerenciaveis_ids),

        # Lista e meta
        'funcionarios': funcionarios,
        'meses': meses,
        'setor_atual': setor_atual,
        'pode_gerenciar_setor_selecionado': pode_gerenciar_setor_selecionado,
    }
    return render(request, 'controle/selecionar_funcionarios.html', context)

# =====================================================================
# Listagem / Visualização de folhas
# =====================================================================

@login_required
def listar_folhas(request):
    nome_funcionario = request.GET.get('nome', '').strip()

    qs = (filter_folhas_by_scope(
            FolhaFrequencia.objects.select_related('funcionario'),
            request.user
         )
         .annotate(nome_i=Lower('funcionario__nome')))

    if nome_funcionario:
        qs = qs.filter(funcionario__nome__icontains=nome_funcionario)

    folhas = qs.order_by('nome_i', 'ano', 'mes')
    return render(request, 'controle/listar_folhas.html', {'folhas': folhas})

@login_required
def visualizar_folha_salva(request, folha_id):
    folha = get_object_or_404(
        FolhaFrequencia.objects.select_related('funcionario', 'funcionario__setor'),
        id=folha_id
    )
    if not assert_can_access_funcionario(request.user, folha.funcionario):
        return deny_and_redirect(request, "Você não pode visualizar esta folha.")
    return HttpResponse(folha.html_armazenado)

# =====================================================================
# Funcionários (CRUD)
# =====================================================================

@login_required
def cadastrar_funcionario(request):
    if request.method == 'POST':
        form = FuncionarioForm(request.POST, request.FILES)
        if form.is_valid():
            setor = form.cleaned_data.get("setor")
            if setor:
                if not filter_setores_by_scope(Setor.objects.filter(id=setor.id), request.user).exists():
                    return deny_and_redirect(request, "Sem permissão para vincular a este setor.")
            form.save()
            messages.success(request, 'Funcionário cadastrado com sucesso!')
            return redirect('controle:listar_funcionarios')
        else:
            messages.error(request, 'Erro ao cadastrar. Verifique os campos.')
    else:
        form = FuncionarioForm()

    return render(request, 'controle/cadastrar_funcionario.html', {'form': form})

@login_required
def listar_funcionarios(request):
    funcionarios = filter_funcionarios_by_scope(
        Funcionario.objects.select_related('setor'),
        request.user
    ).order_by('nome')
    return render(request, 'controle/listar_funcionarios.html', {'funcionarios': funcionarios})

@login_required
def editar_funcionario(request, funcionario_id):
    funcionario = get_object_or_404(Funcionario, id=funcionario_id)

    if not assert_can_access_funcionario(request.user, funcionario):
        return deny_and_redirect(request, "Sem permissão para editar este servidor.")

    if request.method == 'POST':
        form = FuncionarioForm(request.POST, request.FILES, instance=funcionario)
        if form.is_valid():
            setor_novo = form.cleaned_data.get("setor")
            if setor_novo and not filter_setores_by_scope(Setor.objects.filter(id=setor_novo.id), request.user).exists():
                return deny_and_redirect(request, "Sem permissão para vincular a este setor.")
            form.save()
            return redirect('controle:listar_funcionarios')
        else:
            messages.error(request, 'Erro ao salvar. Verifique os campos.')
    else:
        form = FuncionarioForm(instance=funcionario)

    return render(request, 'controle/editar_funcionario.html', {'form': form, 'funcionario': funcionario})

@login_required
def excluir_funcionario(request, id):
    funcionario = get_object_or_404(Funcionario, id=id)
    if not assert_can_access_funcionario(request.user, funcionario):
        return deny_and_redirect(request, "Sem permissão para excluir este servidor.")
    funcionario.delete()
    return redirect('controle:listar_funcionarios')

# =====================================================================
# Horários
# =====================================================================

@login_required
def cadastrar_horario(request):
    if request.method == 'POST':
        form = HorarioTrabalhoForm(request.POST)
        if form.is_valid():
            funcionario = form.cleaned_data.get("funcionario")
            if funcionario and not assert_can_access_funcionario(request.user, funcionario):
                return deny_and_redirect(request, "Sem permissão para este servidor.")
            form.save()
            return redirect('cadastrar_horario')
    else:
        form = HorarioTrabalhoForm()

    return render(request, 'controle/cadastrar_horario.html', {'form': form})

@login_required
def editar_horario(request, funcionario_id):
    funcionario = get_object_or_404(Funcionario, id=funcionario_id)

    if not assert_can_access_funcionario(request.user, funcionario):
        return deny_and_redirect(request, "Sem permissão para alterar horários deste servidor.")

    try:
        horario = HorarioTrabalho.objects.get(funcionario=funcionario)
    except HorarioTrabalho.DoesNotExist:
        horario = None

    if request.method == 'POST':
        form = HorarioTrabalhoForm(request.POST, instance=horario)
        if form.is_valid():
            form.save()
            return redirect('controle:listar_funcionarios')
    else:
        form = HorarioTrabalhoForm(instance=horario)

    return render(request, 'controle/editar_horario.html', {'form': form, 'funcionario': funcionario})

# =====================================================================
# Feriados
# =====================================================================

@login_required
def cadastrar_feriado(request):
    feriados = Feriado.objects.order_by('data')

    if request.method == 'POST':
        form = FeriadoForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('controle:cadastrar_feriado')
    else:
        form = FeriadoForm()

    return render(request, 'controle/cadastrar_feriado.html', {'form': form, 'feriados': feriados})

@login_required
def editar_feriado(request, feriado_id):
    feriado = get_object_or_404(Feriado, id=feriado_id)

    if request.method == 'POST':
        form = FeriadoForm(request.POST, instance=feriado)
        if form.is_valid():
            form.save()
            return redirect('controle:cadastrar_feriado')
    else:
        form = FeriadoForm(instance=feriado)

    return render(request, 'controle/editar_feriado.html', {'form': form, 'feriado': feriado})

@login_required
def excluir_feriado(request, feriado_id):
    feriado = get_object_or_404(Feriado, id=feriado_id)
    feriado.delete()
    return redirect('controle:cadastrar_feriado')

# =====================================================================
# Painel
# =====================================================================

@login_required
def painel_controle(request):
    hoje_date = timezone.localdate()
    agora = timezone.now()

    funcionarios_count = filter_funcionarios_by_scope(Funcionario.objects.all(), request.user).count()
    horarios_count = filter_horarios_by_scope(HorarioTrabalho.objects.all(), request.user).count()
    feriados_count = Feriado.objects.count()

    cutoff = agora - timedelta(days=30)
    folhas_qs = filter_folhas_by_scope(FolhaFrequencia.objects.all(), request.user)
    if 'data_geracao' in {f.name for f in FolhaFrequencia._meta.get_fields()}:
        folhas_qs = folhas_qs.filter(data_geracao__gte=cutoff)
    folhas_30d_q = folhas_qs.count()

    aniversariantes_mes = filter_funcionarios_by_scope(
        Funcionario.objects.filter(data_nascimento__month=hoje_date.month).order_by(Lower('nome')),
        request.user
    )
    aniversariantes_dia = filter_funcionarios_by_scope(
        Funcionario.objects.filter(
            data_nascimento__month=hoje_date.month,
            data_nascimento__day=hoje_date.day
        ).order_by(Lower('nome')),
        request.user
    )

    context = {
        'funcionarios_count': funcionarios_count,
        'horarios_count': horarios_count,
        'feriados_count': feriados_count,
        'folhas_30d_q': folhas_30d_q,
        'aniversariantes_mes': aniversariantes_mes,
        'aniversariantes_dia': aniversariantes_dia,
    }
    return render(request, 'controle/painel_controle.html', context)

# =====================================================================
# Importações
# =====================================================================

@login_required
def importar_funcionarios(request):
    if request.method == 'POST' and request.FILES.get('excel_file'):
        excel_file = request.FILES['excel_file']

        if not excel_file.name.endswith(('.xlsx', '.xls')):
            messages.error(request, "Por favor, envie um arquivo Excel (.xlsx ou .xls).")
            return render(request, 'controle/importar_funcionarios.html')

        try:
            df = pd.read_excel(excel_file)

            if 'Data de Admissão' in df.columns:
                df['Data de Admissão'] = pd.to_datetime(df['Data de Admissão'], dayfirst=True, errors='coerce')
            if 'Data de Nascimento' in df.columns:
                df['Data de Nascimento'] = pd.to_datetime(df['Data de Nascimento'], dayfirst=True, errors='coerce')

            total_importados = 0

            for _, row in df.iterrows():
                setor_nome = str(row.get('Setor')).strip()
                setor_qs = Setor.objects.filter(nome=setor_nome)
                setor = filter_setores_by_scope(setor_qs, request.user).first()
                if not setor:
                    continue  # ignora se não existir/no escopo

                funcionario_data = {
                    'nome': str(row.get('Nome', '')).strip(),
                    'cargo': str(row.get('Cargo', '')).strip(),
                    'funcao': str(row.get('Função', '')).strip(),
                    'data_admissao': row.get('Data de Admissão'),
                    'setor': setor,
                    'tem_planejamento': str(row.get('Tem Planejamento', '')).strip().lower() in ['sim', 'true', '1'],
                    'horario_planejamento': str(row.get('Horário Planejamento', '')).strip() or None,
                    'sabado_letivo': str(row.get('Sábado Letivo', '')).strip().lower() in ['sim', 'true', '1'],
                    'data_nascimento': row.get('Data de Nascimento')
                }

                matricula = str(row.get('Matrícula', '')).strip()
                if matricula:
                    Funcionario.objects.update_or_create(
                        matricula=matricula,
                        defaults=funcionario_data
                    )
                    total_importados += 1

            messages.success(request, f'{total_importados} funcionários foram importados com sucesso.')

        except Exception as e:
            messages.error(request, f'Ocorreu um erro ao importar o arquivo: {e}')

    return render(request, 'controle/importar_funcionarios.html')

@login_required
def importar_horarios_trabalho(request):
    if request.method == 'POST' and request.FILES.get('arquivo_horarios'):
        arquivo = request.FILES['arquivo_horarios']

        if not arquivo.name.endswith(('.xlsx', '.xls', '.csv')):
            messages.error(request, "Envie um arquivo .xlsx, .xls ou .csv válido.")
            return render(request, 'controle/importar_horarios.html')

        try:
            if arquivo.name.endswith('.csv'):
                df = pd.read_csv(arquivo)
            else:
                df = pd.read_excel(arquivo)

            total_importados = 0

            for _, row in df.iterrows():
                nome = str(row.get('nome')).strip()
                turno = str(row.get('turno')).strip().capitalize()
                funcionario = filter_funcionarios_by_scope(
                    Funcionario.objects.filter(nome__iexact=nome),
                    request.user
                ).first()

                if funcionario:
                    horario_inicio = datetime.strptime(str(row.get('horario_inicio')), '%H:%M:%S').time()
                    horario_fim = datetime.strptime(str(row.get('horario_fim')), '%H:%M:%S').time()

                    HorarioTrabalho.objects.update_or_create(
                        funcionario=funcionario,
                        turno=turno,
                        defaults={'horario_inicio': horario_inicio, 'horario_fim': horario_fim}
                    )
                    total_importados += 1
                else:
                    messages.warning(request, f'Funcionário fora do escopo ou não encontrado: {nome}')

            messages.success(request, f'{total_importados} horários de trabalho importados com sucesso.')

        except Exception as e:
            messages.error(request, f'Erro ao importar horários: {e}')

    return render(request, 'controle/importar_horarios.html')

# =====================================================================
# Capa do livro de ponto
# =====================================================================

@login_required
def capas_livro_ponto(request):
    setor_nome = request.GET.get('setor')
    ano = int(request.GET.get('ano'))
    mes = int(request.GET.get('mes'))

    # Locale PT-BR
    try:
        locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8')
    except locale.Error:
        try:
            locale.setlocale(locale.LC_TIME, 'pt_BR')
        except:
            pass

    nome_mes = date(ano, mes, 1).strftime('%B').capitalize()

    # Checa escopo do setor
    prefeitura_ctx = None
    if setor_nome:
        setor_qs = filter_setores_by_scope(Setor.objects.filter(nome=setor_nome), request.user)
        if not setor_qs.exists():
            return deny_and_redirect(request, "Sem permissão para este setor.")
        setor_obj = setor_qs.first()
        prefeitura_ctx = setor_obj.prefeitura_resolvida
    if not prefeitura_ctx:
        prefeitura_ctx = Prefeitura.objects.first()

    paginas = filter_folhas_by_scope(
        FolhaFrequencia.objects.filter(
            funcionario__setor__nome=setor_nome,
            mes=mes, ano=ano
        ),
        request.user
    ).count()

    primeiro_dia = date(ano, mes, 1)
    ultimo_dia = date(ano, mes, calendar.monthrange(ano, mes)[1])

    context = {
        'setor': (setor_nome or '').upper(),
        'ano': ano,
        'mes': mes,
        'nome_mes': nome_mes.upper(),
        'paginas': paginas,
        'data_abertura': primeiro_dia.strftime('%d de %B de %Y'),
        'data_encerramento': ultimo_dia.strftime('%d de %B de %Y'),
        'cidade': getattr(prefeitura_ctx, 'cidade', '') or '',
        'uf': getattr(prefeitura_ctx, 'uf', '') or '',
        # compat
        'escola': None,
    }
    return render(request, 'controle/capas_livro_ponto.html', context)

@login_required
def selecionar_setor_capa(request):
    setores = filter_setores_by_scope(Setor.objects.all(), request.user).order_by('nome')
    hoje = date.today()
    context = {'setores': setores, 'ano': hoje.year, 'mes': hoje.month}
    return render(request, 'controle/selecionar_capa.html', context)

# =====================================================================
# Ficha de funcionário
# =====================================================================

@login_required
def ficha_funcionario(request, funcionario_id):
    funcionario = get_object_or_404(Funcionario, id=funcionario_id)
    if not assert_can_access_funcionario(request.user, funcionario):
        return deny_and_redirect(request, "Sem permissão para visualizar esta ficha.")
    dias_semana = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
    orgao = getattr(funcionario.setor, "orgao", None) if funcionario.setor_id else None
    return render(request, 'controle/ficha_funcionario.html', {
        'funcionario': funcionario,
        'dias_semana': dias_semana,
        'orgao': orgao,
        'escola': None,  # compat
    })

# =====================================================================
# Relatórios
# =====================================================================

@login_required
def relatorio_personalizado_funcionarios(request):
    funcionarios = filter_funcionarios_by_scope(Funcionario.objects.all(), request.user)

    # Filtros
    filtro_serie   = request.POST.getlist('filtro_serie')
    filtro_turma   = request.POST.getlist('filtro_turma')
    filtro_turno   = request.POST.getlist('filtro_turno')
    filtro_setor   = request.POST.getlist('filtro_setor')
    filtro_vinculo = request.POST.getlist('filtro_vinculo')

    if filtro_serie:
        funcionarios = funcionarios.filter(serie__in=filtro_serie)
    if filtro_turma:
        funcionarios = funcionarios.filter(turma__in=filtro_turma)
    if filtro_turno:
        funcionarios = funcionarios.filter(turno__in=filtro_turno)
    if filtro_setor:
        funcionarios = funcionarios.filter(setor__nome__in=filtro_setor)
    if filtro_vinculo:
        funcionarios = funcionarios.filter(tipo_vinculo__in=filtro_vinculo)

    funcionarios = funcionarios.order_by('nome')

    campos_disponiveis = [
        ('nome', 'Nome'),
        ('matricula', 'Matrícula'),
        ('cargo', 'Cargo'),
        ('funcao', 'Função'),
        ('setor', 'Setor'),
        ('data_admissao', 'Data de Admissão'),
        ('data_nascimento', 'Data de Nascimento'),
        ('cpf', 'CPF'),
        ('rg', 'RG'),
        ('pis', 'PIS'),
        ('titulo_eleitor', 'Título de Eleitor'),
        ('ctps_numero', 'CTPS Nº'),
        ('ctps_serie', 'CTPS Série'),
        ('telefone', 'Telefone'),
        ('email', 'Email'),
        ('endereco', 'Endereço'),
        ('numero', 'Número'),
        ('bairro', 'Bairro'),
        ('cidade', 'Cidade'),
        ('uf', 'UF'),
        ('cep', 'CEP'),
        ('estado_civil', 'Estado Civil'),
        ('escolaridade', 'Escolaridade'),
        ('tem_planejamento', 'Planejamento'),
        ('horario_planejamento', 'Horário Planejamento'),
        ('sabado_letivo', 'Sábado Letivo'),
        ('turma', 'Turma'),
        ('turno', 'Turno'),
        ('serie', 'Série'),
        ('tipo_vinculo', 'Tipo de Vínculo'),
        ('fonte_pagadora', 'Fonte Pagadora'),
    ]

    campos_selecionados = request.POST.getlist('campos') if request.method == 'POST' else []

    base_f = filter_funcionarios_by_scope(Funcionario.objects.all(), request.user)
    series  = base_f.exclude(serie__isnull=True).exclude(serie__exact='').values_list('serie', flat=True).distinct()
    turmas  = base_f.exclude(turma__isnull=True).exclude(turma__exact='').values_list('turma', flat=True).distinct()
    turnos  = base_f.exclude(turno__isnull=True).exclude(turno__exact='').values_list('turno', flat=True).distinct()
    setores = filter_setores_by_scope(Setor.objects.all(), request.user)
    vinculos = base_f.exclude(tipo_vinculo__isnull=True).exclude(tipo_vinculo__exact='').values_list('tipo_vinculo', flat=True).distinct()

    return render(request, 'controle/relatorio_personalizado_funcionarios.html', {
        'funcionarios': funcionarios,
        'campos_disponiveis': campos_disponiveis,
        'campos_selecionados': campos_selecionados,
        'series': series,
        'turmas': turmas,
        'turnos': turnos,
        'setores': setores,
        'vinculos': vinculos,
        'filtro_serie': filtro_serie,
        'filtro_turma': filtro_turma,
        'filtro_turno': filtro_turno,
        'filtro_setor': filtro_setor,
        'filtro_vinculo': filtro_vinculo,
        # compat
        'escola': None,
    })

@login_required
def relatorio_professores(request):
    base = filter_funcionarios_by_scope(Funcionario.objects.all(), request.user)

    series = sorted([s for s in set(base.values_list('serie', flat=True)) if s is not None])
    turmas = sorted([t for t in set(base.values_list('turma', flat=True)) if t is not None])
    turnos = sorted([t for t in set(base.values_list('turno', flat=True)) if t is not None])

    setores = filter_setores_by_scope(Setor.objects.all(), request.user)

    filtro_serie = request.POST.getlist('filtro_serie')
    filtro_turma = request.POST.getlist('filtro_turma')
    filtro_turno = request.POST.getlist('filtro_turno')
    filtro_setor = request.POST.getlist('filtro_setor')
    campos_selecionados = request.POST.getlist('campos')

    funcionarios = base.filter(funcao__iexact="PROFESSOR(A)")

    if filtro_serie:
        funcionarios = funcionarios.filter(serie__in=filtro_serie)
    if filtro_turma:
        funcionarios = funcionarios.filter(turma__in=filtro_turma)
    if filtro_turno:
        funcionarios = funcionarios.filter(turno__in=filtro_turno)
    if filtro_setor:
        funcionarios = funcionarios.filter(setor__nome__in=filtro_setor)

    funcionarios = sorted(funcionarios, key=lambda f: (str(f.serie or ""), str(f.turma or "")))

    campos_disponiveis = [
        ('nome', 'Nome'),
        ('matricula', 'Matrícula'),
        ('serie', 'Série'),
        ('turma', 'Turma'),
        ('turno', 'Turno'),
        ('setor', 'Setor'),
        ('telefone', 'Telefone'),
        ('email', 'Email'),
        ('vinculo', 'Tipo de Vínculo'),
    ]

    contexto = {
        'series': series,
        'turmas': turmas,
        'turnos': turnos,
        'setores': setores,
        'filtro_serie': filtro_serie,
        'filtro_turma': filtro_turma,
        'filtro_turno': filtro_turno,
        'filtro_setor': filtro_setor,
        'campos_disponiveis': campos_disponiveis,
        'campos_selecionados': campos_selecionados,
        'funcionarios': funcionarios,
        'escola': None,  # compat
    }
    return render(request, 'controle/relatorio_professores.html', contexto)

def relatorios_funcionarios(request):
    return render(request, 'controle/relatorios_funcionarios.html')

# =====================================================================
# Folhas individuais (multi-meses)
# =====================================================================

@login_required
def gerar_folhas_multimes_funcionario(request):
    folhas_geradas = []
    anos = list(range(2025, 2031))

    if request.method == 'POST':
        form = GerarFolhasIndividuaisForm(request.POST)
        if form.is_valid():
            funcionario = form.cleaned_data['funcionario']
            ano = form.cleaned_data['ano']
            meses = list(map(int, form.cleaned_data['meses']))

            if not assert_can_access_funcionario(request.user, funcionario):
                return deny_and_redirect(request, "Sem permissão para esse servidor.")

            for mes in meses:
                response = gerar_folha_frequencia(request, funcionario.id, mes, ano)
                folhas_geradas.append(response.content.decode())
    else:
        form = GerarFolhasIndividuaisForm()

    return render(request, 'controle/gerar_folhas_individuais.html', {
        'form': form,
        'folhas_geradas': folhas_geradas,
        'anos': anos,
    })

@login_required
def excluir_folha(request, folha_id):
    folha = get_object_or_404(
        FolhaFrequencia.objects.select_related('funcionario', 'funcionario__setor'),
        id=folha_id
    )
    if not assert_can_access_funcionario(request.user, folha.funcionario):
        return deny_and_redirect(request, "Sem permissão para excluir esta folha.")
    folha.delete()
    messages.success(request, "Folha de frequência excluída com sucesso.")
    return redirect('controle:listar_folhas')

# =====================================================================
# Recessos em massa e CRUD
# =====================================================================

@login_required
@require_http_methods(["GET", "POST"])
def recesso_bulk_create(request):
    setor_id = request.GET.get('setor') or request.POST.get('setor')
    form = RecessoBulkForm(request.POST or None, setor_id=setor_id)

    if request.method == 'POST' and form.is_valid():
        setor = form.cleaned_data['setor']
        funcionarios = form.cleaned_data['funcionarios']
        di = form.cleaned_data['data_inicio']
        df = form.cleaned_data['data_fim']
        motivo = form.cleaned_data.get('motivo') or "Recesso"

        criados, pulados = 0, 0
        with transaction.atomic():
            for func in funcionarios:
                existe = RecessoFuncionario.objects.filter(
                    funcionario=func,
                    data_inicio__lte=df,
                    data_fim__gte=di
                ).exists()
                if existe:
                    pulados += 1
                    continue
                RecessoFuncionario.objects.create(
                    setor=setor, funcionario=func, data_inicio=di, data_fim=df, motivo=motivo
                )
                criados += 1

        msg = f"{criados} recesso(s) criado(s)."
        if pulados:
            msg += f" {pulados} período(s) já existiam (sobrepostos) e foram ignorados."
        messages.success(request, msg)
        return redirect('controle:recesso_bulk_create')

    context = {"form": form}
    return render(request, 'controle/recessos_bulk_form.html', context)

@login_required
@require_GET
def api_funcionarios_por_setor(request):
    setor_id = request.GET.get('setor')
    qs = Funcionario.objects.none()
    if setor_id:
        qs = Funcionario.objects.filter(setor_id=setor_id).order_by('nome').values('id', 'nome')
    return JsonResponse(list(qs), safe=False)

def _tem_recesso_no_dia(funcionario, d):
    return RecessoFuncionario.objects.filter(
        funcionario=funcionario,
        data_inicio__lte=d,
        data_fim__gte=d
    ).exists()

@login_required
def gerar_folha_funcionario(request, funcionario_id, mes, ano):
    funcionario = get_object_or_404(Funcionario, pk=funcionario_id)
    # ... sua montagem de `dias` ...
    dias = []  # placeholder se você reaproveitar; preencha conforme sua lógica

    for dia in dias:
        d = dia.data  # datetime.date
        if _tem_recesso_no_dia(funcionario, d):
            dia.descricao = "Recesso"

    context = {'funcionario': funcionario, 'dias': dias}
    return render(request, 'controle/folha_frequencia.html', context)

@login_required
def recessos_list(request):
    """
    Lista recessos dos funcionários DENTRO do escopo do usuário.
    Filtros: nome (?nome=), setor (?setor=ID), mês (?mes=), ano (?ano=)
    """
    nome = (request.GET.get("nome") or "").strip()
    setor_id = request.GET.get("setor")
    mes = request.GET.get("mes")
    ano = request.GET.get("ano")

    func_qs_scope = filter_funcionarios_by_scope(
        Funcionario.objects.select_related("setor"), request.user
    )

    qs = (RecessoFuncionario.objects
          .select_related("funcionario", "setor")
          .filter(funcionario__in=func_qs_scope))

    if nome:
        qs = qs.filter(funcionario__nome__icontains=nome)

    if setor_id:
        qs = qs.filter(setor_id=setor_id)

    if mes and ano:
        try:
            mes_i, ano_i = int(mes), int(ano)
            qs = qs.filter(
                data_inicio__year__lte=ano_i,
                data_fim__year__gte=ano_i
            ).filter(
                Q(data_inicio__month__lte=mes_i) | Q(data_inicio__year__lt=ano_i),
                Q(data_fim__month__gte=mes_i) | Q(data_fim__year__gt=ano_i),
            )
        except ValueError:
            pass

    qs = qs.order_by("-data_inicio", "funcionario__nome")

    paginator = Paginator(qs, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "recessos": page_obj.object_list,
        "setores": filter_setores_by_scope(Setor.objects.all(), request.user).order_by("nome"),
        "nome": nome,
        "setor_id": (int(setor_id) if setor_id else ""),
        "mes": (int(mes) if mes else ""),
        "ano": (int(ano) if ano else ""),
    }
    return render(request, "controle/recessos_list.html", context)

@login_required
def recesso_edit(request, recesso_id):
    recesso = get_object_or_404(RecessoFuncionario.objects.select_related("funcionario", "setor"),
                                pk=recesso_id)

    if not assert_can_access_funcionario(request.user, recesso.funcionario):
        return deny_and_redirect(request, "Sem permissão para editar este recesso.")

    if request.method == "POST":
        form = RecessoFuncionarioForm(request.POST, instance=recesso, user=request.user)
        if form.is_valid():
            obj = form.save(commit=False)
            if not assert_can_access_funcionario(request.user, obj.funcionario):
                return deny_and_redirect(request, "Sem permissão para vincular a este servidor.")
            obj.save()
            messages.success(request, "Recesso atualizado com sucesso.")
            return redirect("controle:recessos_list")
    else:
        form = RecessoFuncionarioForm(instance=recesso, user=request.user)

    return render(request, "controle/recesso_edit.html", {"form": form, "recesso": recesso})

@login_required
def recesso_delete(request, recesso_id):
    recesso = get_object_or_404(RecessoFuncionario.objects.select_related("funcionario"),
                                pk=recesso_id)
    if not assert_can_access_funcionario(request.user, recesso.funcionario):
        return deny_and_redirect(request, "Sem permissão para excluir este recesso.")

    recesso.delete()
    messages.success(request, "Recesso excluído com sucesso.")
    return redirect("controle:recessos_list")

# ---------------------------------------------------------------------
# Logout com namespace (compat)
# ---------------------------------------------------------------------
class PainelLogoutView(LogoutView):
    next_page = reverse_lazy("controle:login")
    http_method_names = ["get", "post", "options", "head"]
    def get(self, request, *args, **kwargs):
        return self.post(request, *args, **kwargs)
