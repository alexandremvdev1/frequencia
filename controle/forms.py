# controle/forms.py
from __future__ import annotations

from datetime import date
from django import forms

from .models import (
    Funcionario, HorarioTrabalho, Feriado,
    RecessoFuncionario, Setor
)
from .permissions import (
    filter_setores_by_scope, filter_funcionarios_by_scope
)

# ---------------------------
# Funcionario
# ---------------------------
class FuncionarioForm(forms.ModelForm):
    class Meta:
        model = Funcionario
        fields = [
            'nome', 'matricula', 'cargo', 'funcao', 'setor',
            'turno', 'turma', 'data_admissao', 'data_nascimento',
            'cpf', 'rg', 'pis', 'titulo_eleitor',
            'ctps_numero', 'ctps_serie',
            'telefone', 'email',
            'endereco', 'numero', 'bairro', 'cidade', 'uf', 'cep',
            'estado_civil', 'escolaridade',
            'tem_planejamento', 'horario_planejamento', 'sabado_letivo',
            'foto',
        ]
        widgets = {
            'data_admissao': forms.TextInput(attrs={
                'placeholder': 'dd/mm/aaaa', 'class': 'data-input',
                'autocomplete': 'off', 'data-mask': 'date',
            }),
            'data_nascimento': forms.TextInput(attrs={
                'placeholder': 'dd/mm/aaaa', 'class': 'data-input',
                'autocomplete': 'off', 'data-mask': 'date',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # aceitar dd/mm/aaaa
        self.fields['data_admissao'].input_formats = ['%d/%m/%Y']
        self.fields['data_nascimento'].input_formats = ['%d/%m/%Y']

        # exibir formatado ao editar
        if self.instance and self.instance.pk:
            if self.instance.data_admissao:
                self.initial['data_admissao'] = self.instance.data_admissao.strftime('%d/%m/%Y')
            if self.instance.data_nascimento:
                self.initial['data_nascimento'] = self.instance.data_nascimento.strftime('%d/%m/%Y')

        # obrigatoriedade condicional
        self.fields['horario_planejamento'].required = False
        if self.instance and self.instance.tem_planejamento:
            self.fields['horario_planejamento'].required = True


# ---------------------------
# Horário de trabalho
# ---------------------------
class HorarioTrabalhoForm(forms.ModelForm):
    class Meta:
        model = HorarioTrabalho
        fields = ['funcionario', 'turno', 'horario_inicio', 'horario_fim']
        widgets = {
            'horario_inicio': forms.TimeInput(attrs={'type': 'time'}),
            'horario_fim': forms.TimeInput(attrs={'type': 'time'}),
        }


# ---------------------------
# Feriado
# ---------------------------
class FeriadoForm(forms.ModelForm):
    class Meta:
        model = Feriado
        fields = ['data', 'descricao', 'sabado_letivo']
        widgets = {
            'data': forms.DateInput(attrs={'type': 'date'}),
            'sabado_letivo': forms.CheckboxInput(attrs={'class': 'checkbox-input'}),
        }


# ---------------------------
# Importação simples
# ---------------------------
class ImportacaoFuncionarioForm(forms.Form):
    excel_file = forms.FileField(label='Arquivo Excel', required=True)


# ---------------------------
# Folhas individuais (multi-meses)
# ---------------------------
MESES_CHOICES = [
    (1, 'Janeiro'), (2, 'Fevereiro'), (3, 'Março'), (4, 'Abril'),
    (5, 'Maio'), (6, 'Junho'), (7, 'Julho'), (8, 'Agosto'),
    (9, 'Setembro'), (10, 'Outubro'), (11, 'Novembro'), (12, 'Dezembro'),
]

class GerarFolhasIndividuaisForm(forms.Form):
    funcionario = forms.ModelChoiceField(
        queryset=Funcionario.objects.all(), label="Funcionário"
    )
    ano = forms.IntegerField(label="Ano", initial=date.today().year)
    meses = forms.MultipleChoiceField(
        choices=MESES_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        label="Meses"
    )
    # (opcional) se quiser filtrar por escopo, inicialize com user=...
    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["funcionario"].queryset = filter_funcionarios_by_scope(
                Funcionario.objects.all(), user
            ).order_by("nome")


# ---------------------------
# Recessos em lote
# ---------------------------
class RecessoBulkForm(forms.Form):
    setor = forms.ModelChoiceField(queryset=Setor.objects.all(), label="Setor")
    funcionarios = forms.ModelMultipleChoiceField(
        queryset=Funcionario.objects.none(),
        label="Funcionários",
        help_text="Selecione um ou mais."
    )
    data_inicio = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    data_fim = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    motivo = forms.CharField(max_length=120, required=False)

    def __init__(self, *args, **kwargs):
        setor_id = kwargs.pop('setor_id', None)
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # filtra setores por escopo (se user fornecido)
        if user is not None:
            self.fields['setor'].queryset = filter_setores_by_scope(
                Setor.objects.all(), user
            ).order_by('nome')

        if setor_id:
            base = Funcionario.objects.filter(setor_id=setor_id)
        else:
            base = Funcionario.objects.none()

        if user is not None:
            base = filter_funcionarios_by_scope(base, user)

        self.fields['funcionarios'].queryset = base.order_by('nome')

    def clean(self):
        cleaned = super().clean()
        di, df = cleaned.get('data_inicio'), cleaned.get('data_fim')
        if di and df and df < di:
            self.add_error('data_fim', "Data fim não pode ser anterior à data início.")
        return cleaned


# ---------------------------
# Recesso (CRUD individual)
# ---------------------------
class RecessoFuncionarioForm(forms.ModelForm):
    class Meta:
        model = RecessoFuncionario
        fields = ["setor", "funcionario", "data_inicio", "data_fim", "motivo"]
        widgets = {
            "setor": forms.Select(attrs={"class": "form-select"}),
            "funcionario": forms.Select(attrs={"class": "form-select"}),
            "data_inicio": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "data_fim": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "motivo": forms.TextInput(attrs={"class": "form-control", "placeholder": "Recesso"}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        setor_id = kwargs.pop("setor_id", None)
        super().__init__(*args, **kwargs)

        if user is not None:
            self.fields["setor"].queryset = filter_setores_by_scope(
                Setor.objects.all(), user
            ).order_by("nome")
            base_func = filter_funcionarios_by_scope(
                Funcionario.objects.select_related("setor"), user
            )
        else:
            self.fields["setor"].queryset = Setor.objects.all().order_by("nome")
            base_func = Funcionario.objects.select_related("setor")

        if setor_id:
            base_func = base_func.filter(setor_id=setor_id)

        self.fields["funcionario"].queryset = base_func.order_by("nome")
