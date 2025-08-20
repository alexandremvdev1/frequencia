# controle/models.py
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q
from cloudinary.models import CloudinaryField


# =======================
# Unidades “macro”
# =======================
class Prefeitura(models.Model):
    nome = models.CharField(max_length=255, unique=True)
    cnpj = models.CharField(max_length=18, blank=True, null=True, unique=True)
    cidade = models.CharField(max_length=100, blank=True, null=True)
    uf = models.CharField(max_length=2, blank=True, null=True)
    endereco = models.CharField(max_length=255, blank=True, null=True)
    numero = models.CharField(max_length=20, blank=True, null=True)
    bairro = models.CharField(max_length=100, blank=True, null=True)
    telefone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    logo = CloudinaryField('Logo da prefeitura', blank=True, null=True)

    class Meta:
        verbose_name = "Prefeitura"
        verbose_name_plural = "Prefeituras"
        ordering = ("nome",)

    def __str__(self):
        return self.nome


class Secretaria(models.Model):
    prefeitura = models.ForeignKey(
        Prefeitura,
        on_delete=models.PROTECT,
        related_name='secretarias'
    )
    nome = models.CharField(max_length=255)
    cnpj = models.CharField(max_length=18, blank=True, null=True)
    telefone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    logo = CloudinaryField('Logo da secretaria', blank=True, null=True)

    class Meta:
        unique_together = ('prefeitura', 'nome')
        verbose_name = "Secretaria"
        verbose_name_plural = "Secretarias"
        ordering = ("prefeitura__nome", "nome")

    def __str__(self):
        return f"{self.nome} ({self.prefeitura})"


class Escola(models.Model):
    # Informação descritiva (mantida para compatibilidade, se você já usa)
    nome_secretaria = models.CharField(max_length=255)
    nome_escola = models.CharField(max_length=255)
    cnpj = models.CharField(max_length=18, unique=True)
    endereco = models.CharField(max_length=255)
    numero = models.CharField(max_length=20)
    bairro = models.CharField(max_length=100)
    cidade = models.CharField(max_length=100)
    uf = models.CharField(max_length=2)
    logo = CloudinaryField('Imagem de fundo', blank=True, null=True)
    telefone = models.CharField(max_length=15, blank=True, null=True)
    email = models.EmailField(max_length=254, blank=True, null=True)

    # Vínculo real com a Secretaria
    secretaria = models.ForeignKey(
        Secretaria,
        on_delete=models.PROTECT,
        related_name='escolas',
        null=True,
        blank=True
    )

    class Meta:
        verbose_name = "Escola"
        verbose_name_plural = "Escolas"
        ordering = ("nome_escola",)

    def __str__(self):
        return f"{self.nome_escola} - {self.nome_secretaria}"


# =======================
# Departamento
# Pertence a: Prefeitura OU Secretaria OU Escola (exatamente um)
# tipo = ORGAO (Escola/Hospital/etc) ou ADMIN (estrutura administrativa) ou OUTRO
# =======================
class Departamento(models.Model):
    class Tipo(models.TextChoices):
        ORGAO = 'ORGAO', 'Órgão vinculado'
        ADMIN = 'ADMIN', 'Estrutura administrativa'
        OUTRO = 'OUTRO', 'Outro'

    nome = models.CharField(max_length=255)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.ADMIN)

    prefeitura = models.ForeignKey(
        Prefeitura, on_delete=models.PROTECT,
        related_name='departamentos',
        null=True, blank=True
    )
    secretaria = models.ForeignKey(
        Secretaria, on_delete=models.PROTECT,
        related_name='departamentos',
        null=True, blank=True
    )
    escola = models.ForeignKey(
        Escola, on_delete=models.PROTECT,
        related_name='departamentos',
        null=True, blank=True
    )

    class Meta:
        verbose_name = "Departamento"
        verbose_name_plural = "Departamentos"
        ordering = ("nome",)
        constraints = [
            # EXATAMENTE UM pai
            models.CheckConstraint(
                name="departamento_exact_one_parent",
                check=(
                    (Q(prefeitura__isnull=False) & Q(secretaria__isnull=True)  & Q(escola__isnull=True))  |
                    (Q(prefeitura__isnull=True)  & Q(secretaria__isnull=False) & Q(escola__isnull=True))  |
                    (Q(prefeitura__isnull=True)  & Q(secretaria__isnull=True)  & Q(escola__isnull=False))
                ),
            ),
            # Unicidade por pai
            models.UniqueConstraint(
                fields=['nome', 'prefeitura'],
                name='uniq_dep_nome_prefeitura',
                condition=Q(prefeitura__isnull=False),
            ),
            models.UniqueConstraint(
                fields=['nome', 'secretaria'],
                name='uniq_dep_nome_secretaria',
                condition=Q(secretaria__isnull=False),
            ),
            models.UniqueConstraint(
                fields=['nome', 'escola'],
                name='uniq_dep_nome_escola',
                condition=Q(escola__isnull=False),
            ),
        ]

    def clean(self):
        pais = [bool(self.prefeitura_id), bool(self.secretaria_id), bool(self.escola_id)]
        if sum(pais) != 1:
            raise ValidationError(
                "Departamento deve pertencer a exatamente uma unidade: Prefeitura OU Secretaria OU Escola."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        pai = self.prefeitura or self.secretaria or self.escola or "-"
        rotulo = dict(self.Tipo.choices).get(self.tipo, self.tipo)
        return f"{self.nome} • {rotulo} — {pai}"


# =======================
# Setor
# Vive dentro de um Departamento (oficial).
# Campo `secretaria` (legado) mantido para compatibilidade com telas antigas.
# =======================
class Setor(models.Model):
    nome = models.CharField(max_length=100)

    departamento = models.ForeignKey(
        Departamento,
        on_delete=models.PROTECT,
        related_name='setores',
        null=True, blank=True
    )

    # LEGADO (se puder remover depois, melhor):
    secretaria = models.ForeignKey(
        Secretaria,
        on_delete=models.PROTECT,
        related_name='setores',
        null=True, blank=True
    )

    class Meta:
        verbose_name = "Setor"
        verbose_name_plural = "Setores"
        ordering = ("nome",)
        constraints = [
            models.CheckConstraint(
                name="setor_has_parent",
                check=Q(departamento__isnull=False) | Q(secretaria__isnull=False),
            ),
        ]

    def clean(self):
        if not self.departamento and not self.secretaria:
            raise ValidationError("Informe ao menos o Departamento (recomendado) ou a Secretaria (legado).")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    # Atalhos hierárquicos (para evitar redundância em Funcionario)
    @property
    def escola(self):
        return self.departamento.escola if self.departamento else None

    @property
    def secretaria_oficial(self):
        if self.departamento and self.departamento.secretaria:
            return self.departamento.secretaria
        return self.secretaria  # legado

    @property
    def prefeitura(self):
        if self.departamento:
            if self.departamento.prefeitura:
                return self.departamento.prefeitura
            if self.departamento.secretaria:
                return self.departamento.secretaria.prefeitura
            if self.departamento.escola and self.departamento.escola.secretaria:
                return self.departamento.escola.secretaria.prefeitura
        if self.secretaria:
            return self.secretaria.prefeitura
        return None

    def __str__(self):
        trilha = self.departamento or self.secretaria or "-"
        return f"{self.nome} — {trilha}"

    def get_chefe(self):
        from .models import Funcionario  # import tardio para evitar ciclo
        return (Funcionario.objects
                .filter(setor=self, is_chefe_setor=True)
                .order_by('chefe_setor_desde', 'id')
                .first())

    @property
    def chefe_atual(self):
        return self.get_chefe()

# =======================
# Funcionário
# =======================
# controle/models.py
from django.db import models
from django.conf import settings
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.utils import timezone

class Funcionario(models.Model):
    TURNO_CHOICES = [
        ('Matutino', 'Matutino'),
        ('Vespertino', 'Vespertino'),
        ('Noturno', 'Noturno'),
        ('Integral', 'Integral'),
    ]

    SERIE_CHOICES = [
        ('1º ANO', '1º ANO'),
        ('2º ANO', '2º ANO'),
        ('3º ANO', '3º ANO'),
        ('4º ANO', '4º ANO'),
        ('5º ANO', '5º ANO'),
        ('6º ANO', '6º ANO'),
        ('7º ANO', '7º ANO'),
        ('8º ANO', '8º ANO'),
        ('9º ANO', '9º ANO'),
    ]

    TURMA_CHOICES = [
        ('A', 'Turma A'), ('B', 'Turma B'), ('C', 'Turma C'),
        ('D', 'Turma D'), ('E', 'Turma E'), ('F', 'Turma F'), ('G', 'Turma G'),
    ]

    TIPO_VINCULO_CHOICES = [
        ('Efetivo', 'Efetivo'),
        ('Contratado', 'Contratado'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='funcionario',
        null=True, blank=True,
        help_text="Vínculo opcional com usuário do sistema."
    )

    nome = models.CharField(max_length=100)
    matricula = models.CharField(max_length=20, unique=True)
    cargo = models.CharField(max_length=50)
    funcao = models.CharField(max_length=50)

    # Setor determina a árvore
    setor = models.ForeignKey('controle.Setor', on_delete=models.CASCADE, db_index=True)

    data_admissao = models.DateField()
    data_nascimento = models.DateField(null=True, blank=True)

    cpf = models.CharField(max_length=14, unique=True, blank=True, null=True)
    rg = models.CharField(max_length=20, blank=True, null=True)
    pis = models.CharField(max_length=20, blank=True, null=True)
    titulo_eleitor = models.CharField(max_length=20, blank=True, null=True)
    ctps_numero = models.CharField(max_length=20, blank=True, null=True)
    ctps_serie = models.CharField(max_length=10, blank=True, null=True)

    telefone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)

    endereco = models.CharField(max_length=255, blank=True, null=True)
    numero = models.CharField(max_length=10, blank=True, null=True)
    bairro = models.CharField(max_length=100, blank=True, null=True)
    cidade = models.CharField(max_length=100, blank=True, null=True)
    uf = models.CharField(max_length=2, blank=True, null=True)
    cep = models.CharField(max_length=10, blank=True, null=True)

    estado_civil = models.CharField(max_length=20, blank=True, null=True)
    escolaridade = models.CharField(max_length=100, blank=True, null=True)

    tem_planejamento = models.BooleanField(default=False)
    horario_planejamento = models.CharField(max_length=50, blank=True, null=True)
    sabado_letivo = models.BooleanField(default=False)

    foto = models.ImageField(upload_to='fotos_funcionarios/', blank=True, null=True)

    turma = models.CharField(max_length=10, choices=TURMA_CHOICES, blank=True, null=True)
    turno = models.CharField(max_length=20, choices=TURNO_CHOICES, blank=True, null=True)
    serie = models.CharField(max_length=20, choices=SERIE_CHOICES, blank=True, null=True)

    tipo_vinculo = models.CharField(max_length=20, choices=TIPO_VINCULO_CHOICES, blank=True, null=True)
    fonte_pagadora = models.CharField(max_length=100, blank=True, null=True)

    inicio_ferias = models.DateField(blank=True, null=True)
    fim_ferias = models.DateField(blank=True, null=True)

    # ✔ Chefia do setor
    is_chefe_setor = models.BooleanField(
        "Chefe do setor", default=False,
        help_text="Marque se este servidor é a chefia imediata do setor."
    )
    chefe_setor_desde = models.DateField(
        "Chefe desde", null=True, blank=True,
        help_text="Data a partir da qual é chefe do setor."
    )

    class Meta:
        ordering = ("nome",)
        # ✔ Garante no máximo 1 chefe por setor (apenas quando is_chefe_setor=True)
        constraints = [
            models.UniqueConstraint(
                fields=["setor"],
                condition=Q(is_chefe_setor=True),
                name="uniq_chefe_por_setor",
            ),
        ]

    # --------- Validação amigável ---------
    def clean(self):
        super().clean()
        if self.is_chefe_setor and self.setor_id:
            qs = Funcionario.objects.filter(setor_id=self.setor_id, is_chefe_setor=True)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError({
                    "is_chefe_setor": "Já existe um chefe definido para este setor."
                })

    # --------- Auto-preenche a data quando marcar como chefe ---------
    def save(self, *args, **kwargs):
        if self.is_chefe_setor and not self.chefe_setor_desde:
            self.chefe_setor_desde = timezone.localdate()
        super().save(*args, **kwargs)

    # --------- Atalhos hierárquicos ---------
    @property
    def departamento(self):
        return self.setor.departamento if self.setor else None  # quando tipo=ORGAO, isto é o “órgão”

    @property
    def orgao(self):
        dep = self.setor.departamento if self.setor else None
        # mantém compatibilidade com seu enum Tipo.ORGAO
        if dep and hasattr(dep, "Tipo") and getattr(dep.Tipo, "ORGAO", None) == getattr(dep, "tipo", None):
            return dep
        return None

    @property
    def escola(self):
        return self.setor.escola if self.setor else None

    @property
    def secretaria(self):
        # alguns projetos têm secretaria_oficial no Setor
        if self.setor:
            return getattr(self.setor, "secretaria_oficial", None) or getattr(self.setor, "secretaria", None)
        return None

    @property
    def prefeitura(self):
        return self.setor.prefeitura if self.setor else None

    def __str__(self):
        return self.nome



# =======================
# Operação
# =======================
class HorarioTrabalho(models.Model):
    TURNOS = [('Manhã', 'Manhã'), ('Tarde', 'Tarde')]
    funcionario = models.ForeignKey(Funcionario, on_delete=models.CASCADE)
    turno = models.CharField(max_length=10, choices=TURNOS)
    horario_inicio = models.TimeField(blank=True, null=True)
    horario_fim = models.TimeField(blank=True, null=True)

    def __str__(self):
        hi = self.horario_inicio.strftime('%H:%M') if self.horario_inicio else '__:__'
        hf = self.horario_fim.strftime('%H:%M') if self.horario_fim else '__:__'
        return f"{self.funcionario.nome} - {self.turno}: {hi} às {hf}"


class Feriado(models.Model):
    data = models.DateField(unique=True)
    descricao = models.CharField(max_length=100)
    sabado_letivo = models.BooleanField(default=False)

    class Meta:
        ordering = ("data",)

    def __str__(self):
        return f"{self.data.strftime('%d/%m/%Y')} - {self.descricao}"


class FolhaFrequencia(models.Model):
    funcionario = models.ForeignKey(Funcionario, on_delete=models.CASCADE)
    mes = models.IntegerField()
    ano = models.IntegerField()
    data_geracao = models.DateTimeField(auto_now_add=True)
    html_armazenado = models.TextField()

    class Meta:
        unique_together = ('funcionario', 'mes', 'ano')
        ordering = ("funcionario__nome", "ano", "mes")

    def __str__(self):
        return f"{self.funcionario.nome} - {self.mes:02d}/{self.ano}"


class SabadoLetivo(models.Model):
    data = models.DateField(unique=True)
    descricao = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        ordering = ("data",)

    def __str__(self):
        return f"Sábado Letivo - {self.data.strftime('%d/%m/%Y')}"


# =======================
# Permissões por nível (legado/auxiliar)
# =======================
class NivelAcesso(models.TextChoices):
    LEITURA = 'LEITURA', 'Leitura'
    GERENCIA = 'GERENCIA', 'Gerenciar (CRUD)'


class AcessoPrefeitura(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='acessos_prefeitura')
    prefeitura = models.ForeignKey(Prefeitura, on_delete=models.CASCADE, related_name='acessos_prefeitura')
    nivel = models.CharField(max_length=16, choices=NivelAcesso.choices, default=NivelAcesso.LEITURA)

    class Meta:
        unique_together = ('user', 'prefeitura')
        verbose_name = "Acesso à Prefeitura"
        verbose_name_plural = "Acessos à Prefeitura"

    def __str__(self):
        return f"{self.user} -> {self.prefeitura} ({self.get_nivel_display()})"


class AcessoSecretaria(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='acessos_secretaria')
    secretaria = models.ForeignKey(Secretaria, on_delete=models.CASCADE, related_name='acessos')
    nivel = models.CharField(max_length=16, choices=NivelAcesso.choices, default=NivelAcesso.LEITURA)

    class Meta:
        unique_together = ('user', 'secretaria')
        verbose_name = "Acesso à Secretaria"
        verbose_name_plural = "Acessos às Secretarias"

    def __str__(self):
        return f"{self.user} -> {self.secretaria} ({self.get_nivel_display()})"


class AcessoEscola(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='acessos_escola')
    escola = models.ForeignKey(Escola, on_delete=models.CASCADE, related_name='acessos_escola')
    nivel = models.CharField(max_length=16, choices=NivelAcesso.choices, default=NivelAcesso.LEITURA)

    class Meta:
        unique_together = ('user', 'escola')
        verbose_name = "Acesso à Unidade (Escola)"
        verbose_name_plural = "Acessos às Unidades (Escolas)"

    def __str__(self):
        return f"{self.user} -> {self.escola} ({self.get_nivel_display()})"


class AcessoSetor(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='acessos_setor')
    setor = models.ForeignKey(Setor, on_delete=models.CASCADE, related_name='acessos_setor')
    nivel = models.CharField(max_length=16, choices=NivelAcesso.choices, default=NivelAcesso.LEITURA)

    class Meta:
        unique_together = ('user', 'setor')
        verbose_name = "Acesso a Setor"
        verbose_name_plural = "Acessos a Setores"

    def __str__(self):
        return f"{self.user} -> {self.setor} ({self.get_nivel_display()})"


# =======================
# Helpers de escopo rápidos (podem ficar no app permissions.py)
# =======================
def _user_is_admin(user):
    return bool(user and (user.is_superuser or user.is_staff))


def filter_setores_by_scope(qs, user):
    """Retorna apenas os setores visíveis pelo usuário, considerando todos os níveis de acesso (legado)."""
    if _user_is_admin(user):
        return qs

    q = Q(acessos_setor__user=user)  # setor direto
    q |= Q(departamento__escola__acessos_escola__user=user)  # por escola
    q |= Q(departamento__secretaria__acessos__user=user)     # por secretaria (via depto)
    q |= Q(secretaria__acessos__user=user)                   # legado no próprio Setor
    q |= Q(departamento__prefeitura__acessos_prefeitura__user=user)  # por prefeitura (via depto)
    q |= Q(secretaria__prefeitura__acessos_prefeitura__user=user)    # por prefeitura (via secretaria legado)
    return qs.filter(q).distinct()


def filter_funcionarios_by_scope(qs, user):
    """Filtra Funcionario pelo escopo do usuário (relacionando via setor)."""
    if _user_is_admin(user):
        return qs
    setores_visiveis = filter_setores_by_scope(Setor.objects.all(), user).values('id')
    return qs.filter(setor_id__in=setores_visiveis).distinct()


def assert_can_access_setor(user, setor: Setor) -> bool:
    return filter_setores_by_scope(Setor.objects.filter(id=setor.id), user).exists()


def assert_can_access_funcionario(user, funcionario: 'Funcionario') -> bool:
    return filter_funcionarios_by_scope(Funcionario.objects.filter(id=funcionario.id), user).exists()


# =======================
# Escopos de acesso por usuário (multinível)
# =======================
class UserScope(models.Model):
    class Nivel(models.TextChoices):
        LEITURA = 'LEITURA', 'Leitura'
        GERENCIA = 'GERENCIA', 'Gerenciar (CRUD)'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='scopes'
    )

    # Exatamente UM destes deve ser preenchido
    prefeitura = models.ForeignKey(Prefeitura, on_delete=models.PROTECT, null=True, blank=True, related_name='scopes')
    secretaria = models.ForeignKey(Secretaria, on_delete=models.PROTECT, null=True, blank=True, related_name='scopes')
    escola = models.ForeignKey(Escola, on_delete=models.PROTECT, null=True, blank=True, related_name='scopes')
    departamento = models.ForeignKey('Departamento', on_delete=models.PROTECT, null=True, blank=True, related_name='scopes')
    setor = models.ForeignKey('Setor', on_delete=models.PROTECT, null=True, blank=True, related_name='scopes')

    nivel = models.CharField(max_length=16, choices=Nivel.choices, default=Nivel.LEITURA)

    class Meta:
        verbose_name = "Escopo de Usuário"
        verbose_name_plural = "Escopos de Usuário"
        unique_together = ('user', 'prefeitura', 'secretaria', 'escola', 'departamento', 'setor')
        constraints = [
            models.CheckConstraint(
                name="userscope_exact_one_target",
                check=(
                    (Q(prefeitura__isnull=False) & Q(secretaria__isnull=True)  & Q(escola__isnull=True)  & Q(departamento__isnull=True) & Q(setor__isnull=True)) |
                    (Q(prefeitura__isnull=True)  & Q(secretaria__isnull=False) & Q(escola__isnull=True)  & Q(departamento__isnull=True) & Q(setor__isnull=True)) |
                    (Q(prefeitura__isnull=True)  & Q(secretaria__isnull=True)  & Q(escola__isnull=False) & Q(departamento__isnull=True) & Q(setor__isnull=True)) |
                    (Q(prefeitura__isnull=True)  & Q(secretaria__isnull=True)  & Q(escola__isnull=True)  & Q(departamento__isnull=False) & Q(setor__isnull=True)) |
                    (Q(prefeitura__isnull=True)  & Q(secretaria__isnull=True)  & Q(escola__isnull=True)  & Q(departamento__isnull=True) & Q(setor__isnull=False))
                ),
            ),
        ]

    def clean(self):
        alvos = [
            bool(self.prefeitura_id),
            bool(self.secretaria_id),
            bool(self.escola_id),
            bool(self.departamento_id),
            bool(self.setor_id),
        ]
        if sum(alvos) != 1:
            raise ValidationError("Selecione exatamente um alvo: Prefeitura OU Secretaria OU Escola OU Departamento OU Setor.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def alvo_tipo(self):
        if self.prefeitura_id: return "Prefeitura"
        if self.secretaria_id: return "Secretaria"
        if self.escola_id: return "Escola"
        if self.departamento_id: return "Departamento"
        if self.setor_id: return "Setor"
        return "-"

    def alvo_nome(self):
        if self.prefeitura_id: return self.prefeitura.nome
        if self.secretaria_id: return self.secretaria.nome
        if self.escola_id: return self.escola.nome_escola
        if self.departamento_id: return self.departamento.nome
        if self.setor_id: return self.setor.nome
        return "-"

    def __str__(self):
        return f"{self.user} -> {self.alvo_tipo()} {self.alvo_nome()} ({self.get_nivel_display()})"


# --- Permissão por Função (Diretor, Coordenador, etc.) -----------------------
class FuncaoPermissao(models.Model):
    class Nivel(models.TextChoices):
        LEITURA = 'LEITURA', 'Leitura'
        GERENCIA = 'GERENCIA', 'Gerenciar (CRUD)'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='permissoes_funcao'
    )
    # nome exato da função do Funcionario.funcao (ex.: "DIRETOR(A)")
    nome_funcao = models.CharField(max_length=50)

    # nível exigido para as ações liberadas
    nivel = models.CharField(max_length=16, choices=Nivel.choices, default=Nivel.LEITURA)

    # (Opcional) restringir por escopo adicional — deixe em branco para valer “em qualquer lugar”
    secretaria = models.ForeignKey('Secretaria', on_delete=models.PROTECT, null=True, blank=True, related_name='permissoes_funcao')
    setor = models.ForeignKey('Setor', on_delete=models.PROTECT, null=True, blank=True, related_name='permissoes_funcao')

    class Meta:
        verbose_name = "Permissão por Função"
        verbose_name_plural = "Permissões por Função"
        unique_together = ('user', 'nome_funcao', 'nivel', 'secretaria', 'setor')

    def clean(self):
        if self.secretaria_id and self.setor_id:
            raise ValidationError("Escolha secretaria OU setor (ou deixe ambos em branco).")

    def __str__(self):
        alvo = self.setor or self.secretaria or "GLOBAL"
        return f"{self.user} -> {self.nome_funcao} ({self.get_nivel_display()}) @ {alvo}"

class RecessoFuncionario(models.Model):
    setor = models.ForeignKey('controle.Setor', on_delete=models.CASCADE, related_name='recessos')
    funcionario = models.ForeignKey('controle.Funcionario', on_delete=models.CASCADE, related_name='recessos')
    data_inicio = models.DateField()
    data_fim = models.DateField()
    motivo = models.CharField(max_length=120, blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=['funcionario', 'data_inicio', 'data_fim']),
            models.Index(fields=['setor', 'data_inicio', 'data_fim']),
        ]
        verbose_name = "Recesso de Funcionário"
        verbose_name_plural = "Recessos de Funcionários"

    def clean(self):
        if self.data_fim < self.data_inicio:
            raise ValidationError("Data fim não pode ser anterior à data início.")

    def __str__(self):
        return f"Recesso {self.funcionario} ({self.data_inicio} → {self.data_fim})"