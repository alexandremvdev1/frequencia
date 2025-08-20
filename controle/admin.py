# controle/admin.py
from django import forms
from django.contrib import admin, messages
from django.shortcuts import render
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils import timezone

from .models import (
    Prefeitura, Secretaria, Escola, Departamento, Setor, Funcionario,
    HorarioTrabalho, Feriado, FolhaFrequencia, SabadoLetivo,
    AcessoPrefeitura, AcessoSecretaria, AcessoEscola, AcessoSetor, NivelAcesso,
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


class AcessoEscolaInline(admin.TabularInline):
    model = AcessoEscola
    extra = 0
    fields = ("escola", "nivel")
    autocomplete_fields = ("escola",)


class AcessoSetorInline(admin.TabularInline):
    model = AcessoSetor
    extra = 0
    fields = ("setor", "nivel")
    autocomplete_fields = ("setor",)


# =========================
# Prefeitura / Secretaria / Escola
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


@admin.register(Escola)
class EscolaAdmin(admin.ModelAdmin):
    list_display = ("nome_escola", "nome_secretaria", "cidade", "uf", "secretaria")
    list_filter = ("cidade", "uf", "secretaria")
    search_fields = ("nome_escola", "nome_secretaria", "cnpj", "secretaria__nome")
    ordering = ("nome_escola",)
    autocomplete_fields = ("secretaria",)
    list_select_related = ("secretaria",)
    list_per_page = 25


# =========================
# Departamento
# =========================
@admin.register(Departamento)
class DepartamentoAdmin(admin.ModelAdmin):
    list_display = ("nome", "tipo", "pai_tipo", "pai_nome")
    list_filter = ("tipo", "prefeitura", "secretaria", "escola")
    search_fields = (
        "nome",
        "prefeitura__nome",
        "secretaria__nome",
        "escola__nome_escola",
    )
    ordering = ("nome",)
    autocomplete_fields = ("prefeitura", "secretaria", "escola")
    list_select_related = ("prefeitura", "secretaria", "escola")
    list_per_page = 25

    def pai_tipo(self, obj):
        if obj.prefeitura_id: return "Prefeitura"
        if obj.secretaria_id: return "Secretaria"
        if obj.escola_id: return "Escola"
        return "-"
    pai_tipo.short_description = "Nível"

    def pai_nome(self, obj):
        if obj.prefeitura_id: return obj.prefeitura.nome
        if obj.secretaria_id: return obj.secretaria.nome
        if obj.escola_id: return obj.escola.nome_escola
        return "-"
    pai_nome.short_description = "Vinculado a"


# =========================
# Setor (com escolha de Chefe)
# =========================
class SetorAdminForm(forms.ModelForm):
    chefe = forms.ModelChoiceField(
        label="Chefe do setor",
        required=False,
        queryset=Funcionario.objects.none(),
        help_text="Selecione o servidor que será a chefia imediata deste setor.",
    )

    class Meta:
        model = Setor
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        inst = self.instance
        if inst and inst.pk:
            qs = Funcionario.objects.filter(setor=inst).order_by("nome")
            self.fields["chefe"].queryset = qs
            atual = qs.filter(is_chefe_setor=True).first()
            if atual:
                self.initial["chefe"] = atual.pk
        else:
            self.fields["chefe"].queryset = Funcionario.objects.none()


@admin.register(Setor)
class SetorAdmin(admin.ModelAdmin):
    form = SetorAdminForm

    list_display = (
        "nome",
        "departamento",
        "secretaria_legado",
        "escola_nome",
        "secretaria_oficial_nome",
        "prefeitura_nome",
        "chefe_nome",
    )
    list_filter = (
        "departamento",
        "departamento__escola",
        "departamento__secretaria",
        "departamento__prefeitura",
        "secretaria",  # legado
    )
    search_fields = (
        "nome",
        "departamento__nome",
        "departamento__escola__nome_escola",
        "departamento__secretaria__nome",
        "departamento__prefeitura__nome",
        "secretaria__nome",
    )
    ordering = ("departamento__nome", "nome")
    autocomplete_fields = ("departamento", "secretaria")
    list_select_related = (
        "departamento",
        "departamento__escola",
        "departamento__secretaria",
        "departamento__prefeitura",
        "secretaria",
    )
    list_per_page = 25

    fieldsets = (
        (None, {"fields": ("nome",)}),
        ("Vinculação", {"fields": ("departamento", "secretaria")}),
        ("Chefia", {"fields": ("chefe",)}),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        chefe = form.cleaned_data.get("chefe")
        if chefe:
            if chefe.setor_id != obj.pk:
                chefe.setor = obj

            Funcionario.objects.filter(setor=obj).exclude(pk=chefe.pk).update(is_chefe_setor=False)

            if not chefe.chefe_setor_desde:
                chefe.chefe_setor_desde = timezone.localdate()
            chefe.is_chefe_setor = True
            chefe.save(update_fields=["setor", "is_chefe_setor", "chefe_setor_desde"])

    # helpers
    def secretaria_legado(self, obj):
        return obj.secretaria or "-"
    secretaria_legado.short_description = "Secretaria (legado)"

    def escola_nome(self, obj):
        return obj.escola.nome_escola if obj.escola else "-"
    escola_nome.short_description = "Escola"

    def secretaria_oficial_nome(self, obj):
        s = obj.secretaria_oficial
        return s.nome if s else "-"
    secretaria_oficial_nome.short_description = "Secretaria (oficial)"

    def prefeitura_nome(self, obj):
        p = obj.prefeitura
        return p.nome if p else "-"
    prefeitura_nome.short_description = "Prefeitura"

    def chefe_nome(self, obj):
        chefe = (Funcionario.objects
                 .filter(setor=obj, is_chefe_setor=True)
                 .order_by('chefe_setor_desde', 'id')
                 .first())
        return chefe.nome if chefe else "-"
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
        "departamento_nome", "escola_nome", "secretaria_nome", "prefeitura_nome",
        "turno", "serie", "turma", "tipo_vinculo",
        "is_chefe_setor", "chefe_setor_desde",
    )
    list_filter = (
        "funcao", "cargo", "turno", "serie", "turma",
        "tipo_vinculo",
        "setor",
        "setor__departamento",
        "setor__departamento__escola",
        "setor__departamento__secretaria",
        "setor__departamento__prefeitura",
        "setor__secretaria",  # legado
        "is_chefe_setor",
    )
    search_fields = ("nome", "matricula", "cpf", "rg", "email", "telefone")
    ordering = ("nome",)
    autocomplete_fields = ("setor",)
    inlines = [HorarioTrabalhoInline]
    list_select_related = (
        "setor",
        "setor__departamento",
        "setor__departamento__escola",
        "setor__departamento__secretaria",
        "setor__departamento__prefeitura",
        "setor__secretaria",
    )
    list_per_page = 25

    fieldsets = (
        ("Identificação", {
            "fields": (("nome", "matricula"), ("cargo", "funcao"))
        }),
        ("Lotação", {
            "fields": (("setor",),)
        }),
        ("Chefia de Setor", {
            "fields": (("is_chefe_setor", "chefe_setor_desde"),),
            "description": "Marque se este funcionário é o chefe do setor. O sistema garante apenas um chefe por setor."
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

        Funcionario.objects.filter(setor=funcionario.setor).exclude(pk=funcionario.pk).update(is_chefe_setor=False)

        funcionario.is_chefe_setor = True
        if not funcionario.chefe_setor_desde:
            funcionario.chefe_setor_desde = timezone.localdate()
        funcionario.save(update_fields=["is_chefe_setor", "chefe_setor_desde"])

        self.message_user(request, f"{funcionario.nome} marcado como chefe do setor {funcionario.setor}.", level=messages.SUCCESS)

    marcar_como_chefe.short_description = "Marcar como chefe do setor"

    def remover_chefe(self, request, queryset):
        updated = queryset.update(is_chefe_setor=False)
        self.message_user(request, f"{updated} funcionário(s) deixaram de ser chefes.", level=messages.SUCCESS)

    remover_chefe.short_description = "Remover marcação de chefe"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        if obj.is_chefe_setor and obj.setor_id:
            Funcionario.objects.filter(setor=obj.setor).exclude(pk=obj.pk).update(is_chefe_setor=False)
            if not obj.chefe_setor_desde:
                obj.chefe_setor_desde = timezone.localdate()
                obj.save(update_fields=["chefe_setor_desde"])

    # helpers
    def departamento_nome(self, obj):
        return obj.departamento.nome if obj.departamento else "-"
    departamento_nome.short_description = "Departamento"

    def escola_nome(self, obj):
        return obj.escola.nome_escola if obj.escola else "-"
    escola_nome.short_description = "Escola"

    def secretaria_nome(self, obj):
        return obj.secretaria.nome if obj.secretaria else "-"
    secretaria_nome.short_description = "Secretaria"

    def prefeitura_nome(self, obj):
        return obj.prefeitura.nome if obj.prefeitura else "-"
    prefeitura_nome.short_description = "Prefeitura"


# =========================
# Horário de Trabalho
# =========================
@admin.register(HorarioTrabalho)
class HorarioTrabalhoAdmin(admin.ModelAdmin):
    list_display = (
        "funcionario", "turno", "horario_inicio", "horario_fim",
        "setor_nome", "departamento_nome", "escola_nome", "secretaria_nome", "prefeitura_nome",
    )
    list_filter = (
        "turno",
        "funcionario__setor",
        "funcionario__setor__departamento",
        "funcionario__setor__departamento__escola",
        "funcionario__setor__departamento__secretaria",
        "funcionario__setor__departamento__prefeitura",
        "funcionario__setor__secretaria",  # legado
    )
    search_fields = ("funcionario__nome", "funcionario__matricula")
    autocomplete_fields = ("funcionario",)
    list_select_related = (
        "funcionario",
        "funcionario__setor",
        "funcionario__setor__departamento",
        "funcionario__setor__departamento__escola",
        "funcionario__setor__departamento__secretaria",
        "funcionario__setor__departamento__prefeitura",
        "funcionario__setor__secretaria",
    )
    ordering = ("funcionario__nome", "turno")
    list_per_page = 25

    def setor_nome(self, obj):
        return obj.funcionario.setor.nome if obj.funcionario and obj.funcionario.setor else "-"
    setor_nome.short_description = "Setor"

    def departamento_nome(self, obj):
        d = obj.funcionario.departamento if obj.funcionario else None
        return d.nome if d else "-"
    departamento_nome.short_description = "Departamento"

    def escola_nome(self, obj):
        e = obj.funcionario.escola if obj.funcionario else None
        return e.nome_escola if e else "-"
    escola_nome.short_description = "Escola"

    def secretaria_nome(self, obj):
        s = obj.funcionario.secretaria if obj.funcionario else None
        return s.nome if s else "-"
    secretaria_nome.short_description = "Secretaria"

    def prefeitura_nome(self, obj):
        p = obj.funcionario.prefeitura if obj.funcionario else None
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
        "setor_nome", "departamento_nome", "escola_nome", "secretaria_nome", "prefeitura_nome",
    )
    list_filter = (
        "ano", "mes",
        "funcionario__setor",
        "funcionario__setor__departamento",
        "funcionario__setor__departamento__escola",
        "funcionario__setor__departamento__secretaria",
        "funcionario__setor__departamento__prefeitura",
        "funcionario__setor__secretaria",  # legado
    )
    search_fields = ("funcionario__nome", "funcionario__matricula")
    raw_id_fields = ("funcionario",)
    date_hierarchy = "data_geracao"
    list_select_related = (
        "funcionario",
        "funcionario__setor",
        "funcionario__setor__departamento",
        "funcionario__setor__departamento__escola",
        "funcionario__setor__departamento__secretaria",
        "funcionario__setor__departamento__prefeitura",
        "funcionario__setor__secretaria",
    )
    ordering = ("-ano", "-mes", "funcionario__nome")
    list_per_page = 25

    def setor_nome(self, obj):
        return obj.funcionario.setor.nome if obj.funcionario and obj.funcionario.setor else "-"
    setor_nome.short_description = "Setor"
    setor_nome.admin_order_field = "funcionario__setor__nome"

    def departamento_nome(self, obj):
        d = obj.funcionario.departamento if obj.funcionario else None
        return d.nome if d else "-"
    departamento_nome.short_description = "Departamento"
    departamento_nome.admin_order_field = "funcionario__setor__departamento__nome"

    def escola_nome(self, obj):
        e = obj.funcionario.escola if obj.funcionario else None
        return e.nome_escola if e else "-"
    escola_nome.short_description = "Escola"
    escola_nome.admin_order_field = "funcionario__setor__departamento__escola__nome_escola"

    def secretaria_nome(self, obj):
        s = obj.funcionario.secretaria if obj.funcionario else None
        return s.nome if s else "-"
    secretaria_nome.short_description = "Secretaria"
    secretaria_nome.admin_order_field = "funcionario__setor__departamento__secretaria__nome"

    def prefeitura_nome(self, obj):
        p = obj.funcionario.prefeitura if obj.funcionario else None
        return p.nome if p else "-"
    prefeitura_nome.short_description = "Prefeitura"
    prefeitura_nome.admin_order_field = "funcionario__setor__departamento__secretaria__prefeitura__nome"


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


@admin.register(AcessoEscola)
class AcessoEscolaAdmin(_AcessoBaseAdmin):
    list_display = ("user", "escola", "nivel", "prefeitura_nome", "secretaria_nome")
    list_filter = ("nivel", "escola", "escola__secretaria", "escola__secretaria__prefeitura")
    search_fields = ("user__username", "user__email", "escola__nome_escola", "escola__secretaria__nome", "escola__secretaria__prefeitura__nome")
    autocomplete_fields = ("user", "escola")
    list_select_related = ("escola", "escola__secretaria", "escola__secretaria__prefeitura")
    ordering = ("escola__secretaria__prefeitura__nome", "escola__secretaria__nome", "escola__nome_escola", "user__username")
    list_per_page = 25

    def prefeitura_nome(self, obj):
        p = obj.escola.secretaria.prefeitura if obj.escola and obj.escola.secretaria else None
        return p.nome if p else "-"
    prefeitura_nome.short_description = "Prefeitura"

    def secretaria_nome(self, obj):
        s = obj.escola.secretaria if obj.escola else None
        return s.nome if s else "-"
    secretaria_nome.short_description = "Secretaria"


@admin.register(AcessoSetor)
class AcessoSetorAdmin(_AcessoBaseAdmin):
    list_display = ("user", "setor", "nivel", "departamento_nome", "escola_nome", "secretaria_nome", "prefeitura_nome")
    list_filter = (
        "nivel",
        "setor",
        "setor__departamento",
        "setor__departamento__escola",
        "setor__departamento__secretaria",
        "setor__departamento__prefeitura",
        "setor__secretaria",  # legado
    )
    search_fields = (
        "user__username", "user__email",
        "setor__nome",
        "setor__departamento__nome",
        "setor__departamento__escola__nome_escola",
        "setor__departamento__secretaria__nome",
        "setor__departamento__prefeitura__nome",
        "setor__secretaria__nome",
    )
    autocomplete_fields = ("user", "setor")
    list_select_related = (
        "setor",
        "setor__departamento",
        "setor__departamento__escola",
        "setor__departamento__secretaria",
        "setor__departamento__prefeitura",
        "setor__secretaria",
    )
    ordering = ("setor__departamento__secretaria__prefeitura__nome", "setor__departamento__secretaria__nome", "setor__departamento__escola__nome_escola", "setor__nome", "user__username")
    list_per_page = 25

    def departamento_nome(self, obj):
        d = obj.setor.departamento if obj.setor else None
        return d.nome if d else "-"
    departamento_nome.short_description = "Departamento"

    def escola_nome(self, obj):
        e = obj.setor.escola if obj.setor else None
        return e.nome_escola if e else "-"
    escola_nome.short_description = "Escola"

    def secretaria_nome(self, obj):
        s = obj.setor.secretaria_oficial if obj.setor else None
        return s.nome if s else "-"
    secretaria_nome.short_description = "Secretaria"

    def prefeitura_nome(self, obj):
        p = obj.setor.prefeitura if obj.setor else None
        return p.nome if p else "-"
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
    inlines = [AcessoPrefeituraInline, AcessoSecretariaInline, AcessoEscolaInline, AcessoSetorInline]
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
                        if not was_created and acc.nivel != nivel:
                            acc.nivel = nivel
                            acc.save(update_fields=["nivel"])
                            updated += 1
                        else:
                            created += 1 if was_created else 0

                    elif escopo == "secretaria":
                        obj = form.cleaned_data["secretaria"]
                        acc, was_created = AcessoSecretaria.objects.get_or_create(user=user, secretaria=obj, defaults={"nivel": nivel})
                        if not was_created and acc.nivel != nivel:
                            acc.nivel = nivel
                            acc.save(update_fields=["nivel"])
                            updated += 1
                        else:
                            created += 1 if was_created else 0

                    elif escopo == "escola":
                        obj = form.cleaned_data["escola"]
                        acc, was_created = AcessoEscola.objects.get_or_create(user=user, escola=obj, defaults={"nivel": nivel})
                        if not was_created and acc.nivel != nivel:
                            acc.nivel = nivel
                            acc.save(update_fields=["nivel"])
                            updated += 1
                        else:
                            created += 1 if was_created else 0

                    elif escopo == "setor":
                        obj = form.cleaned_data["setor"]
                        acc, was_created = AcessoSetor.objects.get_or_create(user=user, setor=obj, defaults={"nivel": nivel})
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
                elif escopo == "escola":
                    obj = form.cleaned_data["escola"]
                    total = AcessoEscola.objects.filter(user__in=queryset, escola=obj).delete()[0]
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
    list_filter = ("nivel", "prefeitura", "secretaria", "escola", "departamento", "setor")
    search_fields = (
        "user__username", "user__email",
        "prefeitura__nome", "secretaria__nome",
        "escola__nome_escola", "departamento__nome", "setor__nome",
    )
    autocomplete_fields = ("user", "prefeitura", "secretaria", "escola", "departamento", "setor")
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
    list_display = ("user", "nome_funcao", "nivel", "secretaria", "setor")
    list_filter = ("nivel", "secretaria", "setor")
    search_fields = ("user__username", "user__first_name", "user__last_name", "nome_funcao")
    autocomplete_fields = ("user", "secretaria", "setor")
    ordering = ("user__username", "nome_funcao")
