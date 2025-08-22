# controle/urls.py
from django.urls import path
from django.shortcuts import redirect
from django.conf import settings
from django.conf.urls.static import static
from . import views
from .views import (
    importar_horarios_trabalho,
    ficha_funcionario,
    relatorio_personalizado_funcionarios,
    gerar_folhas_multimes_funcionario,
    PainelLoginView,
    PainelLogoutView,
    scope_manager,
    scope_debug,
    acessos_conceder,
    acessos_revogar,
)

# 👇 adicione esta linha logo abaixo dos imports
app_name = "controle"

# raiz: se logado vai ao painel, senão vai ao login
def root_redirect(request):
    return redirect("controle:painel_controle" if request.user.is_authenticated else "controle:login")


urlpatterns = [
    path("", root_redirect, name="root"),

    # auth
    path("login/", PainelLoginView.as_view(), name="login"),
    path("logout/", PainelLogoutView.as_view(), name="logout"),

    # painel
    path("painel/", views.painel_controle, name="painel_controle"),
    path("painel-alunos/", views.painel_controle, name="painel_alunos"),

    # funcionalidades principais
    path("folha-frequencia/<int:funcionario_id>/<int:mes>/<int:ano>/", views.gerar_folha_frequencia, name="folha_frequencia"),
    path("selecionar-folhas/", views.selecionar_funcionarios, name="selecionar_funcionarios"),
    path("folhas-geradas/", views.listar_folhas, name="listar_folhas"),
    path("folha/<int:folha_id>/", views.visualizar_folha_salva, name="visualizar_folha_salva"),
    path("gerar-folhas-em-lote/", views.gerar_folhas_em_lote, name="gerar_folhas_em_lote"),
    path("gerar-folhas-lote/",    views.gerar_folhas_em_lote, name="gerar_folhas_lote"),

    # funcionários
    path("cadastrar-funcionario/", views.cadastrar_funcionario, name="cadastrar_funcionario"),
    path("funcionarios/", views.listar_funcionarios, name="listar_funcionarios"),
    path("funcionario/<int:funcionario_id>/editar/", views.editar_funcionario, name="editar_funcionario"),
    path("excluir-funcionario/<int:id>/", views.excluir_funcionario, name="excluir_funcionario"),

    # horários
    path("cadastrar-horario/", views.cadastrar_horario, name="cadastrar_horario"),
    path("editar-horario/<int:funcionario_id>/", views.editar_horario, name="editar_horario"),

    # feriados
    path("feriados/", views.cadastrar_feriado, name="cadastrar_feriado"),
    path("feriado/<int:feriado_id>/editar/", views.editar_feriado, name="editar_feriado"),
    path("feriado/<int:feriado_id>/excluir/", views.excluir_feriado, name="excluir_feriado"),

    # folhas
    path("excluir-folha/<int:folha_id>/", views.excluir_folha, name="excluir_folha"),

    # importações
    path("importar_funcionarios/", views.importar_funcionarios, name="importar_funcionarios"),
    path("importar-horarios/", importar_horarios_trabalho, name="importar_horarios_trabalho"),

    # livro de ponto
    path("livro-ponto/selecionar-capa/", views.selecionar_setor_capa, name="selecionar_capa"),
    path("livro-ponto/capas/", views.capas_livro_ponto, name="capas_livro_ponto"),

    # relatórios
    path("funcionario/<int:funcionario_id>/ficha/", ficha_funcionario, name="imprimir_ficha_funcionario"),
    path("relatorio-personalizado/", relatorio_personalizado_funcionarios, name="relatorio_personalizado_funcionarios"),
    path("relatorio-professores/", views.relatorio_professores, name="relatorio_professores"),
    path("relatorios-funcionarios/", views.relatorios_funcionarios, name="relatorios_funcionarios"),
    path("folhas/individuais/", gerar_folhas_multimes_funcionario, name="gerar_folhas_multimes_funcionario"),

    # superadmin: gestão e debug de escopos
    path("acessos/scopes/", scope_manager, name="scope_manager"),
    path("acessos/debug/", scope_debug, name="scope_debug"),
    path("acessos/conceder/", acessos_conceder, name="acessos_conceder"),
    path("acessos/revogar/", acessos_revogar, name="acessos_revogar"),

    # recessos
    path("recessos/novo/", views.recesso_bulk_create, name="recesso_bulk_create"),
    path("api/funcionarios-por-setor/", views.api_funcionarios_por_setor, name="api_funcionarios_por_setor"),

    path('recessos/', views.recessos_list, name='recessos_list'),
    path('recessos/<int:recesso_id>/editar/', views.recesso_edit, name='recesso_edit'),
    path('recessos/<int:recesso_id>/excluir/', views.recesso_delete, name='recesso_delete'),

    path("horarios/", views.listar_horarios_funcionarios, name="listar_horarios_funcionarios"),
    path("horarios/<int:funcionario_id>/editar/", views.editar_horarios_funcionario, name="editar_horarios_funcionarios"),
    path('planejamento/lote/', views.planejamento_lote, name='planejamento_lote'),
    path('planejamento/selecionar/', views.selecionar_funcionarios_planejamento, name='selecionar_funcionarios_planejamento'),
    path('folhas/excluir-selecionadas/', views.excluir_folhas_selecionadas, name='excluir_folhas_selecionadas'),
    path('sabados-letivos/', views.sabados_letivos, name='sabados_letivos'),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
