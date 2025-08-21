# controle/admin_forms.py
from django import forms
from .models import (
    Prefeitura, Secretaria, Orgao, Setor, NivelAcesso
)

ESCOPO_CHOICES = [
    ("prefeitura", "Prefeitura"),
    ("secretaria", "Secretaria"),
    ("escola", "Órgão / Unidade"),   # mantém a CHAVE "escola" para compatibilidade dos posts
    ("setor", "Setor"),
]


class ConcederAcessoForm(forms.Form):
    escopo = forms.ChoiceField(choices=ESCOPO_CHOICES, label="Escopo")
    nivel = forms.ChoiceField(choices=NivelAcesso.choices, label="Nível de acesso")

    prefeitura = forms.ModelChoiceField(
        queryset=Prefeitura.objects.all(), required=False, label="Prefeitura"
    )
    secretaria = forms.ModelChoiceField(
        queryset=Secretaria.objects.select_related("prefeitura"),
        required=False, label="Secretaria"
    )
    # Campo segue se chamando "escola" por compatibilidade, mas é Orgao
    escola = forms.ModelChoiceField(
        queryset=Orgao.objects.select_related("secretaria", "secretaria__prefeitura"),
        required=False, label="Órgão/Unidade"
    )
    setor = forms.ModelChoiceField(
        queryset=Setor.objects.select_related("orgao", "secretaria", "secretaria__prefeitura").order_by("nome"),
        required=False, label="Setor",
    )

    def clean(self):
        cleaned = super().clean()
        escopo = cleaned.get("escopo")
        need = {
            "prefeitura": "prefeitura",
            "secretaria": "secretaria",
            "escola": "escola",   # continua "escola" (mas é Orgao)
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
        queryset=Secretaria.objects.select_related("prefeitura"),
        required=False, label="Secretaria"
    )
    # idem: campo "escola" aponta para Orgao
    escola = forms.ModelChoiceField(
        queryset=Orgao.objects.select_related("secretaria", "secretaria__prefeitura"),
        required=False, label="Órgão/Unidade"
    )
    setor = forms.ModelChoiceField(
        queryset=Setor.objects.select_related("orgao", "secretaria", "secretaria__prefeitura").order_by("nome"),
        required=False, label="Setor",
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
