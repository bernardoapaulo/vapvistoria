"""
Apaga os dados de TESTE e deixa o sistema pronto para uso.

APAGA: clientes, alunos (e documentos), veículos, atendimentos (e histórico), agendamentos, recebimentos, despesas
(e comprovantes), fechamentos de mês, auditoria, registros de Vip/Preparação (e fotos), regravações (anexos, documentos
emitidos, parceiros e técnicos) e os tipos de serviço.
MANTÉM: usuários (menos "funcionario_teste", o usuário fictício), grupos e permissões, categorias de despesa, horário de
funcionamento e a configuração da empresa (só a empresa de EXEMPLO é apagada).

Segurança: sem --confirmar só MOSTRA o que seria apagado. Com --somente-se-ficticio (usado no deploy da Vercel) o
comando só age se os dados fictícios do `popular_dados` ainda existirem; depois de limpo, vira um "nada a fazer" e
pode ficar ligado sem risco de apagar dados reais.

Uso:
    python manage.py limpar_dados_teste              # mostra o que seria apagado
    python manage.py limpar_dados_teste --confirmar  # apaga
"""
from django.core.management.base import BaseCommand
from django.core.management.color import no_style
from django.db import connection, transaction

from agenda.models import Agendamento
from atendimentos.models import Atendimento, HistoricoAtendimento
from cadastros.models import Aluno, Cliente, Veiculo
from contas.management.commands.popular_dados import CLIENTES
from django.contrib.auth import get_user_model
from financeiro.models import Despesa, FechamentoMes, Recebimento, RegistroAuditoria
from servicos.models import TipoServico
from regravacoes.models import (
    AnexoRegravacao, ConfiguracaoEmpresa, DocumentoEmitido, HistoricoRegravacao, Parceiro, RegistroRegravacao,
    SequenciaDocumento, Tecnico,
)
from vip_preparacao.models import FotoVip, HistoricoVip, ItemServicoVip, RegistroVip

USUARIO_FICTICIO = "funcionario_teste"
NOMES_FICTICIOS = [c[0] for c in CLIENTES]

# Ordem segura: o que protege (PROTECT) outro registro sai antes dele
ETAPAS = [
    ("Fotos de Vip/Preparação", FotoVip), ("Itens de serviço do Vip", ItemServicoVip),
    ("Histórico do Vip", HistoricoVip), ("Registros de Vip/Preparação", RegistroVip),
    ("Documentos emitidos (PDF)", DocumentoEmitido), ("Numeração dos documentos", SequenciaDocumento),
    ("Anexos de regravação", AnexoRegravacao), ("Histórico de regravações", HistoricoRegravacao),
    ("Regravações", RegistroRegravacao), ("Parceiros indicadores", Parceiro), ("Técnicos responsáveis", Tecnico),
    ("Agendamentos", Agendamento), ("Recebimentos", Recebimento), ("Despesas", Despesa),
    ("Fechamentos de mês", FechamentoMes), ("Auditoria do financeiro", RegistroAuditoria),
    ("Histórico de atendimentos", HistoricoAtendimento), ("Atendimentos", Atendimento),
    ("Veículos", Veiculo), ("Alunos", Aluno), ("Clientes", Cliente), ("Tipos de serviço", TipoServico),
]


def _arquivos(modelo):
    """(armazenamento, nome) de cada arquivo guardado pelos registros do modelo."""
    campos = [f for f in modelo._meta.get_fields() if getattr(f, "upload_to", None) is not None]
    for objeto in modelo.objects.all().iterator():
        for campo in campos:
            arquivo = getattr(objeto, campo.name)
            if arquivo:
                yield arquivo.storage, arquivo.name


class Command(BaseCommand):
    help = "Apaga os dados de teste (clientes, atendimentos, financeiro, Vip, serviços...) e deixa o sistema pronto para uso."

    def add_arguments(self, parser):
        parser.add_argument("--confirmar", action="store_true", help="Apaga de verdade (sem isto só mostra o que seria apagado).")
        parser.add_argument("--somente-se-ficticio", action="store_true",
                            help="Só age se os dados fictícios do popular_dados ainda existirem (seguro para deixar ligado no deploy).")

    def handle(self, *args, **opcoes):
        if opcoes["somente_se_ficticio"] and not Cliente.objects.filter(nome__in=NOMES_FICTICIOS).exists():
            self.stdout.write("Dados fictícios não encontrados: nada a limpar.")
            return

        contagens = [(rotulo, modelo, modelo.objects.count()) for rotulo, modelo in ETAPAS]
        usuario = get_user_model().objects.filter(username=USUARIO_FICTICIO)
        self.stdout.write("O que será apagado:" if opcoes["confirmar"] else "SIMULAÇÃO (nada foi apagado). Seria apagado:")
        for rotulo, _, n in contagens:
            self.stdout.write(f"  {rotulo}: {n}")
        self.stdout.write(f"  Usuário fictício '{USUARIO_FICTICIO}': {usuario.count()}")
        self.stdout.write("Fica: demais usuários, grupos, categorias de despesa e horário de funcionamento.")
        if not opcoes["confirmar"]:
            self.stdout.write(self.style.WARNING("Para apagar de verdade, rode com --confirmar."))
            return

        arquivos = []
        for _, modelo, n in contagens:
            if n:
                arquivos += list(_arquivos(modelo))
        with transaction.atomic():
            for _, modelo, _ in contagens:
                modelo.objects.all().delete()
            usuario.delete()

        for armazenamento, nome in arquivos:           # arquivos enviados (fotos, documentos, comprovantes)
            try:
                armazenamento.delete(nome)
            except Exception:
                pass
        # a empresa de EXEMPLO do popular_dados volta ao branco; uma empresa REAL (já configurada) fica como está
        ConfiguracaoEmpresa.objects.filter(razao_social__startswith="[EXEMPLO]").delete()
        self._reiniciar_numeracao([m for _, m, _ in contagens])
        self.stdout.write(self.style.SUCCESS("Dados de teste apagados. O sistema está pronto para uso."))

    @staticmethod
    def _reiniciar_numeracao(modelos):
        """Os próximos cadastros recomeçam do número 1 (nas tabelas que ficaram vazias)."""
        with connection.cursor() as cursor:
            if connection.vendor == "sqlite":
                tabelas = ", ".join(f"'{m._meta.db_table}'" for m in modelos)
                cursor.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({tabelas})")
            else:
                for sql in connection.ops.sequence_reset_sql(no_style(), modelos):
                    cursor.execute(sql)
