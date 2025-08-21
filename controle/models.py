from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from cloudinary.models import CloudinaryField


# =======================
# Macro
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
        Prefeitura, on_delete=models.PROTECT, related_name='secretarias'
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


# =======================
# Órgão (sempre vinculado a uma Secretaria)
# =======================
class Orgao(models.Model):
    secretaria = models.ForeignKey(
        Secretaria, on_delete=models.PROTECT, related_name='orgaos'
    )
    nome = models.CharField(max_length=255)
    cnpj = models.CharField(max_length=18, blank=True, null=True)
    telefone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    logo = CloudinaryField('Logo do órgão', blank=True, null=True)

    class Meta:
        unique_together = ('secretaria', 'nome')
        verbose_name = "Órgão vinculado"
        verbose_name_plural = "Órgãos vinculados"
        ordering = ("secretaria__prefeitura__nome", "secretaria__nome", "nome")

    def __str__(self):
        return f"{self.nome} — {self.secretaria}"


# =======================
# Setor (existe dentro de UM único pai: Prefeitura OU Secretaria OU Órgão)
# Chefia oficial via FK -> Funcionario (um chefe por setor; um funcionario pode chefiar vários setores)
# =======================
class Setor(models.Model):
    nome = models.CharField(max_length=100)

    prefeitura = models.ForeignKey(
        Prefeitura, on_delete=models.PROTECT, related_name='setores', null=True, blank=True
    )
    secretaria = models.ForeignKey(
        Secretaria, on_delete=models.PROTECT, related_name='setores', null=True, blank=True
    )
    orgao = models.ForeignKey(
        Orgao, on_delete=models.PROTECT, related_name='setores', null=True, blank=True
    )

    # Chefia oficial do setor
    chefe = models.ForeignKey(
        'Funcionario', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='chefias_de_setor',
        help_text="Servidor que exerce a chefia deste setor."
    )

    class Meta:
        verbose_name = "Setor"
        verbose_name_plural = "Setores"
        ordering = ("nome",)
        constraints = [
            # Exatamente UM pai
            models.CheckConstraint(
                name="setor_exact_one_parent",
                check=(
                    (Q(prefeitura__isnull=False) & Q(secretaria__isnull=True) & Q(orgao__isnull=True)) |
                    (Q(prefeitura__isnull=True) & Q(secretaria__isnull=False) & Q(orgao__isnull=True)) |
                    (Q(prefeitura__isnull=True) & Q(secretaria__isnull=True) & Q(orgao__isnull=False))
                )
            ),
            # Nome único dentro do pai
            models.UniqueConstraint(
                fields=['nome', 'prefeitura'],
                name='uniq_setor_nome_prefeitura',
                condition=Q(prefeitura__isnull=False),
            ),
            models.UniqueConstraint(
                fields=['nome', 'secretaria'],
                name='uniq_setor_nome_secretaria',
                condition=Q(secretaria__isnull=False),
            ),
            models.UniqueConstraint(
                fields=['nome', 'orgao'],
                name='uniq_setor_nome_orgao',
                condition=Q(orgao__isnull=False),
            ),
        ]

    def clean(self):
        pais = [bool(self.prefeitura_id), bool(self.secretaria_id), bool(self.orgao_id)]
        if sum(pais) != 1:
            raise ValidationError("Setor deve pertencer a exatamente um: Prefeitura OU Secretaria OU Órgão.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def prefeitura_resolvida(self):
        if self.prefeitura_id:
            return self.prefeitura
        if self.secretaria_id:
            return self.secretaria.prefeitura
        if self.orgao_id:
            return self.orgao.secretaria.prefeitura
        return None

    @property
    def secretaria_resolvida(self):
        if self.secretaria_id:
            return self.secretaria
        if self.orgao_id:
            return self.orgao.secretaria
        return None

    def __str__(self):
        pai = self.orgao or self.secretaria or self.prefeitura or "-"
        return f"{self.nome} — {pai}"

    # Suporte legado: se por algum motivo chefe não estiver preenchido, busca pelo flag do funcionário
    def get_chefe(self):
        if self.chefe_id:
            return self.chefe
        from .models import Funcionario
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
class Funcionario(models.Model):
    TURNO_CHOICES = [('Matutino','Matutino'), ('Vespertino','Vespertino'), ('Noturno','Noturno'), ('Integral','Integral')]
    SERIE_CHOICES = [
        ('1º ANO','1º ANO'), ('2º ANO','2º ANO'), ('3º ANO','3º ANO'), ('4º ANO','4º ANO'),
        ('5º ANO','5º ANO'), ('6º ANO','6º ANO'), ('7º ANO','7º ANO'), ('8º ANO','8º ANO'), ('9º ANO','9º ANO'),
    ]
    TURMA_CHOICES = [('A','Turma A'), ('B','Turma B'), ('C','Turma C'), ('D','Turma D'), ('E','Turma E'), ('F','Turma F'), ('G','Turma G')]
    TIPO_VINCULO_CHOICES = [('Efetivo','Efetivo'), ('Contratado','Contratado')]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        related_name='funcionario', null=True, blank=True,
        help_text="Vínculo opcional com usuário do sistema."
    )

    nome = models.CharField(max_length=100)
    matricula = models.CharField(max_length=20, unique=True)
    cargo = models.CharField(max_length=50)
    funcao = models.CharField(max_length=50)

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

    # Flag informativo (não determina chefia oficial; esta é Setor.chefe)
    is_chefe_setor = models.BooleanField("Chefe do setor", default=False)
    chefe_setor_desde = models.DateField("Chefe desde", null=True, blank=True)

    class Meta:
        ordering = ("nome",)
        # Mantém a regra "apenas 1 marcado como chefe por setor" para o flag informativo
        constraints = [
            models.UniqueConstraint(
                fields=["setor"],
                condition=Q(is_chefe_setor=True),
                name="uniq_chefe_por_setor",
            ),
        ]

    def clean(self):
        super().clean()
        if self.is_chefe_setor and self.setor_id:
            qs = Funcionario.objects.filter(setor_id=self.setor_id, is_chefe_setor=True)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError({"is_chefe_setor": "Já existe um chefe definido para este setor."})

    def save(self, *args, **kwargs):
        if self.is_chefe_setor and not self.chefe_setor_desde:
            self.chefe_setor_desde = timezone.localdate()
        super().save(*args, **kwargs)

    # Atalhos hierárquicos
    @property
    def orgao(self):
        return self.setor.orgao if self.setor else None

    @property
    def secretaria(self):
        return self.setor.secretaria_resolvida if self.setor else None

    @property
    def prefeitura(self):
        return self.setor.prefeitura_resolvida if self.setor else None

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
# Permissões (acessos por nível)
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
    secretaria = models.ForeignKey(Secretaria, on_delete=models.CASCADE, related_name='acessos_secretaria')
    nivel = models.CharField(max_length=16, choices=NivelAcesso.choices, default=NivelAcesso.LEITURA)

    class Meta:
        unique_together = ('user', 'secretaria')
        verbose_name = "Acesso à Secretaria"
        verbose_name_plural = "Acessos às Secretarias"

    def __str__(self):
        return f"{self.user} -> {self.secretaria} ({self.get_nivel_display()})"


class AcessoOrgao(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='acessos_orgao')
    orgao = models.ForeignKey(Orgao, on_delete=models.CASCADE, related_name='acessos_orgao')
    nivel = models.CharField(max_length=16, choices=NivelAcesso.choices, default=NivelAcesso.LEITURA)

    class Meta:
        unique_together = ('user', 'orgao')
        verbose_name = "Acesso a Órgão"
        verbose_name_plural = "Acessos a Órgãos"

    def __str__(self):
        return f"{self.user} -> {self.orgao} ({self.get_nivel_display()})"


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
# Helpers de escopo
# =======================
def _user_is_admin(user):
    return bool(user and (user.is_superuser or user.is_staff))


def filter_setores_by_scope(qs, user):
    """
    Setores visíveis ao usuário por todos os níveis de acesso.
    Prefeitura → vê todos os setores da prefeitura (inclusive os das secretarias e órgãos)
    Secretaria → vê setores da secretaria e de seus órgãos
    Órgão → vê setores daquele órgão
    Setor → vê aquele setor
    """
    if _user_is_admin(user):
        return qs

    q = Q(acessos_setor__user=user)  # setor direto
    q |= Q(prefeitura__acessos_prefeitura__user=user)

    # acesso em secretaria pega setores da própria e dos órgãos dela
    q |= Q(secretaria__acessos_secretaria__user=user)
    q |= Q(orgao__secretaria__acessos_secretaria__user=user)

    # acesso em órgão pega setores do órgão
    q |= Q(orgao__acessos_orgao__user=user)

    return qs.filter(q).distinct()


def filter_funcionarios_by_scope(qs, user):
    if _user_is_admin(user):
        return qs
    setores_visiveis = filter_setores_by_scope(Setor.objects.all(), user).values('id')
    return qs.filter(setor_id__in=setores_visiveis).distinct()


def assert_can_access_setor(user, setor: Setor) -> bool:
    return filter_setores_by_scope(Setor.objects.filter(id=setor.id), user).exists()


def assert_can_access_funcionario(user, funcionario: 'Funcionario') -> bool:
    return filter_funcionarios_by_scope(Funcionario.objects.filter(id=funcionario.id), user).exists()


# =======================
# Escopos de usuário (multinível)
# =======================
class UserScope(models.Model):
    class Nivel(models.TextChoices):
        LEITURA = 'LEITURA', 'Leitura'
        GERENCIA = 'GERENCIA', 'Gerenciar (CRUD)'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='scopes')

    # Exatamente UM destes
    prefeitura = models.ForeignKey(Prefeitura, on_delete=models.PROTECT, null=True, blank=True, related_name='scopes')
    secretaria = models.ForeignKey(Secretaria, on_delete=models.PROTECT, null=True, blank=True, related_name='scopes')
    orgao = models.ForeignKey(Orgao, on_delete=models.PROTECT, null=True, blank=True, related_name='scopes')
    setor = models.ForeignKey(Setor, on_delete=models.PROTECT, null=True, blank=True, related_name='scopes')

    nivel = models.CharField(max_length=16, choices=Nivel.choices, default=Nivel.LEITURA)

    class Meta:
        verbose_name = "Escopo de Usuário"
        verbose_name_plural = "Escopos de Usuário"
        unique_together = ('user', 'prefeitura', 'secretaria', 'orgao', 'setor')
        constraints = [
            models.CheckConstraint(
                name="userscope_exact_one_target",
                check=(
                    (Q(prefeitura__isnull=False) & Q(secretaria__isnull=True) & Q(orgao__isnull=True) & Q(setor__isnull=True)) |
                    (Q(prefeitura__isnull=True) & Q(secretaria__isnull=False) & Q(orgao__isnull=True) & Q(setor__isnull=True)) |
                    (Q(prefeitura__isnull=True) & Q(secretaria__isnull=True) & Q(orgao__isnull=False) & Q(setor__isnull=True)) |
                    (Q(prefeitura__isnull=True) & Q(secretaria__isnull=True) & Q(orgao__isnull=True) & Q(setor__isnull=False))
                )
            ),
        ]

    def clean(self):
        alvos = [bool(self.prefeitura_id), bool(self.secretaria_id), bool(self.orgao_id), bool(self.setor_id)]
        if sum(alvos) != 1:
            raise ValidationError("Selecione exatamente um alvo: Prefeitura OU Secretaria OU Órgão OU Setor.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def alvo_tipo(self):
        if self.prefeitura_id: return "Prefeitura"
        if self.secretaria_id: return "Secretaria"
        if self.orgao_id: return "Órgão"
        if self.setor_id: return "Setor"
        return "-"

    def alvo_nome(self):
        if self.prefeitura_id: return self.prefeitura.nome
        if self.secretaria_id: return self.secretaria.nome
        if self.orgao_id: return self.orgao.nome
        if self.setor_id: return self.setor.nome
        return "-"

    def __str__(self):
        return f"{self.user} -> {self.alvo_tipo()} {self.alvo_nome()} ({self.get_nivel_display()})"


# --- Permissão por Função (Diretor, Coordenador, etc.) -----------------------
class FuncaoPermissao(models.Model):
    class Nivel(models.TextChoices):
        LEITURA = 'LEITURA', 'Leitura'
        GERENCIA = 'GERENCIA', 'Gerenciar (CRUD)'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='permissoes_funcao')
    nome_funcao = models.CharField(max_length=50)

    nivel = models.CharField(max_length=16, choices=Nivel.choices, default=Nivel.LEITURA)

    # Escopo opcional
    secretaria = models.ForeignKey(Secretaria, on_delete=models.PROTECT, null=True, blank=True, related_name='permissoes_funcao')
    orgao = models.ForeignKey(Orgao, on_delete=models.PROTECT, null=True, blank=True, related_name='permissoes_funcao')
    setor = models.ForeignKey(Setor, on_delete=models.PROTECT, null=True, blank=True, related_name='permissoes_funcao')

    class Meta:
        verbose_name = "Permissão por Função"
        verbose_name_plural = "Permissões por Função"
        unique_together = ('user', 'nome_funcao', 'nivel', 'secretaria', 'orgao', 'setor')

    def clean(self):
        # permite no máx. 1 escopo específico
        count = sum([bool(self.secretaria_id), bool(self.orgao_id), bool(self.setor_id)])
        if count > 1:
            raise ValidationError("Escolha no máximo um escopo: Secretaria OU Órgão OU Setor (ou deixe todos em branco).")

    def __str__(self):
        alvo = self.setor or self.orgao or self.secretaria or "GLOBAL"
        return f"{self.user} -> {self.nome_funcao} ({self.get_nivel_display()}) @ {alvo}"


class RecessoFuncionario(models.Model):
    setor = models.ForeignKey(Setor, on_delete=models.CASCADE, related_name='recessos')
    funcionario = models.ForeignKey(Funcionario, on_delete=models.CASCADE, related_name='recessos')
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
