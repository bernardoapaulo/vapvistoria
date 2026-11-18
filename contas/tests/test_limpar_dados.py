"""Limpeza dos dados de teste: apaga o que é fictício, mantém usuários reais, grupos e categorias, e é segura."""
import os
import shutil
import tempfile
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase

from agenda.models import Agendamento, HorarioFuncionamento
from atendimentos.models import Atendimento, HistoricoAtendimento
from cadastros.models import Cliente, Veiculo
from contas.permissoes import FUNCIONARIO
from financeiro.models import CategoriaDespesa, Despesa, FechamentoMes, Recebimento, RegistroAuditoria
from servicos.models import TipoServico
from regravacoes.models import (
    AnexoRegravacao, ConfiguracaoEmpresa, DocumentoEmitido, Parceiro, RegistroRegravacao, SequenciaDocumento, Tecnico,
)
from vip_preparacao.models import FotoVip, ItemServicoVip, RegistroVip

Usuario = get_user_model()
MODELOS = (FotoVip, ItemServicoVip, RegistroVip, DocumentoEmitido, SequenciaDocumento, AnexoRegravacao, RegistroRegravacao,
           Parceiro, Tecnico, Agendamento, Recebimento, Despesa, FechamentoMes, RegistroAuditoria,
           HistoricoAtendimento, Atendimento, Veiculo, Cliente, TipoServico)


def rodar(*args, **kw):
    saida = StringIO()
    call_command("limpar_dados_teste", *args, stdout=saida, **kw)
    return saida.getvalue()


class LimpezaDosDadosDeTesteTest(TestCase):
    def setUp(self):
        self.pasta = tempfile.mkdtemp(prefix="limpeza_")
        self.addCleanup(shutil.rmtree, self.pasta, ignore_errors=True)
        armazenamentos = [FotoVip._meta.get_field(n).storage for n in ("imagem", "miniatura")] +                          [AnexoRegravacao._meta.get_field(n).storage for n in ("arquivo", "miniatura")]
        for armazenamento in armazenamentos:           # as fotos e anexos de exemplo vão para uma pasta temporária
            for atributo in ("base_location", "location"):
                armazenamento.__dict__[atributo] = self.pasta
            self.addCleanup(lambda a=armazenamento: [a.__dict__.pop(k, None) for k in ("base_location", "location")])
        call_command("popular_dados", stdout=StringIO())
        self.real = Usuario.objects.create_user("maria_real", password="Senha#Forte2026")
        self.real.groups.add(Group.objects.get(name=FUNCIONARIO))

    def arquivos(self):
        return [os.path.join(r, f) for r, _, fs in os.walk(self.pasta) for f in fs]

    def test_sem_confirmar_so_simula_e_nao_apaga_nada(self):
        antes = {m: m.objects.count() for m in MODELOS}
        saida = rodar()
        self.assertIn("SIMULAÇÃO", saida)
        self.assertIn("--confirmar", saida)
        self.assertEqual({m: m.objects.count() for m in MODELOS}, antes)
        self.assertGreater(antes[Cliente], 0)
        self.assertTrue(Usuario.objects.filter(username="funcionario_teste").exists())

    def test_confirmar_apaga_os_dados_de_teste_e_mantem_o_que_importa(self):
        self.assertTrue(self.arquivos())               # há fotos de exemplo gravadas
        horario = list(HorarioFuncionamento.objects.values_list("pk", flat=True))
        categorias = CategoriaDespesa.objects.count()
        saida = rodar(confirmar=True)
        self.assertIn("pronto para uso", saida)
        for modelo in MODELOS:
            self.assertEqual(modelo.objects.count(), 0, modelo.__name__)
        self.assertEqual(self.arquivos(), [])                                   # fotos apagadas do armazenamento
        # fica: usuários reais (e o admin), grupos, categorias de despesa e horário de funcionamento
        self.assertTrue(Usuario.objects.filter(username="admin_teste").exists())
        self.assertTrue(Usuario.objects.filter(username="maria_real").exists())
        self.assertFalse(Usuario.objects.filter(username="funcionario_teste").exists())
        self.assertEqual(Group.objects.filter(name__in=["Administrador", "Funcionário"]).count(), 2)
        self.assertEqual(ConfiguracaoEmpresa.obter().razao_social, "")                     # a empresa de EXEMPLO foi apagada
        self.assertEqual(CategoriaDespesa.objects.count(), categorias)
        self.assertEqual(list(HorarioFuncionamento.objects.values_list("pk", flat=True)), horario)

    def test_empresa_real_ja_configurada_nao_e_apagada(self):
        cfg = ConfiguracaoEmpresa.obter()
        cfg.razao_social = "Empresa Real Configurada Ltda"
        cfg.save()
        rodar(confirmar=True)
        self.assertEqual(ConfiguracaoEmpresa.obter().razao_social, "Empresa Real Configurada Ltda")

    def test_depois_de_limpo_o_sistema_funciona_e_a_numeracao_recomeca(self):
        rodar(confirmar=True)
        cliente = Cliente.objects.create(nome="Cliente de Verdade", telefone="11999990000")
        servico = TipoServico.objects.create(nome="Serviço real", categoria="limpeza", valor_padrao="99.00")
        self.assertEqual((cliente.pk, servico.pk), (1, 1))
        self.client.force_login(Usuario.objects.get(username="admin_teste"))
        for nome in ("inicio", "dashboard", "atendimento_lista", "financeiro", "vip_lista", "cliente_lista", "servico_lista", "agenda_calendario",
                     "regravacao_lista", "parceiro_lista", "tecnico_lista", "empresa"):
            from django.urls import reverse
            self.assertEqual(self.client.get(reverse(nome)).status_code, 200, nome)

    def test_modo_do_deploy_so_age_com_dados_ficticios_e_depois_nao_apaga_dados_reais(self):
        self.assertIn("pronto para uso", rodar(confirmar=True, somente_se_ficticio=True))
        Cliente.objects.create(nome="Cliente de Verdade", telefone="11999990000")
        TipoServico.objects.create(nome="Serviço real", categoria="limpeza", valor_padrao="99.00")
        saida = rodar(confirmar=True, somente_se_ficticio=True)                    # um novo deploy, variável ainda ligada
        self.assertIn("nada a limpar", saida)
        self.assertEqual((Cliente.objects.count(), TipoServico.objects.count()), (1, 1))
