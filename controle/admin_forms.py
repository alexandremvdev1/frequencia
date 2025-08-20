# controle/admin_forms.py
from django import forms
from .models import (
    Prefeitura, Secretaria, Escola, Setor, NivelAcesso
)

ESCOPO_CHOICES = [
    ("prefeitura", "Prefeitura"),
    ("secretaria", "Secretaria"),
    ("escola", "Escola / Unidade"),
    ("setor", "Setor"),
]


class ConcederAcessoForm(forms.Form):
    escopo = forms.ChoiceField(choices=ESCOPO_CHOICES, label="Escopo")
    nivel = forms.ChoiceField(choices=NivelAcesso.choices, label="Nível de acesso")

    prefeitura = forms.ModelChoiceField(
        queryset=Prefeitura.objects.all(), required=False, label="Prefeitura"
    )
    secretaria = forms.ModelChoiceField(
        queryset=Secretaria.objects.select_related("prefeitura"), required=False, label="Secretaria"
    )
    escola = forms.ModelChoiceField(
        queryset=Escola.objects.select_related("secretaria__prefeitura"), required=False, label="Escola/Unidade"
    )
    setor = forms.ModelChoiceField(
        queryset=Setor.objects.select_related(
            "departamento",
            "departamento__escola",
            "departamento__secretaria",
            "departamento__prefeitura",
            "secretaria",
        ),
        required=False,
        label="Setor",
    )

    def clean(self):
        cleaned = super().clean()
        escopo = cleaned.get("escopo")
        # Exige exatamente um alvo de acordo com o escopo
        need = {
            "prefeitura": "prefeitura",
            "secretaria": "secretaria",
            "escola": "escola",
            "setor": "setor",
        }[escopo]
        if not cleaned.get(need):
            self.add_error(need, f"Selecione a/o {need}.")
        return cleaned


class RevogarAcessoForm(forms.Form):
    escopo = forms.ChoiceField(choices=ESCOPO_CHOICES, label="Escopo")

    prefeitura = forms.ModelChoiceField(
        queryset=Prefeitura.objects.all(), required=False, label="Prefeitura"
    )
    secretaria = forms.ModelChoiceField(
        queryset=Secretaria.objects.select_related("prefeitura"), required=False, label="Secretaria"
    )
    escola = forms.ModelChoiceField(
        queryset=Escola.objects.select_related("secretaria__prefeitura"), required=False, label="Escola/Unidade"
    )
    setor = forms.ModelChoiceField(
        queryset=Setor.objects.select_related(
            "departamento",
            "departamento__escola",
            "departamento__secretaria",
            "departamento__prefeitura",
            "secretaria",
        ),
        required=False,
        label="Setor",
    )

    def clean(self):
        cleaned = super().clean()
        escopo = cleaned.get("escopo")
        need = {
            "prefeitura": "prefeitura",
            "secretaria": "secretaria",
            "escola": "escola",
            "setor": "setor",
        }[escopo]
        if not cleaned.get(need):
            self.add_error(need, f"Selecione a/o {need}.")
        return cleaned
