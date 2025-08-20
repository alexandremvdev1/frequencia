from django import forms
from .models import Funcionario
from datetime import date


class FuncionarioForm(forms.ModelForm):
    class Meta:
        model = Funcionario
        fields = [
            'nome',
            'matricula',
            'cargo',
            'funcao',
            'setor',
            'turno',
            'turma',
            'data_admissao',
            'data_nascimento',
            'cpf',
            'rg',
            'pis',
            'titulo_eleitor',
            'ctps_numero',
            'ctps_serie',
            'telefone',
            'email',
            'endereco',
            'numero',
            'bairro',
            'cidade',
            'uf',
            'cep',
            'estado_civil',
            'escolaridade',
            'tem_planejamento',
            'horario_planejamento',
            'sabado_letivo',
            'foto',
        ]

        widgets = {
            'data_admissao': forms.TextInput(attrs={
                'placeholder': 'dd/mm/aaaa',
                'class': 'data-input',
                'autocomplete': 'off',
                'data-mask': 'date',
            }),
            'data_nascimento': forms.TextInput(attrs={
                'placeholder': 'dd/mm/aaaa',
                'class': 'data-input',
                'autocomplete': 'off',
                'data-mask': 'date',
            }),
        }

    def __init__(self, *args, **kwargs):
        super(FuncionarioForm, self).__init__(*args, **kwargs)

        # Aceitar entrada no formato brasileiro
        self.fields['data_admissao'].input_formats = ['%d/%m/%Y']
        self.fields['data_nascimento'].input_formats = ['%d/%m/%Y']

        # Mostrar valores já salvos no formato correto ao editar
        if self.instance and self.instance.pk:
            if self.instance.data_admissao:
                self.initial['data_admissao'] = self.instance.data_admissao.strftime('%d/%m/%Y')
            if self.instance.data_nascimento:
                self.initial['data_nascimento'] = self.instance.data_nascimento.strftime('%d/%m/%Y')

        # Campo opcional inicialmente
        self.fields['horario_planejamento'].required = False
        if self.instance and self.instance.tem_planejamento:
            self.fields['horario_planejamento'].required = True

from .models import HorarioTrabalho

class HorarioTrabalhoForm(forms.ModelForm):
    class Meta:
        model = HorarioTrabalho
        fields = ['funcionario', 'turno', 'horario_inicio', 'horario_fim']
        widgets = {
            'horario_inicio': forms.TimeInput(attrs={'type': 'time'}),
            'horario_fim': forms.TimeInput(attrs={'type': 'time'}),
        }

from .models import Feriado

class FeriadoForm(forms.ModelForm):
    class Meta:
        model = Feriado
        fields = ['data', 'descricao', 'sabado_letivo']  # Incluindo o campo sabado_letivo
        widgets = {
            'data': forms.DateInput(attrs={'type': 'date'}),
            'sabado_letivo': forms.CheckboxInput(attrs={'class': 'checkbox-input'}),  # Checkbox para sábado letivo
        }


class ImportacaoFuncionarioForm(forms.Form):
    excel_file = forms.FileField(label='Arquivo Excel', required=True)

MESES_CHOICES = [
    (1, 'Janeiro'), (2, 'Fevereiro'), (3, 'Março'), (4, 'Abril'),
    (5, 'Maio'), (6, 'Junho'), (7, 'Julho'), (8, 'Agosto'),
    (9, 'Setembro'), (10, 'Outubro'), (11, 'Novembro'), (12, 'Dezembro'),
]

class GerarFolhasIndividuaisForm(forms.Form):
    funcionario = forms.ModelChoiceField(queryset=Funcionario.objects.all(), label="Funcionário")
    ano = forms.IntegerField(label="Ano", initial=date.today().year)
    meses = forms.MultipleChoiceField(choices=MESES_CHOICES, widget=forms.CheckboxSelectMultiple, label="Meses")

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

# controle/forms.py
from django import forms
from .models import RecessoFuncionario, Setor, Funcionario

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
        super().__init__(*args, **kwargs)
        if setor_id:
            self.fields['funcionarios'].queryset = Funcionario.objects.filter(setor_id=setor_id).order_by('nome')
        else:
            self.fields['funcionarios'].queryset = Funcionario.objects.none()

    def clean(self):
        cleaned = super().clean()
        di, df = cleaned.get('data_inicio'), cleaned.get('data_fim')
        if di and df and df < di:
            self.add_error('data_fim', "Data fim não pode ser anterior à data início.")
        return cleaned

# controle/forms.py
from django import forms
from .models import RecessoFuncionario, Setor, Funcionario
from .permissions import filter_setores_by_scope, filter_funcionarios_by_scope

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
        # <<< aceita e consome os kwargs extras
        user = kwargs.pop("user", None)
        setor_id = kwargs.pop("setor_id", None)

        super().__init__(*args, **kwargs)

        # Filtra os conjuntos de opções conforme o escopo do usuário (se fornecido)
        if user is not None:
            self.fields["setor"].queryset = (
                filter_setores_by_scope(Setor.objects.all(), user).order_by("nome")
            )
            base_func = filter_funcionarios_by_scope(
                Funcionario.objects.select_related("setor"), user
            )
        else:
            self.fields["setor"].queryset = Setor.objects.all().order_by("nome")
            base_func = Funcionario.objects.select_related("setor")

        if setor_id:
            base_func = base_func.filter(setor_id=setor_id)

        self.fields["funcionario"].queryset = base_func.order_by("nome")

