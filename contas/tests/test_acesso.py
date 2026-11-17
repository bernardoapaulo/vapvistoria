"""
Acesso por módulo: o Funcionário só enxerga Clientes, Serviços e Vip/Preparação (central em contas/permissoes.py).
Estes testes rodam com a configuração PADRÃO (sem liberar nada), exceto o que prova a reabilitação de um módulo.
"""
import re
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import override_settings
from django.urls import URLResolver, get_resolver, reverse

from atendimentos.models import Atendimento
from atendimentos.tests.base import BaseAtendimentoTest
from contas import acesso
from contas.permissoes import ACESSO_POR_PERFIL, ADMINISTRADOR, FUNCIONARIO, PAGINA_INICIAL_POR_PERFIL
from servicos.models import TipoServico
from vip_preparacao.models import ItemServicoVip, RegistroVip

PERMITIDOS = {"clientes", "servicos", "vip"}
OCULTOS = set(acesso.MODULOS) - PERMITIDOS - {"admin"}


def rotas():
    """Todas as rotas do projeto (sem o admin do Django), com argumentos de exemplo no lugar dos conversores."""
    def percorrer(resolver, prefixo=""):
        for p in resolver.url_patterns:
            rota = prefixo + str(p.pattern)
            if isinstance(p, URLResolver):
                if not rota.startswith("admin/"):
                    yield from percorrer(p, rota)
            else:
                yield re.sub(r"<[^>]+>", "1", rota)
    return sorted(set(percorrer(get_resolver())))


@override_settings(ACESSO_POR_PERFIL=ACESSO_POR_PERFIL)      # o mapa PADRÃO de produção, não o liberado da base
class BaseAcessoTest(BaseAtendimentoTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.atendimento = Atendimento.objects.create(
            cliente=cls.cliente, tipo_servico=cls.vistoria, veiculo=cls.veiculo, valor_cobrado=Decimal("250.00"),
            registrado_por=cls.admin)
        cls.registro = RegistroVip.objects.create(
            cliente=cls.cliente, placa="VIP1A23", marca="Fiat", modelo="Argo", cor="branco", ano=2021,
            data_preparacao=date.today(), criado_por=cls.admin, alterado_por=cls.admin)
        ItemServicoVip.objects.create(registro=cls.registro, servico=cls.limpeza, valor=Decimal("100.00"))
        cls.registro.valor = Decimal("100.00")
        cls.registro.save()


class CentralDeAcessoTest(BaseAcessoTest):
    def test_toda_rota_pertence_a_um_modulo_ou_e_publica(self):
        """Se alguém criar uma rota fora dos módulos, este teste falha: ela ficaria sem a barreira do perfil."""
        soltas = [r for r in rotas() if "/" + r != "/" and r not in acesso.ROTAS_PUBLICAS
                  and acesso.modulo_da_url("/" + r) is None]
        self.assertEqual(soltas, [])

    def test_mapa_padrao(self):
        self.assertEqual(set(ACESSO_POR_PERFIL[FUNCIONARIO]), PERMITIDOS)
        self.assertEqual(ACESSO_POR_PERFIL[ADMINISTRADOR], "todos")
        self.assertEqual(PAGINA_INICIAL_POR_PERFIL[FUNCIONARIO], "vip_lista")
        self.assertEqual(acesso.modulos_do_usuario(self.func), PERMITIDOS)
        self.assertEqual(acesso.modulos_do_usuario(self.admin), set(acesso.NOMES))

    def test_mudar_a_central_reabilita_um_modulo_sem_tocar_em_views_ou_templates(self):
        self.client.force_login(self.func)
        self.assertEqual(self.client.get(reverse("agenda_calendario")).status_code, 403)
        novo_mapa = {**ACESSO_POR_PERFIL, FUNCIONARIO: ("clientes", "servicos", "vip", "agenda")}   # uma linha
        with override_settings(ACESSO_POR_PERFIL=novo_mapa):
            self.func._modulos_acesso = None                                  # (o cache vale por usuário carregado)
            self.client.force_login(get_user_model().objects.get(pk=self.func.pk))
            self.assertEqual(self.client.get(reverse("agenda_calendario")).status_code, 200)
            self.assertContains(self.client.get(reverse("vip_lista")), reverse("agenda_calendario"))   # aparece no menu
            self.assertEqual(self.client.get(reverse("financeiro")).status_code, 403)                 # os outros seguem ocultos
        self.client.force_login(get_user_model().objects.get(pk=self.func.pk))
        self.assertEqual(self.client.get(reverse("agenda_calendario")).status_code, 403)

    def test_usuario_sem_perfil_nao_enxerga_modulo_nenhum_mas_a_pagina_inicial_abre(self):
        sem = get_user_model().objects.create_user("semperfil", password="x")
        self.client.force_login(sem)
        self.assertEqual(self.client.get(reverse("inicio")).status_code, 200)
        for nome in ("cliente_lista", "vip_lista", "servico_lista", "atendimento_lista"):
            self.assertEqual(self.client.get(reverse(nome)).status_code, 403, nome)


class FuncionarioModulosOcultosTest(BaseAcessoTest):
    def setUp(self):
        self.client.force_login(self.func)

    def test_toda_rota_de_modulo_oculto_devolve_403_em_get_e_em_post(self):
        ocultas = [r for r in rotas() if acesso.modulo_da_url("/" + r) in OCULTOS]
        self.assertGreater(len(ocultas), 40)
        for rota in ocultas:
            self.assertEqual(self.client.get("/" + rota).status_code, 403, f"GET /{rota}")
            self.assertEqual(self.client.post("/" + rota, {}).status_code, 403, f"POST /{rota}")

    def test_endpoints_de_dados_exportacao_e_download_estao_barrados(self):
        for nome, args in (("dashboard_exportar", []), ("relatorio_csv", []), ("agenda_eventos", []),
                           ("despesa_comprovante", [1]), ("aluno_documento", [1, "foto"])):
            self.assertEqual(self.client.get(reverse(nome, args=args)).status_code, 403, nome)
        self.assertEqual(self.client.get("/admin/").status_code, 403)

    def test_os_modulos_permitidos_funcionam(self):
        for nome in ("cliente_lista", "cliente_novo", "servico_lista", "servico_novo", "vip_lista", "vip_novo"):
            self.assertEqual(self.client.get(reverse(nome)).status_code, 200, nome)
        self.assertEqual(self.client.get(reverse("cliente_detalhe", args=[self.cliente.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("servico_detalhe", args=[self.limpeza.pk])).status_code, 200)
        self.assertEqual(self.client.get(self.registro.get_absolute_url()).status_code, 200)

    def test_pagina_403_tem_identidade_e_link_de_volta_para_o_vip(self):
        resposta = self.client.get(reverse("financeiro"))
        self.assertContains(resposta, "Acesso negado", status_code=403)
        self.assertContains(resposta, 'alt="VAP Vistoria"', status_code=403)
        self.assertContains(resposta, f'href="{reverse("vip_lista")}"', status_code=403)

    def test_inicio_leva_o_funcionario_para_o_vip_e_o_login_tambem(self):
        self.assertRedirects(self.client.get(reverse("inicio")), reverse("vip_lista"))
        self.client.logout()
        resposta = self.client.post(reverse("login"), {"username": "func", "password": "x"}, follow=True)
        self.assertEqual(resposta.redirect_chain[-1][0], reverse("vip_lista"))
        self.assertEqual(resposta.status_code, 200)

    def test_menu_so_tem_clientes_servicos_e_vip(self):
        html = self.client.get(reverse("vip_lista")).content.decode()
        menu = html[html.index('id="menu"'):html.index("</aside>")]
        for presente in ("cliente_lista", "servico_lista", "vip_lista"):
            self.assertIn(f'href="{reverse(presente)}"', menu, presente)
        for ausente in ("inicio", "dashboard", "atendimento_lista", "agenda_calendario", "financeiro", "aluno_lista", "veiculo_lista"):
            self.assertNotIn(f'href="{reverse(ausente)}"', menu, ausente)
        self.assertNotIn("Dashboard", menu)
        self.assertNotIn("Financeiro", menu)
        self.assertNotIn("Atendimentos", menu)
        self.assertNotIn("Agenda", menu)
        self.assertNotIn("Alunos", menu)
        self.assertNotIn("Veículos", menu)
        self.assertNotIn("Início", menu)
        self.assertIn("Vip/Preparação", menu)

    def test_administrador_continua_vendo_tudo(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("inicio")).content.decode()
        menu = html[html.index('id="menu"'):html.index("</aside>")]
        for nome in ("inicio", "dashboard", "atendimento_lista", "agenda_calendario", "financeiro", "cliente_lista",
                     "aluno_lista", "veiculo_lista", "servico_lista", "vip_lista"):
            self.assertIn(f'href="{reverse(nome)}"', menu, nome)
        for nome in ("inicio", "dashboard", "atendimento_lista", "agenda_calendario", "financeiro", "aluno_lista", "veiculo_lista", "recebimento_lista"):
            self.assertEqual(self.client.get(reverse(nome)).status_code, 200, nome)


class DetalheDoClienteTest(BaseAcessoTest):
    def test_funcionario_ve_contato_e_registros_vip_sem_dinheiro_nem_links_de_modulos_ocultos(self):
        self.client.force_login(self.func)
        resposta = self.client.get(reverse("cliente_detalhe", args=[self.cliente.pk]))
        html = resposta.content.decode()
        corpo = html[html.index("<main"):]
        self.assertContains(resposta, self.cliente.nome)
        self.assertContains(resposta, "Dados do cliente")
        self.assertContains(resposta, "ABC1234")                               # veículos: só texto
        self.assertContains(resposta, "VIP1A23")                               # registros Vip do cliente
        self.assertContains(resposta, "Vip/Preparação")
        for oculto in ("Histórico de serviços", "Próximo agendamento", "Total", "R$", "Adicionar veículo"):
            self.assertNotIn(oculto, corpo, oculto)
        for prefixo in ("/atendimentos/", "/agenda/", "/veiculos/", "/financeiro/", "/dashboard/", "/alunos/"):
            self.assertNotIn(f'href="{prefixo}', corpo, prefixo)
        self.assertNotIn("250,00", corpo)

    def test_funcionario_nem_consulta_o_historico_de_atendimentos(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self.client.force_login(self.func)
        with CaptureQueriesContext(connection) as q:
            self.client.get(reverse("cliente_detalhe", args=[self.cliente.pk]))
        sql = " ".join(x["sql"].lower() for x in q)
        self.assertNotIn("atendimentos_atendimento", sql)
        self.assertNotIn("agenda_agendamento", sql)

    def test_administrador_ve_historico_total_e_valores(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("cliente_detalhe", args=[self.cliente.pk])).content.decode()
        for esperado in ("Histórico de serviços", "250,00", "VIP1A23", "100,00", "Próximo agendamento"):
            self.assertIn(esperado, html, esperado)


class AutocompletesInternosTest(BaseAcessoTest):
    def test_busca_de_cliente_e_modal_de_servicos_funcionam_para_o_funcionario(self):
        self.client.force_login(self.func)
        pagina = self.client.get(reverse("vip_novo"))
        self.assertContains(pagina, self.cliente.nome)                         # lista de clientes do autocompletar
        self.assertContains(pagina, 'data-servico-opcao')                      # pop-up de serviços
        self.assertContains(pagina, "Limpeza")

    def test_veiculo_por_placa_devolve_so_o_necessario(self):
        self.client.force_login(self.func)
        dados = self.client.get(reverse("vip_veiculo"), {"placa": "abc-1234"}).json()
        self.assertEqual(set(dados), {"encontrado", "marca", "modelo", "ano", "chassi", "cor", "cor_outra"})
        self.assertEqual((dados["encontrado"], dados["marca"], dados["modelo"]), (True, "Fiat", "Uno"))
        self.assertNotIn(self.cliente.nome, str(dados))                        # nada do proprietário nem de atendimentos
        self.assertEqual(self.client.get(reverse("vip_veiculo"), {"placa": "ZZZ9999"}).json(), {"encontrado": False})

    def test_cadastrar_novo_cliente_volta_para_o_formulario_vip(self):
        self.client.force_login(self.func)
        resposta = self.client.post(f"{reverse('cliente_novo')}?next={reverse('vip_novo')}",
                                    {"nome": "Cliente Novo", "telefone": "11999990000", "data_cadastro": date.today().isoformat()})
        from cadastros.models import Cliente
        novo = Cliente.objects.get(nome="Cliente Novo")
        self.assertRedirects(resposta, f"{reverse('vip_novo')}?cliente={novo.pk}")

    def test_retorno_do_cadastro_so_aceita_enderecos_do_proprio_site(self):
        self.client.force_login(self.func)
        resposta = self.client.post(f"{reverse('cliente_novo')}?next=https://exemplo.com/roubo",
                                    {"nome": "Cliente Dois", "telefone": "11999990001", "data_cadastro": date.today().isoformat()})
        self.assertNotIn("exemplo.com", resposta["Location"])


class VipParaOFuncionarioTest(BaseAcessoTest):
    def preparar(self, **extra):
        return {"valor": "100.00", "forma": "pix", "data": date.today().isoformat(), **extra}

    def test_funcionario_conclui_e_nao_ve_aviso_nem_link_do_financeiro(self):
        self.client.force_login(self.func)
        resposta = self.client.post(reverse("vip_concluir", args=[self.registro.pk]), self.preparar(), follow=True)
        textos = " ".join(str(m) for m in get_messages(resposta.wsgi_request))
        self.assertIn("Registro concluído.", textos)
        self.assertNotIn("Financeiro", textos)
        self.registro.refresh_from_db()
        self.assertEqual(self.registro.status, "concluido")
        self.assertEqual(self.registro.atendimentos.count(), 1)                # o recebimento foi lançado "por baixo"
        corpo = resposta.content.decode()
        corpo = corpo[corpo.index("<main"):]
        self.assertNotIn("/atendimentos/", corpo)
        self.assertNotIn("/financeiro/", corpo)
        self.assertNotIn("Atendimento gerado", corpo)

    def test_administrador_ve_o_aviso_do_financeiro_e_o_link_do_atendimento(self):
        self.client.force_login(self.admin)
        resposta = self.client.post(reverse("vip_concluir", args=[self.registro.pk]), self.preparar(), follow=True)
        textos = " ".join(str(m) for m in get_messages(resposta.wsgi_request))
        self.assertIn("lançados no Financeiro", textos)
        self.assertContains(resposta, "/atendimentos/")

    def test_funcionario_ve_os_valores_do_registro_em_somente_leitura(self):
        self.client.force_login(self.func)
        self.assertContains(self.client.get(self.registro.get_absolute_url()), "R$ 100,00")
        pagina = self.client.get(reverse("vip_editar", args=[self.registro.pk]))
        self.assertRegex(pagina.content.decode(), r'<input[^>]*name="itens-0-valor"[^>]*disabled')


class ServicosParaOFuncionarioTest(BaseAcessoTest):
    def test_funcionario_cadastra_e_consulta_servicos_mas_nao_edita_nem_exclui(self):
        self.client.force_login(self.func)
        lista = self.client.get(reverse("servico_lista"))
        self.assertContains(lista, "Novo serviço")
        self.assertContains(lista, "Limpeza")
        resposta = self.client.post(reverse("servico_novo"), {
            "nome": "Cristalização", "categoria": "limpeza", "valor_padrao": "220.00", "ativo": "on"})
        novo = TipoServico.objects.get(nome="Cristalização")
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual((novo.valor_padrao, novo.criado_por), (Decimal("220.00"), self.func))
        self.assertContains(self.client.get(novo.get_absolute_url()), "220")              # vê o valor padrão
        self.assertContains(self.client.get(novo.get_absolute_url()), "Cadastrado por")
        self.assertEqual(self.client.get(reverse("servico_editar", args=[novo.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("servico_editar", args=[novo.pk]), {"nome": "x"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("servico_excluir", args=[novo.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("servico_excluir", args=[novo.pk])).status_code, 403)
        self.assertTrue(TipoServico.objects.filter(pk=novo.pk).exists())

    def test_servico_cadastrado_pelo_funcionario_aparece_no_vip(self):
        self.client.force_login(self.func)
        self.client.post(reverse("servico_novo"), {"nome": "Higienização", "categoria": "limpeza", "valor_padrao": "90.00", "ativo": "on"})
        self.assertContains(self.client.get(reverse("vip_novo")), "Higienização")
