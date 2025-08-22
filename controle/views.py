# controle/views.py
import calendar
import locale
from calendar import monthrange
from datetime import date, datetime, timedelta
from django.db.models import Prefetch
import pandas as pd
import unicodedata
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
from urllib.parse import urlencode

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
    RecessoFuncionario, NivelAcesso,
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


def _only_superuser(u):  # se já existir em outro lugar, pode remover esta função
    return bool(u and u.is_superuser)

@login_required
@user_passes_test(_only_superuser)
def acessos_conceder(request):
    """
    Concede/acerta um acesso para um usuário em EXATAMENTE um alvo:
    Prefeitura OU Secretaria OU Órgão OU Setor.
    Salva nas tabelas AcessoPrefeitura/Secretaria/Orgao/Setor.
    """
    User = get_user_model()

    if request.method == "POST":
        user_id = request.POST.get("user")
        nivel = (request.POST.get("nivel") or "").upper().strip()

        pref_id = (request.POST.get("prefeitura") or "").strip()
        sec_id  = (request.POST.get("secretaria") or "").strip()
        org_id  = (request.POST.get("orgao") or "").strip()
        set_id  = (request.POST.get("setor") or "").strip()

        # Validações básicas
        if not user_id:
            messages.error(request, "Selecione um usuário.")
            return redirect("controle:acessos_conceder")

        try:
            alvo_user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            messages.error(request, "Usuário inválido.")
            return redirect("controle:acessos_conceder")

        if nivel not in dict(NivelAcesso.choices):
            messages.error(request, "Selecione um nível de acesso válido (Leitura ou Gerenciar).")
            return redirect("controle:acessos_conceder")

        escolhas = [
            ("prefeitura", pref_id),
            ("secretaria", sec_id),
            ("orgao",      org_id),
            ("setor",      set_id),
        ]
        preenchidas = [(k, v) for k, v in escolhas if v]
        if len(preenchidas) != 1:
            messages.error(
                request,
                "Selecione exatamente um alvo (Prefeitura OU Secretaria OU Órgão OU Setor)."
            )
            return redirect("controle:acessos_conceder")

        alvo, alvo_pk = preenchidas[0]

        try:
            with transaction.atomic():
                created = False
                updated = False

                if alvo == "prefeitura":
                    pref = get_object_or_404(Prefeitura, pk=alvo_pk)
                    obj, was_created = AcessoPrefeitura.objects.update_or_create(
                        user=alvo_user, prefeitura=pref,
                        defaults={"nivel": nivel}
                    )
                    created = was_created
                    updated = (not was_created)

                elif alvo == "secretaria":
                    sec = get_object_or_404(Secretaria, pk=alvo_pk)
                    obj, was_created = AcessoSecretaria.objects.update_or_create(
                        user=alvo_user, secretaria=sec,
                        defaults={"nivel": nivel}
                    )
                    created = was_created
                    updated = (not was_created)

                elif alvo == "orgao":
                    org = get_object_or_404(Orgao, pk=alvo_pk)
                    obj, was_created = AcessoOrgao.objects.update_or_create(
                        user=alvo_user, orgao=org,
                        defaults={"nivel": nivel}
                    )
                    created = was_created
                    updated = (not was_created)

                elif alvo == "setor":
                    st = get_object_or_404(Setor, pk=alvo_pk)
                    obj, was_created = AcessoSetor.objects.update_or_create(
                        user=alvo_user, setor=st,
                        defaults={"nivel": nivel}
                    )
                    created = was_created
                    updated = (not was_created)

            if created:
                messages.success(request, "Acesso criado com sucesso.")
            elif updated:
                messages.success(request, "Acesso já existente — nível atualizado com sucesso.")
            else:
                messages.info(request, "Acesso já existia e permaneceu inalterado.")

        except Exception as e:
            messages.error(request, f"Erro ao salvar o acesso: {e}")

        return redirect("controle:acessos_conceder")

    # GET — popula os selects usados no template
    contexto = {
        "usuarios": User.objects.order_by("username", "first_name", "last_name"),
        "niveis": NivelAcesso.choices,
        "prefeituras": Prefeitura.objects.order_by("nome"),
        "secretarias": Secretaria.objects.select_related("prefeitura").order_by("prefeitura__nome", "nome"),
        "orgaos": Orgao.objects.select_related("secretaria", "secretaria__prefeitura")
                               .order_by("secretaria__prefeitura__nome", "secretaria__nome", "nome"),
        "setores": Setor.objects.select_related("prefeitura", "secretaria", "orgao",
                                                "orgao__secretaria", "orgao__secretaria__prefeitura").order_by("nome"),
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

MESES_PT = [
    "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
]

def _norm(s: str) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.strip().lower()


@login_required
def painel_controle(request):
    hoje_date = timezone.localdate()
    agora = timezone.now()

    # =======================
    # KPIs
    # =======================
    funcionarios_count = filter_funcionarios_by_scope(
        Funcionario.objects.all(), request.user
    ).count()

    horarios_count = filter_horarios_by_scope(
        HorarioTrabalho.objects.all(), request.user
    ).count()

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

    # =======================
    # Calendário do mês atual
    # =======================
    ano = hoje_date.year
    mes = hoje_date.month
    # domingo como primeiro dia (0=segunda ... 6=domingo)
    cal = calendar.Calendar(firstweekday=6)
    cal_weeks = cal.monthdatescalendar(ano, mes)

    # limites do mês
    first_day = date(ano, mes, 1)
    last_day = date(ano, mes, calendar.monthrange(ano, mes)[1])

    # dicionário data -> lista de eventos (cada evento é dict {'titulo','categoria'})
    cal_events_by_day = {}
    for week in cal_weeks:
        for d in week:
            cal_events_by_day.setdefault(d, [])

    def _add_evt(d, titulo, categoria):
        cal_events_by_day.setdefault(d, []).append({
            "titulo": titulo,
            "categoria": (categoria or "OUTRO").upper()
        })

    # 1) Eventos do Calendário Escolar (se o modelo existir)
    try:
        from .models import CalendarioEvento  # caso ainda não tenha criado, apenas ignora
        eventos_qs = CalendarioEvento.objects.filter(
            data_inicio__lte=last_day,
            data_fim__gte=first_day
        ).only("titulo", "categoria", "data_inicio", "data_fim")
    except Exception:
        eventos_qs = []

    for e in eventos_qs:
        d = max(e.data_inicio, first_day)
        fim = min(e.data_fim, last_day)
        while d <= fim:
            _add_evt(d, e.titulo, e.categoria)
            d += timedelta(days=1)

    # 2) Feriados
    for f in Feriado.objects.filter(data__range=(first_day, last_day)):
        _add_evt(f.data, f"FERIADO — {f.descricao}", "FERIADO")

    # 3) Sábados letivos
    for s in SabadoLetivo.objects.filter(data__range=(first_day, last_day)):
        titulo = "SÁBADO LETIVO" + (f" — {s.descricao}" if getattr(s, "descricao", None) else "")
        _add_evt(s.data, titulo, "AULA")

    context = {
        'funcionarios_count': funcionarios_count,
        'horarios_count': horarios_count,
        'feriados_count': feriados_count,
        'folhas_30d_q': folhas_30d_q,
        'aniversariantes_mes': aniversariantes_mes,
        'aniversariantes_dia': aniversariantes_dia,

        # calendário (para o card no painel)
        'cal_weeks': cal_weeks,
        'cal_events_by_day': cal_events_by_day,
        'cal_mes_nome': MESES_PT[mes],
        'cal_mes_num': mes,
        'cal_ano': ano,
    }
    return render(request, 'controle/painel_controle.html', context)

@login_required
def importar_funcionarios(request):
    if request.method == 'POST' and request.FILES.get('excel_file'):
        arquivo = request.FILES['excel_file']
        nome_arquivo = arquivo.name.lower()

        # Aceita xlsx, xls, csv
        if not nome_arquivo.endswith(('.xlsx', '.xls', '.csv')):
            messages.error(request, "Envie um arquivo .xlsx, .xls ou .csv.")
            return render(request, 'controle/importar_funcionarios.html')

        # Ler arquivo com fallbacks
        try:
            if nome_arquivo.endswith('.csv'):
                df = pd.read_csv(arquivo)
            elif nome_arquivo.endswith('.xlsx'):
                try:
                    import openpyxl  # noqa
                except ImportError:
                    messages.error(request, "Falta 'openpyxl' para .xlsx. Instale: pip install openpyxl (ou envie CSV).")
                    return render(request, 'controle/importar_funcionarios.html')
                df = pd.read_excel(arquivo, engine='openpyxl')
            else:  # .xls
                try:
                    import xlrd  # noqa
                except ImportError:
                    messages.error(request, "Falta 'xlrd' para .xls. Instale: pip install xlrd (ou converta para .xlsx/CSV).")
                    return render(request, 'controle/importar_funcionarios.html')
                df = pd.read_excel(arquivo, engine='xlrd')
        except Exception as e:
            messages.error(request, f"Ocorreu um erro ao abrir o arquivo: {e}")
            return render(request, 'controle/importar_funcionarios.html')

        # Nomes de colunas limpos
        df.columns = [str(c).strip() for c in df.columns]

        # Colunas EXATAS requeridas (batem com o modelo/cabeçalho)
        obrigatorias = [
            'Nome', 'Matrícula', 'Setor', 'Cargo', 'Função',
            'Data de Admissão', 'Série', 'Turma', 'Turno (cadastro)', 'Vínculo'
        ]
        faltantes = [c for c in obrigatorias if c not in df.columns]
        if faltantes:
            messages.error(request, "Colunas obrigatórias ausentes: " + ", ".join(faltantes))
            return render(request, 'controle/importar_funcionarios.html')

        # Conversão de data (campo do modelo é obrigatório)
        df['Data de Admissão'] = pd.to_datetime(df['Data de Admissão'], dayfirst=True, errors='coerce')

        # Choices do modelo (canônicos)
        TURNO_MAP = {
            'matutino': 'Matutino',
            'vespertino': 'Vespertino',
            'noturno': 'Noturno',
            'integral': 'Integral',
        }
        VINC_MAP = {
            'efetivo': 'Efetivo',
            'contratado': 'Contratado',
        }
        SERIES_OK = {
            '1º ANO','2º ANO','3º ANO','4º ANO','5º ANO','6º ANO','7º ANO','8º ANO','9º ANO'
        }
        TURMAS_OK = {'A','B','C','D','E','F','G'}

        def cell(row, col):
            val = row.get(col)
            if pd.isna(val):
                return ""
            return str(val).strip()

        total_ok = 0
        ign_sem_matricula = 0
        ign_sem_setor = 0
        ign_admissao_invalida = 0
        ajustados_turno = 0
        ajustados_vinculo = 0
        inval_series = 0
        inval_turmas = 0

        with transaction.atomic():
            for _, row in df.iterrows():
                nome = cell(row, 'Nome')
                matricula = cell(row, 'Matrícula')
                setor_nome = cell(row, 'Setor')
                cargo = cell(row, 'Cargo')
                funcao = cell(row, 'Função')
                serie_in = cell(row, 'Série')
                turma_in = cell(row, 'Turma')
                turno_in = cell(row, 'Turno (cadastro)')
                vinc_in = cell(row, 'Vínculo')
                adm = row.get('Data de Admissão')

                if not matricula:
                    ign_sem_matricula += 1
                    continue

                if not setor_nome:
                    ign_sem_setor += 1
                    continue

                if pd.isna(adm):
                    ign_admissao_invalida += 1
                    continue

                # Resolver Setor pelo nome dentro do escopo do usuário
                setor_qs = Setor.objects.filter(nome__iexact=setor_nome)
                setor_qs = filter_setores_by_scope(setor_qs, request.user)
                setor = setor_qs.first()
                if not setor:
                    ign_sem_setor += 1
                    continue

                # Normalizações/validações para bater com os choices do modelo
                turno = TURNO_MAP.get(_norm(turno_in)) if turno_in else None
                if turno_in and not turno:
                    ajustados_turno += 1  # valor inválido → None

                vinculo = VINC_MAP.get(_norm(vinc_in)) if vinc_in else None
                if vinc_in and not vinculo:
                    ajustados_vinculo += 1  # valor inválido → None

                serie = serie_in if serie_in in SERIES_OK else None
                if serie_in and serie is None:
                    inval_series += 1

                turma = turma_in.upper() if turma_in else None
                turma = turma if (turma and turma in TURMAS_OK) else None
                if turma_in and turma is None:
                    inval_turmas += 1

                # Monta dict exatamente como o modelo espera
                funcionario_data = {
                    'nome': nome,
                    'cargo': cargo,
                    'funcao': funcao,
                    'data_admissao': pd.to_datetime(adm).date(),
                    'setor': setor,
                    'serie': serie,
                    'turma': turma,
                    'turno': turno,
                    'tipo_vinculo': vinculo,
                }

                Funcionario.objects.update_or_create(
                    matricula=matricula,
                    defaults=funcionario_data
                )
                total_ok += 1

        # Mensagens finais
        base_msg = f'{total_ok} funcionário(s) importado(s)/atualizado(s).'
        avisos = []
        if ign_sem_matricula: avisos.append(f'{ign_sem_matricula} sem Matrícula')
        if ign_sem_setor: avisos.append(f'{ign_sem_setor} com Setor inexistente/fora de escopo')
        if ign_admissao_invalida: avisos.append(f'{ign_admissao_invalida} com Data de Admissão inválida')
        if ajustados_turno: avisos.append(f'{ajustados_turno} com Turno inválido (definido como vazio)')
        if ajustados_vinculo: avisos.append(f'{ajustados_vinculo} com Vínculo inválido (definido como vazio)')
        if inval_series: avisos.append(f'{inval_series} com Série inválida (definida como vazia)')
        if inval_turmas: avisos.append(f'{inval_turmas} com Turma inválida (definida como vazia)')

        if avisos:
            messages.warning(request, base_msg + " Avisos: " + "; ".join(avisos))
        else:
            messages.success(request, base_msg)

    return render(request, 'controle/importar_funcionarios.html')

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render
from django.db import transaction
from datetime import time
import pandas as pd
import unicodedata
import re

from .models import Funcionario, HorarioTrabalho, Setor, filter_funcionarios_by_scope

def _norm(s: str) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.strip().lower()

def _parse_turno(value: str):
    """
    Normaliza para choices do modelo: 'Manhã' ou 'Tarde'.
    Aceita variações: manha, manhã, m, matutino -> Manhã | tarde, t, vespertino -> Tarde
    """
    v = _norm(value)
    if not v:
        return None
    if v in {"manha", "manhã", "m", "matutino", "man", "am"}:
        return "Manhã"
    if v in {"tarde", "t", "vespertino", "tar", "pm"}:
        return "Tarde"
    return None

_TIME_PATTERNS = [
    r"^\s*(\d{1,2})[:hH\.](\d{2})\s*$",   # 8:30, 08:30, 8h30, 8.30
    r"^\s*(\d{1,2})\s*[:hH]\s*$",         # 8:, 8h  -> minutos = 00
    r"^\s*(\d{1,2})(\d{2})\s*$",          # 0830, 930 -> HHMM
    r"^\s*(\d{1,2})\s*$",                 # 8 -> 08:00
]

def _parse_time(value):
    """
    Aceita '08:00', '8:00', '08:00:00', '8h30', '0830', '8', '8h', etc.
    Retorna datetime.time ou None.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    # tenta formatos padrão do pandas/excel (p.ex. já vem como datetime.time)
    if hasattr(value, "hour") and hasattr(value, "minute"):
        try:
            return time(int(value.hour), int(value.minute))
        except Exception:
            pass

    # remove segundos se vier “HH:MM:SS”
    if re.match(r"^\d{1,2}:\d{2}:\d{2}$", s):
        s = s[:5]  # HH:MM

    for pat in _TIME_PATTERNS:
        m = re.match(pat, s)
        if not m:
            continue
        if pat == _TIME_PATTERNS[0]:
            hh, mm = int(m.group(1)), int(m.group(2))
        elif pat == _TIME_PATTERNS[1]:
            hh, mm = int(m.group(1)), 0
        elif pat == _TIME_PATTERNS[2]:
            raw_h, raw_m = m.group(1), m.group(2)
            hh, mm = int(raw_h), int(raw_m)
        else:  # only hour
            hh, mm = int(m.group(1)), 0

        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return time(hh, mm)
        return None

    return None

def _pick_col(df, *candidatos):
    """
    Retorna o nome real da coluna no df que corresponda a qualquer um dos candidatos (case/acentos-insensitive).
    Ex.: _pick_col(df, 'Matrícula', 'matricula', 'matricula*') -> 'Matrícula'
    """
    norm_map = {_norm(c): c for c in df.columns}
    for c in candidatos:
        c_norm = _norm(c)
        if c_norm in norm_map:
            return norm_map[c_norm]
    return None

@login_required
def importar_horarios_trabalho(request):
    if request.method == 'POST' and request.FILES.get('arquivo_horarios'):
        arquivo = request.FILES['arquivo_horarios']
        nome = arquivo.name.lower()

        # aceita .xlsx, .xls, .csv
        if not nome.endswith(('.xlsx', '.xls', '.csv')):
            messages.error(request, "Envie um arquivo .xlsx, .xls ou .csv válido.")
            return render(request, 'controle/importar_horarios.html')

        # leitura com fallbacks de engine
        try:
            if nome.endswith('.csv'):
                df = pd.read_csv(arquivo)
            elif nome.endswith('.xlsx'):
                try:
                    import openpyxl  # noqa
                except ImportError:
                    messages.error(request, "Faltando 'openpyxl' para .xlsx. Instale: pip install openpyxl (ou envie CSV).")
                    return render(request, 'controle/importar_horarios.html')
                df = pd.read_excel(arquivo, engine='openpyxl')
            else:  # .xls
                try:
                    import xlrd  # noqa
                except ImportError:
                    messages.error(request, "Faltando 'xlrd' para .xls. Instale: pip install xlrd (ou converta para .xlsx/CSV).")
                    return render(request, 'controle/importar_horarios.html')
                df = pd.read_excel(arquivo, engine='xlrd')
        except Exception as e:
            messages.error(request, f'Erro ao abrir arquivo: {e}')
            return render(request, 'controle/importar_horarios.html')

        # normaliza cabeçalhos
        df.columns = [str(c).strip() for c in df.columns]

        # tenta localizar colunas (flexível)
        col_matricula = _pick_col(df, 'Matrícula', 'matricula')
        col_nome      = _pick_col(df, 'Nome', 'nome')
        col_turno     = _pick_col(df, 'Turno', 'turno')
        col_inicio    = _pick_col(df, 'Horário Início', 'Horario Inicio', 'horario_inicio', 'inicio', 'início', 'hora inicio')
        col_fim       = _pick_col(df, 'Horário Fim', 'Horario Fim', 'horario_fim', 'fim', 'hora fim')

        # requisitos mínimos
        if not col_turno or not col_inicio or not col_fim:
            messages.error(request, "Colunas obrigatórias ausentes: 'Turno', 'Horário Início' e 'Horário Fim'.")
            return render(request, 'controle/importar_horarios.html')

        if not col_matricula and not col_nome:
            messages.error(request, "Informe ao menos uma coluna de identificação do servidor: 'Matrícula' ou 'Nome'.")
            return render(request, 'controle/importar_horarios.html')

        total_ok = 0
        warn_func_nao_encontrado = 0
        warn_ambiguidade = 0
        warn_turno_invalido = 0
        warn_hora_invalida = 0

        # opcional: usar Setor para desambiguar nomes
        col_setor = _pick_col(df, 'Setor')

        def _cell(row, col):
            val = row.get(col)
            if pd.isna(val):
                return ""
            return str(val).strip()

        with transaction.atomic():
            for _, row in df.iterrows():
                # Identificação do funcionário
                func_qs = Funcionario.objects.all()

                if col_matricula:
                    matricula = _cell(row, col_matricula)
                    if matricula:
                        func_qs = func_qs.filter(matricula__iexact=matricula)
                    else:
                        func_qs = Funcionario.objects.none()
                else:
                    nome_func = _cell(row, col_nome)
                    func_qs = func_qs.filter(nome__iexact=nome_func)

                # Restringe por escopo do usuário
                func_qs = filter_funcionarios_by_scope(func_qs, request.user)

                # Se nome, tentar desambiguar por setor (se existir coluna)
                if col_matricula is None and col_setor:
                    setor_nome = _cell(row, col_setor)
                    if setor_nome:
                        func_qs = func_qs.filter(setor__nome__iexact=setor_nome)

                count = func_qs.count()
                if count == 0:
                    warn_func_nao_encontrado += 1
                    continue
                if count > 1:
                    warn_ambiguidade += 1
                    continue

                funcionario = func_qs.first()

                # Turno
                turno_raw = _cell(row, col_turno)
                turno = _parse_turno(turno_raw)
                if turno is None:
                    warn_turno_invalido += 1
                    continue

                # Horários
                ini = _parse_time(row.get(col_inicio))
                fim = _parse_time(row.get(col_fim))
                if not ini or not fim:
                    warn_hora_invalida += 1
                    continue

                # grava (1 registro por funcionario+turno)
                HorarioTrabalho.objects.update_or_create(
                    funcionario=funcionario,
                    turno=turno,
                    defaults={'horario_inicio': ini, 'horario_fim': fim}
                )
                total_ok += 1

        # mensagens finais
        base_msg = f"{total_ok} horário(s) importado(s)/atualizado(s)."
        avisos = []
        if warn_func_nao_encontrado: avisos.append(f"{warn_func_nao_encontrado} funcionário(s) fora do escopo/não encontrado(s)")
        if warn_ambiguidade: avisos.append(f"{warn_ambiguidade} linha(s) ambígua(s) (mais de um funcionário)")
        if warn_turno_invalido: avisos.append(f"{warn_turno_invalido} com turno inválido (use Manhã/Tarde)")
        if warn_hora_invalida: avisos.append(f"{warn_hora_invalida} com horário inválido")

        if avisos:
            messages.warning(request, base_msg + " Avisos: " + "; ".join(avisos))
        else:
            messages.success(request, base_msg)

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

def _fmt(t: time | None) -> str:
    return t.strftime('%H:%M') if t else ''

def _parse_hhmm(value: str | None) -> time | None:
    """Aceita '', '08:00', '8:00', '08:00:00'."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    # HH:MM:SS -> HH:MM
    if len(s) == 8 and s[2] == ':' and s[5] == ':':
        s = s[:5]
    try:
        dt = datetime.strptime(s, '%H:%M')
        return time(dt.hour, dt.minute)
    except ValueError:
        return None


@login_required
def listar_horarios_funcionarios(request):
    """
    Lista todos os funcionários visíveis ao usuário + horários (Manhã/Tarde).
    Possui busca por nome e filtro por setor.
    """
    q = (request.GET.get('q') or '').strip()
    setor_id = (request.GET.get('setor') or '').strip()

    base_qs = Funcionario.objects.select_related('setor').prefetch_related(
        Prefetch('horariotrabalho_set', queryset=HorarioTrabalho.objects.order_by('turno'))
    ).order_by(Lower('nome'))

    # respeita escopo
    base_qs = filter_funcionarios_by_scope(base_qs, request.user)

    if q:
        base_qs = base_qs.filter(nome__icontains=q)
    if setor_id:
        base_qs = base_qs.filter(setor_id=setor_id)

    linhas = []
    for f in base_qs:
        # pega 2 registros (um manhã, um tarde)
        manha = next((h for h in f.horariotrabalho_set.all() if h.turno == 'Manhã'), None)
        tarde = next((h for h in f.horariotrabalho_set.all() if h.turno == 'Tarde'), None)

        linhas.append({
            "funcionario": f,                     # para usar id/nome no template
            "nome": f.nome,
            "setor": f.setor.nome if f.setor else "",
            "turno_cadastro": f.turno or "",
            "vinculo": f.tipo_vinculo or "",
            "m_ini": _fmt(manha.horario_inicio) if manha else "",
            "m_fim": _fmt(manha.horario_fim) if manha else "",
            "t_ini": _fmt(tarde.horario_inicio) if tarde else "",
            "t_fim": _fmt(tarde.horario_fim) if tarde else "",
        })

    setores = filter_funcionarios_by_scope(
        Funcionario.objects.select_related('setor'), request.user
    ).values_list('setor_id', 'setor__nome').distinct().order_by('setor__nome')

    context = {
        "linhas": linhas,
        "setores": setores,
        "filtros": {"q": q, "setor": setor_id},
    }
    return render(request, "controle/listar_horarios_funcionarios.html", context)


@login_required
def editar_horarios_funcionario(request, funcionario_id: int):
    """
    Edita os dois turnos (Manhã/Tarde) de um funcionário em um único formulário.
    - Se um turno vier vazio (início e fim), o registro é removido.
    - Caso contrário, é criado/atualizado via update_or_create.
    """
    f = get_object_or_404(Funcionario, id=funcionario_id)

    # checa escopo
    if not filter_funcionarios_by_scope(Funcionario.objects.filter(id=f.id), request.user).exists():
        messages.error(request, "Você não tem permissão para editar este servidor.")
        return redirect("listar_horarios_funcionarios")

    # existentes
    manha = HorarioTrabalho.objects.filter(funcionario=f, turno='Manhã').first()
    tarde = HorarioTrabalho.objects.filter(funcionario=f, turno='Tarde').first()

    if request.method == "POST":
        m_ini = _parse_hhmm(request.POST.get("manha_inicio"))
        m_fim = _parse_hhmm(request.POST.get("manha_fim"))
        t_ini = _parse_hhmm(request.POST.get("tarde_inicio"))
        t_fim = _parse_hhmm(request.POST.get("tarde_fim"))

        # Manhã
        if m_ini and m_fim:
            HorarioTrabalho.objects.update_or_create(
                funcionario=f, turno='Manhã',
                defaults={"horario_inicio": m_ini, "horario_fim": m_fim}
            )
        else:
            HorarioTrabalho.objects.filter(funcionario=f, turno='Manhã').delete()

        # Tarde
        if t_ini and t_fim:
            HorarioTrabalho.objects.update_or_create(
                funcionario=f, turno='Tarde',
                defaults={"horario_inicio": t_ini, "horario_fim": t_fim}
            )
        else:
            HorarioTrabalho.objects.filter(funcionario=f, turno='Tarde').delete()

        messages.success(request, "Horários atualizados com sucesso.")
        return redirect("listar_horarios_funcionarios")

    context = {
        "f": f,
        "m_ini": _fmt(manha.horario_inicio) if manha else "",
        "m_fim": _fmt(manha.horario_fim) if manha else "",
        "t_ini": _fmt(tarde.horario_inicio) if tarde else "",
        "t_fim": _fmt(tarde.horario_fim) if tarde else "",
    }
    return render(request, "controle/editar_horarios_funcionario.html", context)


# ---------- Normalizador de horários livres ----------
_HHMM_TOKEN = re.compile(r'(\d{1,2})(?::|h|H|\.|)?(\d{0,2})')

def _fmt_hhmm(h: str, m: str) -> str | None:
    if m == "" or m is None:
        m = "00"
    try:
        hh = int(h)
        mm = int(m)
    except ValueError:
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return f"{hh:02d}:{mm:02d}"

def normalizar_horario_livre(texto: str) -> str:
    """
    Converte entradas como:
      '17h25min às 20h40min', '17:25 as 20:40', '17 25 - 20 40', '17-20'
    para '17:25–20:40' (EN DASH). Se achar só um horário, retorna 'HH:MM'.
    Se nada for reconhecido, retorna ''.
    """
    if not texto:
        return ""
    s = str(texto).strip().lower()

    # normaliza conectores para '-'
    s = s.replace('—', '-').replace('–', '-')
    s = re.sub(r'\b(às|ás|as|ate|até|a)\b', '-', s)
    # remove rótulos
    s = re.sub(r'\b(min|mins|minuto|minutos|hora|horas|hs?)\b', '', s)
    s = s.replace(' ', '')

    # extrai pares de hora/minuto com minutos opcionais
    tokens = _HHMM_TOKEN.findall(s)
    horarios = []
    for h, m in tokens:
        hhmm = _fmt_hhmm(h, m)
        if hhmm:
            horarios.append(hhmm)
    if not horarios:
        return ""

    # Se houver separador '-', tenta separar blocos
    if '-' in s:
        blocos = s.split('-', 1)
        # conta quantos tokens em cada bloco para pegar o primeiro horário de cada lado
        esquerdo = _HHMM_TOKEN.findall(blocos[0])
        direito  = _HHMM_TOKEN.findall(blocos[1])
        h_ini = _fmt_hhmm(*esquerdo[0]) if esquerdo else None
        h_fim = _fmt_hhmm(*direito[0])  if direito  else None
        if h_ini and h_fim:
            return f"{h_ini}–{h_fim}"
        if h_ini:
            return h_ini
        return horarios[0]

    # sem '-', use os dois primeiros horários (se houver)
    if len(horarios) >= 2:
        return f"{horarios[0]}–{horarios[1]}"
    return horarios[0]


# ---------- PLANEJAMENTO EM LOTE ----------
@login_required
def planejamento_lote(request):
    """
    Define (em lote) o 'horario_planejamento' para todos os servidores
    com tem_planejamento=True, respeitando o escopo do usuário.
    Aceita formatos livres (ex.: '17h25min ás 20h40min').
    """
    if request.method == 'POST':
        # pode vir como 'horario' (form único) ou múltiplos campos 'horario' (por segurança)
        candidatos = [v.strip() for v in request.POST.getlist('horario') if v.strip()]
        horario_bruto = candidatos[0] if candidatos else (request.POST.get('horario') or '').strip()
        substituir = bool(request.POST.get('substituir'))

        horario_norm = normalizar_horario_livre(horario_bruto)
        if not horario_norm:
            messages.error(request, "Informe um intervalo válido, ex.: 08:00–10:00 (aceita '08h às 10h').")
            return render(request, 'controle/planejamento_lote.html', {
                'filtros': {},
                'exemplo': '08:00–10:00',
            })

        qs = filter_funcionarios_by_scope(
            Funcionario.objects.filter(tem_planejamento=True),
            request.user
        )

        if not substituir:
            qs = qs.filter(Q(horario_planejamento__isnull=True) | Q(horario_planejamento__exact=''))

        atualizados = qs.update(horario_planejamento=horario_norm)

        if atualizados:
            messages.success(request, f"Horário de planejamento aplicado a {atualizados} servidor(es): {horario_norm}.")
        else:
            if substituir:
                messages.info(request, "Nenhum servidor com planejamento no seu escopo.")
            else:
                messages.info(request, "Todos no seu escopo já possuíam horário de planejamento.")

        return redirect('controle:listar_horarios_funcionarios')

    # GET
    return render(request, 'controle/planejamento_lote.html', {
        'filtros': {},
        'exemplo': '08:00–10:00',
    })


# ---------- SELECIONAR FUNCIONÁRIOS (habilitar/remover) ----------
@login_required
def selecionar_funcionarios_planejamento(request):
    """
    Lista funcionários para habilitar/desabilitar 'tem_planejamento' em massa.
    Opcionalmente grava um 'horario_planejamento' padrão nos habilitados.
    """
    setores = filter_setores_by_scope(Setor.objects.all(), request.user).order_by('nome')
    qs = (filter_funcionarios_by_scope(
            Funcionario.objects.select_related('setor'),
            request.user
         )
         .order_by(Lower('nome')))

    setor_id = (request.GET.get('setor') or '').strip()
    busca = (request.GET.get('q') or '').strip()

    if setor_id:
        qs = qs.filter(setor_id=setor_id)
    if busca:
        qs = qs.filter(nome__icontains=busca)

    if request.method == 'POST':
        ids = request.POST.getlist('funcionarios')          # todos os checkboxes marcados
        acao = request.POST.get('acao')

        # no template há 2 campos "horario_padrao" (topo e rodapé):
        hp_cands = [v.strip() for v in request.POST.getlist('horario_padrao') if v.strip()]
        horario_raw = hp_cands[0] if hp_cands else (request.POST.get('horario_padrao') or '').strip()
        horario_norm = normalizar_horario_livre(horario_raw)

        if not ids:
            messages.warning(request, "Nenhum funcionário selecionado.")
            return redirect('controle:selecionar_funcionarios_planejamento')

        alvo_qs = filter_funcionarios_by_scope(Funcionario.objects.filter(id__in=ids), request.user)

        with transaction.atomic():
            if acao == 'habilitar':
                if horario_norm:
                    n = alvo_qs.update(tem_planejamento=True, horario_planejamento=horario_norm)
                    messages.success(request, f"Planejamento habilitado para {n} funcionário(s). Horário: {horario_norm}.")
                else:
                    n = alvo_qs.update(tem_planejamento=True)
                    messages.success(request, f"Planejamento habilitado para {n} funcionário(s).")
            elif acao == 'remover':
                n = alvo_qs.update(tem_planejamento=False, horario_planejamento=None)
                messages.success(request, f"Planejamento removido de {n} funcionário(s).")
            else:
                messages.error(request, "Ação inválida.")
                # preserva filtros
                base = reverse('controle:selecionar_funcionarios_planejamento')
                query = urlencode({k: v for k, v in [('setor', setor_id), ('q', busca)] if v})
                return redirect(f"{base}?{query}" if query else base)

        # preserva filtros na volta
        base = reverse('controle:selecionar_funcionarios_planejamento')
        query = urlencode({k: v for k, v in [('setor', setor_id), ('q', busca)] if v})
        return redirect(f"{base}?{query}" if query else base)

    context = {
        'funcionarios': qs,
        'setores': setores,
        'filtros': {'setor': setor_id, 'q': busca},
    }
    return render(request, 'controle/selecionar_funcionarios_planejamento.html', context)

@login_required
def excluir_folhas_selecionadas(request):
    if request.method != 'POST':
        return redirect('controle:listar_folhas')  # volte para a listagem

    ids = request.POST.getlist('folhas')
    if not ids:
        messages.warning(request, 'Nenhuma folha selecionada.')
        return redirect('controle:listar_folhas')

    # Filtra as folhas pelos IDs enviados
    qs = (FolhaFrequencia.objects
          .select_related('funcionario')
          .filter(id__in=ids))

    # (Opcional, mas recomendado) restringe por escopo do usuário
    funcionarios_no_escopo = filter_funcionarios_by_scope(
        Funcionario.objects.all(), request.user
    )
    qs = qs.filter(funcionario__in=funcionarios_no_escopo)

    n = qs.count()
    qs.delete()

    messages.success(request, f'{n} folha(s) excluída(s).')
    return redirect('controle:listar_folhas')

@login_required
def sabados_letivos(request):
    """
    Página única para cadastrar um Sábado Letivo e listar todos os já cadastrados.
    """
    if request.method == 'POST':
        # Exclusão individual (mesma página)
        if request.POST.get('acao') == 'excluir' and request.POST.get('id'):
            try:
                SabadoLetivo.objects.filter(id=request.POST['id']).delete()
                messages.success(request, "Sábado letivo removido.")
            except Exception:
                messages.error(request, "Não foi possível remover este dia.")
            return redirect('controle:sabados_letivos')

        # Cadastro
        data_str = (request.POST.get('data') or '').strip()
        descricao = (request.POST.get('descricao') or '').strip()

        if not data_str:
            messages.error(request, "Informe a data.")
            return redirect('controle:sabados_letivos')

        try:
            d = date.fromisoformat(data_str)  # YYYY-MM-DD
        except ValueError:
            messages.error(request, "Data inválida. Use o seletor de data.")
            return redirect('controle:sabados_letivos')

        # Garante que é um sábado (segunda=0 ... sábado=5)
        if d.weekday() != 5:
            messages.error(request, "A data informada não é sábado. Escolha um sábado.")
            return redirect('controle:sabados_letivos')

        try:
            obj, created = SabadoLetivo.objects.get_or_create(
                data=d,
                defaults={'descricao': descricao or None}
            )
            if created:
                messages.success(request, "Sábado letivo cadastrado com sucesso.")
            else:
                # Atualiza descrição, se enviada
                if descricao:
                    obj.descricao = descricao
                    obj.save(update_fields=['descricao'])
                    messages.success(request, "Sábado letivo já existia; descrição atualizada.")
                else:
                    messages.info(request, "Este sábado letivo já estava cadastrado.")
        except IntegrityError:
            messages.error(request, "Este sábado letivo já está cadastrado.")
        except Exception:
            messages.error(request, "Não foi possível cadastrar o sábado letivo.")

        return redirect('controle:sabados_letivos')

    sabados = SabadoLetivo.objects.all().order_by('data')
    return render(request, 'controle/sabados_letivos.html', {'sabados': sabados})

# controle/views.py
from collections import defaultdict, namedtuple
import calendar
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Case, When, IntegerField
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from .forms import CalendarioEventoForm
from .models import CalendarioEvento, Feriado, SabadoLetivo, Orgao

# ======================== Configurações & utilidades =========================

# Ordem para decidir a cor da CÉLULA (menor índice = maior prioridade)
_CATEGORIA_PRIORIDADE = [
    "FERIADO", "RECESSO", "NAO_LETIVO",
    "SAETO", "AVALIACAO", "AVALIACAO_DIAGNOSTICA", "RECUPERACOES_FINAIS",
    "CONSELHO_PEDAGOGICO", "PPP_AVALIACAO", "FORMACAO_TURMAS", "FORMATURAS",
    "MATRICULAS", "AULA_INAUGURAL", "INICIO_BIMESTRE", "FORMACOES_CONTINUADAS",
    "AULA", "REUNIAO", "PLANEJAMENTO",
    # ↓ prioridade baixa, não “pinta” por cima de não-letivos/avaliações
    "DATAS_COMEMORATIVAS",
    "INDEPENDENCIA_BRASIL", "OUTRO",
]
_PRI = {cat: i for i, cat in enumerate(_CATEGORIA_PRIORIDADE)}

DisplayEvent = namedtuple("DisplayEvent", "titulo categoria pk")

PT_MESES = [
    "Janeiro","Fevereiro","Março","Abril","Maio","Junho",
    "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"
]

def _month_weeks(y: int, m: int):
    """Matriz de semanas (domingo como primeiro dia)."""
    cal = calendar.Calendar(firstweekday=6)  # 6=domingo
    return cal.monthdatescalendar(y, m)

def _month_bounds(y: int, m: int):
    first = date(y, m, 1)
    last = date(y, m, calendar.monthrange(y, m)[1])
    return first, last

def _daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)

# ========================= Mapa de eventos por dia (mês) =====================

def _events_map_for_month(y: int, m: int, orgao: Orgao | None = None):
    """
    Retorna (weeks, events_by_day) para o mês informado.
    Une: CalendarioEvento + Feriado + SabadoLetivo (como AULA).
    Aplica prioridade para facilitar a cor da célula.
    """
    first, last = _month_bounds(y, m)
    weeks = _month_weeks(y, m)
    ev_map: dict[date, list] = defaultdict(list)

    # Eventos (globais e/ou por órgão)
    ce_qs = (
        CalendarioEvento.objects
        .filter(Q(data_inicio__lte=last) & Q(data_fim__gte=first))
        .order_by("data_inicio", "titulo")
        .select_related("orgao")
    )
    if orgao:
        ce_qs = ce_qs.filter(Q(orgao__isnull=True) | Q(orgao=orgao))

    for ev in ce_qs:
        span_ini = max(ev.data_inicio, first)
        span_fim = min(ev.data_fim, last)
        for d in _daterange(span_ini, span_fim):
            ev_map[d].append(ev)

    # Feriados (injetados)
    for f in Feriado.objects.filter(data__range=(first, last)).order_by("data"):
        ev_map[f.data].append(
            DisplayEvent(titulo=f"Feriado — {f.descricao}", categoria="FERIADO", pk=None)
        )

    # Sábados letivos (injetados como AULA)
    for s in SabadoLetivo.objects.filter(data__range=(first, last)).order_by("data"):
        if s.data.weekday() == 5:  # sábado
            ev_map[s.data].append(
                DisplayEvent(titulo="Sábado Letivo", categoria="AULA", pk=None)
            )

    # Prioridade para definir a cor
    for k, lst in ev_map.items():
        ev_map[k] = sorted(lst, key=lambda e: _PRI.get(getattr(e, "categoria", "OUTRO"), 999))

    return weeks, dict(ev_map)

# ========================= Cálculo de dias letivos ===========================

def _dias_letivos_do_mes(y: int, m: int, events_by_day: dict) -> int:
    """
    Regras:
      - Seg–Sex são letivos, EXCETO se houver FERIADO/RECESSO/NAO_LETIVO.
      - Sábado conta apenas se marcado como letivo (AULA/AULA_INAUGURAL ou SabadoLetivo).
      - Domingo não conta.
    """
    first, last = _month_bounds(y, m)

    feriados_model = set(
        Feriado.objects.filter(data__range=(first, last)).values_list("data", flat=True)
    )
    nao_letivo_cats = {"FERIADO", "RECESSO", "NAO_LETIVO"}
    feriados_eventos = {
        d for d, evs in events_by_day.items()
        if any(getattr(e, "categoria", "") in nao_letivo_cats for e in evs)
    }
    feriados = feriados_model | feriados_eventos

    sabados_tabela = set(
        SabadoLetivo.objects.filter(data__range=(first, last)).values_list("data", flat=True)
    )

    letivos = 0
    for d in _daterange(first, last):
        wd = d.weekday()  # 0=seg ... 6=dom
        if wd <= 4:  # seg-sex
            if d not in feriados:
                letivos += 1
        elif wd == 5:  # sábado
            marcado_evento = any(
                getattr(e, "categoria", "") in {"AULA", "AULA_INAUGURAL"} for e in events_by_day.get(d, [])
            )
            if (marcado_evento or d in sabados_tabela) and d not in feriados:
                letivos += 1
        # domingo: ignora
    return letivos

# =======================  Calendário (mensal) + cadastro  ====================

@login_required
def calendario_escolar(request):
    today = timezone.localdate()
    ano = int(request.GET.get("ano", today.year))
    mes = int(request.GET.get("mes", today.month))
    orgao_id = request.GET.get("orgao") or None
    orgao = get_object_or_404(Orgao, pk=orgao_id) if orgao_id else None

    # POST: criar evento
    if request.method == "POST":
        form = CalendarioEventoForm(request.POST)
        if form.is_valid():
            ev = form.save()
            messages.success(request, "Evento salvo com sucesso.")
            url = f"{request.path}?ano={ev.data_inicio.year}&mes={ev.data_inicio.month}"
            if ev.orgao_id:
                url += f"&orgao={ev.orgao_id}"
            return redirect(url)
        messages.error(request, "Corrija os campos destacados.")
    else:
        form = CalendarioEventoForm()

    # Dados do mês
    weeks, events_by_day = _events_map_for_month(ano, mes, orgao=orgao)
    letivos_mes = _dias_letivos_do_mes(ano, mes, events_by_day)

    # Navegação
    prev_y, prev_m = (ano - 1, 12) if mes == 1 else (ano, mes - 1)
    next_y, next_m = (ano + 1, 1) if mes == 12 else (ano, mes + 1)

    orgaos = Orgao.objects.all().order_by(
        "secretaria__prefeitura__nome", "secretaria__nome", "nome"
    )

    context = {
        "now": timezone.now(),
        "ano": ano,
        "mes": mes,
        "mes_nome": calendar.month_name[mes].capitalize(),
        "prev_m": prev_m, "prev_y": prev_y,
        "next_m": next_m, "next_y": next_y,
        "orgao": orgao,
        "orgaos": orgaos,
        "weeks": weeks,
        "events_by_day": events_by_day,
        "letivos_mes": letivos_mes,
        "form": form,
    }
    return render(request, "controle/calendario_escolar.html", context)

@login_required
def calendario_excluir(request, pk: int):
    ev = get_object_or_404(CalendarioEvento, pk=pk)
    ano = ev.data_inicio.year
    mes = ev.data_inicio.month
    orgao_id = ev.orgao_id
    ev.delete()
    messages.success(request, "Evento excluído.")
    url = f"{redirect('controle:calendario_escolar').url}?ano={ano}&mes={mes}"
    if orgao_id:
        url += f"&orgao={orgao_id}"
    return redirect(url)

# =============================  Impressão (12 meses) =========================

@login_required
def calendario_impressao(request):
    today = timezone.localdate()
    ano = int(request.GET.get("ano", today.year))
    orgao_id = request.GET.get("orgao") or None
    orgao = get_object_or_404(Orgao, pk=orgao_id) if orgao_id else None

    # ===== Grids mensais (domingo como primeiro dia) =====
    cal = calendar.Calendar(firstweekday=6)
    meses = []
    for m in range(1, 13):
        weeks, wk = [], []
        for d in cal.itermonthdates(ano, m):
            wk.append(d)
            if len(wk) == 7:
                weeks.append(wk)
                wk = []
        meses.append({
            "nome": PT_MESES[m-1],
            "month_num": m,
            "year": ano,
            "weeks": weeks,
        })

    # ===== Eventos do ano (globais + órgão) =====
    ano_ini, ano_fim = date(ano, 1, 1), date(ano, 12, 31)
    ev_qs = (CalendarioEvento.objects
             .filter(data_inicio__lte=ano_fim, data_fim__gte=ano_ini)
             .select_related('orgao'))

    if orgao:
        ev_qs = ev_qs.filter(Q(orgao=orgao) | Q(orgao__isnull=True))

    prioridade = Case(
        When(categoria='FERIADO', then=0),
        When(categoria='RECESSO', then=1),
        When(categoria='AULA', then=2),
        default=9,
        output_field=IntegerField(),
    )
    ev_qs = ev_qs.order_by('data_inicio', prioridade, 'titulo')

    # ===== Mapa de eventos por dia (apenas DIAS DO MÊS) =====
    events_by_day: dict[date, list] = {}

    # Cria chaves apenas para dias que pertencem ao mês do card
    for m in meses:
        for week in m["weeks"]:
            for d in week:
                if d.month == m["month_num"]:
                    events_by_day.setdefault(d, [])

    # Preenche com eventos (apenas se o dia está no mês correspondente)
    for ev in ev_qs:
        s = max(ev.data_inicio, ano_ini)
        f = min(ev.data_fim, ano_fim)
        cur = s
        while cur <= f:
            if cur in events_by_day:          # só dias do mês
                events_by_day[cur].append(ev)
            cur += timedelta(days=1)

    # Injeta feriados
    for f in Feriado.objects.filter(data__range=(ano_ini, ano_fim)).order_by('data'):
        if f.data in events_by_day:
            events_by_day[f.data].append(
                DisplayEvent(titulo=f"Feriado — {f.descricao}", categoria="FERIADO", pk=None)
            )

    # Injeta sábados letivos (como AULA)
    for s in SabadoLetivo.objects.filter(data__range=(ano_ini, ano_fim)).order_by('data'):
        if s.data in events_by_day and s.data.weekday() == 5:
            events_by_day[s.data].append(
                DisplayEvent(titulo="Sábado Letivo", categoria="AULA", pk=None)
            )

    # Ordena por prioridade (para a cor da célula no template)
    for k, lst in events_by_day.items():
        events_by_day[k] = sorted(lst, key=lambda e: _PRI.get(getattr(e, "categoria", "OUTRO"), 999))

    # ===== Dias letivos por mês (e total anual) =====
    for m in meses:
        local_map = {
            d: events_by_day.get(d, [])
            for w in m["weeks"] for d in w
            if d.month == m["month_num"]          # só dias do mês
        }
        m["letivos"] = _dias_letivos_do_mes(m["year"], m["month_num"], local_map)

    letivos_total_ano = sum(m["letivos"] for m in meses)

    # ===== Listas para as seções "Datas comemorativas" e "Eventos" =====
    eventos_lista = (CalendarioEvento.objects
                     .filter(Q(data_inicio__year=ano) | Q(data_fim__year=ano))
                     .order_by("data_inicio", "titulo")
                     .select_related("orgao"))
    if orgao:
        eventos_lista = eventos_lista.filter(Q(orgao=orgao) | Q(orgao__isnull=True))

    datas_comemorativas = eventos_lista.filter(categoria="DATAS_COMEMORATIVAS")
    eventos_regulares = eventos_lista.exclude(categoria="DATAS_COMEMORATIVAS")

    # OBS: nomes e logos são fixos no template (estáticos), não passamos prefeitura/secretaria aqui.
    context = {
        "ano": ano,
        "orgao": orgao,
        "meses": meses,
        "events_by_day": events_by_day,
        "letivos_total_ano": letivos_total_ano,
        "datas_comemorativas": datas_comemorativas,
        "eventos_regulares": eventos_regulares,
    }
    return render(request, "controle/calendario_impressao.html", context)




 