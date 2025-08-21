from django import forms
from django.contrib import admin, messages
from django.shortcuts import render
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils import timezone

from .models import (
    Prefeitura, Secretaria, Orgao, Setor, Funcionario,
    HorarioTrabalho, Feriado, FolhaFrequencia, SabadoLetivo,
    AcessoPrefeitura, AcessoSecretaria, AcessoOrgao, AcessoSetor, NivelAcesso,
    UserScope, FuncaoPermissao,
)
from .admin_forms import ConcederAcessoForm, RevogarAcessoForm

# =========================
# Branding do Admin
# =========================
admin.site.site_header = "Gestão de Frequência"
admin.site.site_title = "Admin • Frequência"
admin.site.index_title = "Painel de Administração"
admin.ModelAdmin.empty_value_display = "-"

# =========================
# Inlines
# =========================
class HorarioTrabalhoInline(admin.TabularInline):
    model = HorarioTrabalho
    extra = 0
    fields = ("turno", "horario_inicio", "horario_fim")
    autocomplete_fields = ("funcionario",)
    show_change_link = True


# ----- Inlines de Acesso para o Usuário -----
class AcessoPrefeituraInline(admin.TabularInline):
    model = AcessoPrefeitura
    extra = 0
    fields = ("prefeitura", "nivel")
    autocomplete_fields = ("prefeitura",)


class AcessoSecretariaInline(admin.TabularInline):
    model = AcessoSecretaria
    extra = 0
    fields = ("secretaria", "nivel")
    autocomplete_fields = ("secretaria",)


class AcessoOrgaoInline(admin.TabularInline):
    model = AcessoOrgao
    extra = 0
    fields = ("orgao", "nivel")
    autocomplete_fields = ("orgao",)


class AcessoSetorInline(admin.TabularInline):
    model = AcessoSetor
    extra = 0
    fields = ("setor", "nivel")
    autocomplete_fields = ("setor",)


# =========================
# Prefeitura / Secretaria / Órgão
# =========================
@admin.register(Prefeitura)
class PrefeituraAdmin(admin.ModelAdmin):
    list_display = ("nome", "cnpj", "cidade", "uf", "telefone", "email")
    search_fields = ("nome", "cnpj", "cidade", "email", "telefone")
    ordering = ("nome",)
    list_per_page = 25


@admin.register(Secretaria)
class SecretariaAdmin(admin.ModelAdmin):
    list_display = ("nome", "prefeitura", "cnpj", "telefone", "email")
    list_filter = ("prefeitura",)
    search_fields = ("nome", "cnpj", "email", "telefone", "prefeitura__nome")
    ordering = ("prefeitura__nome", "nome")
    list_select_related = ("prefeitura",)
    list_per_page = 25


@admin.register(Orgao)
class OrgaoAdmin(admin.ModelAdmin):
    list_display = ("nome", "secretaria", "cnpj", "telefone", "email")
    list_filter = ("secretaria", "secretaria__prefeitura")
    search_fields = ("nome", "cnpj", "email", "telefone", "secretaria__nome", "secretaria__prefeitura__nome")
    ordering = ("secretaria__prefeitura__nome", "secretaria__nome", "nome")
    list_select_related = ("secretaria", "secretaria__prefeitura")
    list_per_page = 25


# =========================
# Setor (com escolha de Chefe via FK)
# =========================
class SetorAdminForm(forms.ModelForm):
    chefe = forms.ModelChoiceField(
        label="Chefe do setor",
        required=False,
        queryset=Funcionario.objects.all().order_by("nome"),
        help_text="Selecione o servidor que será a chefia imediata deste setor.",
    )

    class Meta:
        model = Setor
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        inst = self.instance
        if inst and inst.pk and inst.chefe_id:
            self.initial["chefe"] = inst.chefe_id


@admin.register(Setor)
class SetorAdmin(admin.ModelAdmin):
    form = SetorAdminForm

    list_display = (
        "nome",
        "pai_tipo",
        "pai_nome",
        "secretaria_resolvida_nome",
        "prefeitura_resolvida_nome",
        "chefe_nome",
    )
    list_filter = ("prefeitura", "secretaria", "orgao")
    search_fields = (
        "nome",
        "prefeitura__nome",
        "secretaria__nome",
        "orgao__nome",
        "orgao__secretaria__nome",
        "orgao__secretaria__prefeitura__nome",
    )
    ordering = ("nome",)
    autocomplete_fields = ("prefeitura", "secretaria", "orgao", "chefe")
    list_select_related = ("prefeitura", "secretaria", "orgao", "orgao__secretaria", "orgao__secretaria__prefeitura")
    list_per_page = 25

    fieldsets = (
        (None, {"fields": ("nome",)}),
        ("Vinculação (marque exatamente um)", {"fields": ("prefeitura", "secretaria", "orgao")}),
        ("Chefia", {"fields": ("chefe",)}),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        # Define/atualiza a chefia do setor (via FK) – NÃO altera o setor do funcionário
        chefe = form.cleaned_data.get("chefe")
        if obj.chefe_id != (chefe.id if chefe else None):
            obj.chefe = chefe
            obj.save(update_fields=["chefe"])

        # Opcional: manter o flag informativo no funcionário
        if chefe and not chefe.is_chefe_setor:
            chefe.is_chefe_setor = True
            if not chefe.chefe_setor_desde:
                chefe.chefe_setor_desde = timezone.localdate()
            chefe.save(update_fields=["is_chefe_setor", "chefe_setor_desde"])

    # helpers
    def pai_tipo(self, obj):
        if obj.orgao_id:
            return "Órgão"
        if obj.secretaria_id:
            return "Secretaria"
        if obj.prefeitura_id:
            return "Prefeitura"
        return "-"
    pai_tipo.short_description = "Nível"

    def pai_nome(self, obj):
        if obj.orgao_id:
            return obj.orgao.nome
        if obj.secretaria_id:
            return obj.secretaria.nome
        if obj.prefeitura_id:
            return obj.prefeitura.nome
        return "-"
    pai_nome.short_description = "Vinculado a"

    def secretaria_resolvida_nome(self, obj):
        # secretaria direta ou via orgao
        if obj.secretaria_id:
            return obj.secretaria.nome
        if obj.orgao_id and obj.orgao.secretaria_id:
            return obj.orgao.secretaria.nome
        return "-"
    secretaria_resolvida_nome.short_description = "Secretaria (resolvida)"

    def prefeitura_resolvida_nome(self, obj):
        # prefeitura direta; ou via secretaria; ou via orgao->secretaria
        if obj.prefeitura_id:
            return obj.prefeitura.nome
        if obj.secretaria_id and obj.secretaria.prefeitura_id:
            return obj.secretaria.prefeitura.nome
        if obj.orgao_id and obj.orgao.secretaria_id and obj.orgao.secretaria.prefeitura_id:
            return obj.orgao.secretaria.prefeitura.nome
        return "-"
    prefeitura_resolvida_nome.short_description = "Prefeitura (resolvida)"

    def chefe_nome(self, obj):
        return obj.chefe.nome if obj.chefe else "-"
    chefe_nome.short_description = "Chefe do setor"


# =========================
# Funcionário
# =========================
@admin.register(Funcionario)
class FuncionarioAdmin(admin.ModelAdmin):
    save_on_top = True

    list_display = (
        "nome", "matricula", "funcao", "cargo",
        "setor",
        "orgao_nome", "secretaria_nome", "prefeitura_nome",
        "turno", "serie", "turma", "tipo_vinculo",
        "is_chefe_setor", "chefe_setor_desde",
    )
    list_filter = (
        "funcao", "cargo", "turno", "serie", "turma",
        "tipo_vinculo",
        "setor",
        "setor__orgao",
        "setor__secretaria",
        "setor__prefeitura",
        "is_chefe_setor",
    )
    search_fields = ("nome", "matricula", "cpf", "rg", "email", "telefone")
    ordering = ("nome",)
    autocomplete_fields = ("setor",)
    inlines = [HorarioTrabalhoInline]
    list_select_related = (
        "setor",
        "setor__orgao",
        "setor__secretaria",
        "setor__prefeitura",
    )
    list_per_page = 25

    fieldsets = (
        ("Identificação", {
            "fields": (("nome", "matricula"), ("cargo", "funcao"))
        }),
        ("Lotação", {
            "fields": (("setor",),)
        }),
        ("Chefia de Setor (flag informativo)", {
            "fields": (("is_chefe_setor", "chefe_setor_desde"),),
            "description": "Use o campo CHEFE no cadastro do Setor para definir a chefia. "
                           "Este flag apenas indica se a pessoa exerce alguma chefia."
        }),
        ("Contato", {
            "fields": (("telefone", "email"),)
        }),
        ("Endereço", {
            "fields": (("endereco", "numero"), ("bairro", "cidade", "uf"), "cep")
        }),
        ("Documentos", {
            "classes": ("collapse",),
            "fields": (("cpf", "rg", "pis"), ("titulo_eleitor",), ("ctps_numero", "ctps_serie"))
        }),
        ("Vínculo", {
            "fields": (("tipo_vinculo", "fonte_pagadora"), ("data_admissao",),)
        }),
        ("Escolaridade", {
            "fields": (("estado_civil", "escolaridade"),)
        }),
        ("Turma / Turno", {
            "fields": (("turno", "serie", "turma"),)
        }),
        ("Planejamento", {
            "fields": (("tem_planejamento", "horario_planejamento"), "sabado_letivo")
        }),
        ("Dados adicionais", {
            "classes": ("collapse",),
            "fields": (("data_nascimento", "inicio_ferias", "fim_ferias"), "foto")
        }),
    )

    actions = ["marcar_como_chefe", "remover_chefe"]

    def marcar_como_chefe(self, request, queryset):
        """
        Define o funcionário selecionado como chefe do SEU setor atual.
        (Não afeta outros setores onde ele possa ser chefe.)
        """
        if queryset.count() != 1:
            self.message_user(
                request,
                "Selecione exatamente 1 funcionário para marcar como chefe.",
                level=messages.ERROR,
            )
            return

        funcionario = queryset.first()
        if not funcionario.setor_id:
            self.message_user(
                request,
                "Funcionário sem setor definido não pode ser chefe.",
                level=messages.ERROR,
            )
            return

        # Seta a chefia via FK no Setor
        setor = funcionario.setor
        if setor.chefe_id != funcionario.id:
            setor.chefe = funcionario
            setor.save(update_fields=["chefe"])

        # Marca o flag informativo
        if not funcionario.is_chefe_setor:
            funcionario.is_chefe_setor = True
        if not funcionario.chefe_setor_desde:
            funcionario.chefe_setor_desde = timezone.localdate()
        funcionario.save(update_fields=["is_chefe_setor", "chefe_setor_desde"])

        self.message_user(request, f"{funcionario.nome} agora é chefe do setor {funcionario.setor}.", level=messages.SUCCESS)

    marcar_como_chefe.short_description = "Definir como chefe do seu setor atual"

    def remover_chefe(self, request, queryset):
        """
        Remove o(s) funcionário(s) como chefe de TODOS os setores onde constam como chefe.
        """
        num_setores = Setor.objects.filter(chefe__in=queryset).update(chefe=None)
        # Flag informativo (opcional): desmarca
        updated = queryset.update(is_chefe_setor=False)
        self.message_user(
            request,
            f"Chefia removida em {num_setores} setor(es); {updated} funcionário(s) sem marcação de chefe.",
            level=messages.SUCCESS
        )

    remover_chefe.short_description = "Remover chefias deste(s) funcionário(s)"

    # helpers
    def orgao_nome(self, obj):
        o = obj.setor.orgao if obj.setor else None
        return o.nome if o else "-"
    orgao_nome.short_description = "Órgão"

    def secretaria_nome(self, obj):
        s = obj.setor.secretaria if obj.setor and obj.setor.secretaria_id else (
            obj.setor.orgao.secretaria if obj.setor and obj.setor.orgao_id and obj.setor.orgao.secretaria_id else None
        )
        return s.nome if s else "-"
    secretaria_nome.short_description = "Secretaria"

    def prefeitura_nome(self, obj):
        p = None
        if obj.setor:
            if obj.setor.prefeitura_id:
                p = obj.setor.prefeitura
            elif obj.setor.secretaria_id and obj.setor.secretaria.prefeitura_id:
                p = obj.setor.secretaria.prefeitura
            elif obj.setor.orgao_id and obj.setor.orgao.secretaria_id and obj.setor.orgao.secretaria.prefeitura_id:
                p = obj.setor.orgao.secretaria.prefeitura
        return p.nome if p else "-"
    prefeitura_nome.short_description = "Prefeitura"


# =========================
# Horário de Trabalho
# =========================
@admin.register(HorarioTrabalho)
class HorarioTrabalhoAdmin(admin.ModelAdmin):
    list_display = (
        "funcionario", "turno", "horario_inicio", "horario_fim",
        "setor_nome", "orgao_nome", "secretaria_nome", "prefeitura_nome",
    )
    list_filter = (
        "turno",
        "funcionario__setor",
        "funcionario__setor__orgao",
        "funcionario__setor__secretaria",
        "funcionario__setor__prefeitura",
    )
    search_fields = ("funcionario__nome", "funcionario__matricula")
    autocomplete_fields = ("funcionario",)
    list_select_related = (
        "funcionario",
        "funcionario__setor",
        "funcionario__setor__orgao",
        "funcionario__setor__secretaria",
        "funcionario__setor__prefeitura",
    )
    ordering = ("funcionario__nome", "turno")
    list_per_page = 25

    def setor_nome(self, obj):
        return obj.funcionario.setor.nome if obj.funcionario and obj.funcionario.setor else "-"
    setor_nome.short_description = "Setor"

    def orgao_nome(self, obj):
        o = obj.funcionario.setor.orgao if obj.funcionario and obj.funcionario.setor else None
        return o.nome if o else "-"
    orgao_nome.short_description = "Órgão"

    def secretaria_nome(self, obj):
        s = None
        if obj.funcionario and obj.funcionario.setor:
            if obj.funcionario.setor.secretaria_id:
                s = obj.funcionario.setor.secretaria
            elif obj.funcionario.setor.orgao_id and obj.funcionario.setor.orgao.secretaria_id:
                s = obj.funcionario.setor.orgao.secretaria
        return s.nome if s else "-"
    secretaria_nome.short_description = "Secretaria"

    def prefeitura_nome(self, obj):
        p = None
        if obj.funcionario and obj.funcionario.setor:
            setor = obj.funcionario.setor
            if setor.prefeitura_id:
                p = setor.prefeitura
            elif setor.secretaria_id and setor.secretaria.prefeitura_id:
                p = setor.secretaria.prefeitura
            elif setor.orgao_id and setor.orgao.secretaria_id and setor.orgao.secretaria.prefeitura_id:
                p = setor.orgao.secretaria.prefeitura
        return p.nome if p else "-"
    prefeitura_nome.short_description = "Prefeitura"


# =========================
# Feriado
# =========================
@admin.register(Feriado)
class FeriadoAdmin(admin.ModelAdmin):
    list_display = ("data", "descricao", "sabado_letivo")
    list_filter = ("sabado_letivo",)
    search_fields = ("descricao",)
    date_hierarchy = "data"
    ordering = ("-data",)
    list_per_page = 25


# =========================
# Sábado Letivo
# =========================
@admin.register(SabadoLetivo)
class SabadoLetivoAdmin(admin.ModelAdmin):
    list_display = ("data", "descricao")
    search_fields = ("descricao",)
    date_hierarchy = "data"
    ordering = ("-data",)
    list_per_page = 25


# =========================
# Folha de Frequência
# =========================
@admin.register(FolhaFrequencia)
class FolhaFrequenciaAdmin(admin.ModelAdmin):
    readonly_fields = ("data_geracao",)
    list_display = (
        "funcionario", "mes", "ano", "data_geracao",
        "setor_nome", "orgao_nome", "secretaria_nome", "prefeitura_nome",
    )
    list_filter = (
        "ano", "mes",
        "funcionario__setor",
        "funcionario__setor__orgao",
        "funcionario__setor__secretaria",
        "funcionario__setor__prefeitura",
    )
    search_fields = ("funcionario__nome", "funcionario__matricula")
    raw_id_fields = ("funcionario",)
    date_hierarchy = "data_geracao"
    list_select_related = (
        "funcionario",
        "funcionario__setor",
        "funcionario__setor__orgao",
        "funcionario__setor__secretaria",
        "funcionario__setor__prefeitura",
    )
    ordering = ("-ano", "-mes", "funcionario__nome")
    list_per_page = 25

    def setor_nome(self, obj):
        return obj.funcionario.setor.nome if obj.funcionario and obj.funcionario.setor else "-"
    setor_nome.short_description = "Setor"
    setor_nome.admin_order_field = "funcionario__setor__nome"

    def orgao_nome(self, obj):
        o = obj.funcionario.setor.orgao if obj.funcionario and obj.funcionario.setor else None
        return o.nome if o else "-"
    orgao_nome.short_description = "Órgão"
    orgao_nome.admin_order_field = "funcionario__setor__orgao__nome"

    def secretaria_nome(self, obj):
        s = None
        if obj.funcionario and obj.funcionario.setor:
            setor = obj.funcionario.setor
            if setor.secretaria_id:
                s = setor.secretaria
            elif setor.orgao_id and setor.orgao.secretaria_id:
                s = setor.orgao.secretaria
        return s.nome if s else "-"
    secretaria_nome.short_description = "Secretaria"
    secretaria_nome.admin_order_field = "funcionario__setor__secretaria__nome"

    def prefeitura_nome(self, obj):
        p = None
        if obj.funcionario and obj.funcionario.setor:
            setor = obj.funcionario.setor
            if setor.prefeitura_id:
                p = setor.prefeitura
            elif setor.secretaria_id and setor.secretaria.prefeitura_id:
                p = setor.secretaria.prefeitura
            elif setor.orgao_id and setor.orgao.secretaria_id and setor.orgao.secretaria.prefeitura_id:
                p = setor.orgao.secretaria.prefeitura
        return p.nome if p else "-"
    prefeitura_nome.short_description = "Prefeitura"
    prefeitura_nome.admin_order_field = "funcionario__setor__prefeitura__nome"


# =========================
# Acessos / Permissões (com ações rápidas)
# =========================
class _AcessoBaseAdmin(admin.ModelAdmin):
    actions = ["action_set_leitura", "action_set_gerencia"]

    def action_set_leitura(self, request, queryset):
        updated = queryset.update(nivel=NivelAcesso.LEITURA)
        self.message_user(request, f"Nível alterado para LEITURA em {updated} registro(s).", level=messages.SUCCESS)

    def action_set_gerencia(self, request, queryset):
        updated = queryset.update(nivel=NivelAcesso.GERENCIA)
        self.message_user(request, f"Nível alterado para GERÊNCIA em {updated} registro(s).", level=messages.SUCCESS)


@admin.register(AcessoPrefeitura)
class AcessoPrefeituraAdmin(_AcessoBaseAdmin):
    list_display = ("user", "prefeitura", "nivel")
    list_filter = ("nivel", "prefeitura")
    search_fields = ("user__username", "user__email", "prefeitura__nome")
    autocomplete_fields = ("user", "prefeitura")
    list_select_related = ("prefeitura",)
    ordering = ("prefeitura__nome", "user__username")
    list_per_page = 25


@admin.register(AcessoSecretaria)
class AcessoSecretariaAdmin(_AcessoBaseAdmin):
    list_display = ("user", "secretaria", "nivel")
    list_filter = ("nivel", "secretaria", "secretaria__prefeitura")
    search_fields = ("user__username", "user__email", "secretaria__nome", "secretaria__prefeitura__nome")
    autocomplete_fields = ("user", "secretaria")
    list_select_related = ("secretaria", "secretaria__prefeitura")
    ordering = ("secretaria__prefeitura__nome", "secretaria__nome", "user__username")
    list_per_page = 25


@admin.register(AcessoOrgao)
class AcessoOrgaoAdmin(_AcessoBaseAdmin):
    list_display = ("user", "orgao", "nivel", "secretaria_nome", "prefeitura_nome")
    list_filter = ("nivel", "orgao", "orgao__secretaria", "orgao__secretaria__prefeitura")
    search_fields = ("user__username", "user__email", "orgao__nome", "orgao__secretaria__nome", "orgao__secretaria__prefeitura__nome")
    autocomplete_fields = ("user", "orgao")
    list_select_related = ("orgao", "orgao__secretaria", "orgao__secretaria__prefeitura")
    ordering = ("orgao__secretaria__prefeitura__nome", "orgao__secretaria__nome", "orgao__nome", "user__username")
    list_per_page = 25

    def secretaria_nome(self, obj):
        s = obj.orgao.secretaria if obj.orgao else None
        return s.nome if s else "-"
    secretaria_nome.short_description = "Secretaria"

    def prefeitura_nome(self, obj):
        p = obj.orgao.secretaria.prefeitura if obj.orgao and obj.orgao.secretaria else None
        return p.nome if p else "-"
    prefeitura_nome.short_description = "Prefeitura"


@admin.register(AcessoSetor)
class AcessoSetorAdmin(_AcessoBaseAdmin):
    list_display = ("user", "setor", "nivel", "orgao_nome", "secretaria_nome", "prefeitura_nome")
    list_filter = (
        "nivel",
        "setor",
        "setor__orgao",
        "setor__secretaria",
        "setor__prefeitura",
    )
    search_fields = (
        "user__username", "user__email",
        "setor__nome",
        "setor__orgao__nome",
        "setor__secretaria__nome",
        "setor__prefeitura__nome",
    )
    autocomplete_fields = ("user", "setor")
    list_select_related = (
        "setor",
        "setor__orgao",
        "setor__secretaria",
        "setor__prefeitura",
    )
    ordering = ("setor__prefeitura__nome", "setor__secretaria__nome", "setor__orgao__nome", "setor__nome", "user__username")
    list_per_page = 25

    def orgao_nome(self, obj):
        o = obj.setor.orgao if obj.setor else None
        return o.nome if o else "-"
    orgao_nome.short_description = "Órgão"

    def secretaria_nome(self, obj):
        if not obj.setor:
            return "-"
        if obj.setor.secretaria_id:
            return obj.setor.secretaria.nome
        if obj.setor.orgao_id and obj.setor.orgao.secretaria_id:
            return obj.setor.orgao.secretaria.nome
        return "-"
    secretaria_nome.short_description = "Secretaria"

    def prefeitura_nome(self, obj):
        if not obj.setor:
            return "-"
        if obj.setor.prefeitura_id:
            return obj.setor.prefeitura.nome
        if obj.setor.secretaria_id and obj.setor.secretaria.prefeitura_id:
            return obj.setor.secretaria.prefeitura.nome
        if obj.setor.orgao_id and obj.setor.orgao.secretaria_id and obj.setor.orgao.secretaria.prefeitura_id:
            return obj.setor.orgao.secretaria.prefeitura.nome
        return "-"
    prefeitura_nome.short_description = "Prefeitura"


# =========================
# User Admin (inlines + ações em massa)
# =========================
User = get_user_model()
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [AcessoPrefeituraInline, AcessoSecretariaInline, AcessoOrgaoInline, AcessoSetorInline]
    actions = ["conceder_acesso_bulk", "revogar_acesso_bulk"]

    def conceder_acesso_bulk(self, request, queryset):
        if "apply" in request.POST:
            form = ConcederAcessoForm(request.POST)
            if form.is_valid():
                escopo = form.cleaned_data["escopo"]
                nivel = form.cleaned_data["nivel"]

                created = 0
                updated = 0

                for user in queryset:
                    if escopo == "prefeitura":
                        obj = form.cleaned_data["prefeitura"]
                        acc, was_created = AcessoPrefeitura.objects.get_or_create(user=user, prefeitura=obj, defaults={"nivel": nivel})
                    elif escopo == "secretaria":
                        obj = form.cleaned_data["secretaria"]
                        acc, was_created = AcessoSecretaria.objects.get_or_create(user=user, secretaria=obj, defaults={"nivel": nivel})
                    elif escopo == "orgao":
                        obj = form.cleaned_data["orgao"]
                        acc, was_created = AcessoOrgao.objects.get_or_create(user=user, orgao=obj, defaults={"nivel": nivel})
                    elif escopo == "setor":
                        obj = form.cleaned_data["setor"]
                        acc, was_created = AcessoSetor.objects.get_or_create(user=user, setor=obj, defaults={"nivel": nivel})
                    else:
                        continue

                    if not was_created and acc.nivel != nivel:
                        acc.nivel = nivel
                        acc.save(update_fields=["nivel"])
                        updated += 1
                    else:
                        created += 1 if was_created else 0

                self.message_user(
                    request,
                    f"Acessos: {created} criado(s), {updated} atualizado(s).",
                    level=messages.SUCCESS
                )
                return None
        else:
            form = ConcederAcessoForm()

        context = {
            "title": "Conceder acesso (em massa)",
            "users": queryset,
            "form": form,
            "action": "conceder_acesso_bulk",
        }
        return render(request, "admin/conceder_acesso.html", context)

    conceder_acesso_bulk.short_description = "Conceder acesso…"

    def revogar_acesso_bulk(self, request, queryset):
        if "apply" in request.POST:
            form = RevogarAcessoForm(request.POST)
            if form.is_valid():
                escopo = form.cleaned_data["escopo"]
                total = 0

                if escopo == "prefeitura":
                    obj = form.cleaned_data["prefeitura"]
                    total = AcessoPrefeitura.objects.filter(user__in=queryset, prefeitura=obj).delete()[0]
                elif escopo == "secretaria":
                    obj = form.cleaned_data["secretaria"]
                    total = AcessoSecretaria.objects.filter(user__in=queryset, secretaria=obj).delete()[0]
                elif escopo == "orgao":
                    obj = form.cleaned_data["orgao"]
                    total = AcessoOrgao.objects.filter(user__in=queryset, orgao=obj).delete()[0]
                elif escopo == "setor":
                    obj = form.cleaned_data["setor"]
                    total = AcessoSetor.objects.filter(user__in=queryset, setor=obj).delete()[0]

                self.message_user(request, f"Acessos revogados: {total}.", level=messages.SUCCESS)
                return None
        else:
            form = RevogarAcessoForm()

        context = {
            "title": "Revogar acesso (em massa)",
            "users": queryset,
            "form": form,
            "action": "revogar_acesso_bulk",
        }
        return render(request, "admin/revogar_acesso.html", context)

    revogar_acesso_bulk.short_description = "Revogar acesso…"


# =========================
# UserScope
# =========================
@admin.register(UserScope)
class UserScopeAdmin(admin.ModelAdmin):
    list_display = ("user", "alvo_tipo", "alvo_nome", "nivel")
    list_filter = ("nivel", "prefeitura", "secretaria", "orgao", "setor")
    search_fields = (
        "user__username", "user__email",
        "prefeitura__nome", "secretaria__nome",
        "orgao__nome", "setor__nome",
    )
    autocomplete_fields = ("user", "prefeitura", "secretaria", "orgao", "setor")
    ordering = ("user__username",)

    def alvo_tipo(self, obj):
        return obj.alvo_tipo()
    alvo_tipo.short_description = "Nível"

    def alvo_nome(self, obj):
        return obj.alvo_nome()
    alvo_nome.short_description = "Alvo"


# =========================
# FuncaoPermissao
# =========================
@admin.register(FuncaoPermissao)
class FuncaoPermissaoAdmin(admin.ModelAdmin):
    list_display = ("user", "nome_funcao", "nivel", "secretaria", "orgao", "setor")
    list_filter = ("nivel", "secretaria", "orgao", "setor")
    search_fields = ("user__username", "user__first_name", "user__last_name", "nome_funcao")
    autocomplete_fields = ("user", "secretaria", "orgao", "setor")
    ordering = ("user__username", "nome_funcao")
