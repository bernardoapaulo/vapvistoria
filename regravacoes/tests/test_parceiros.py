from decimal import Decimal

from django.urls import reverse

from cadastros.models import Cliente
from regravacoes import regras
from regravacoes.models import Parceiro

from .base import BaseRegravacaoTest

D = Decimal


class ParceiroTest(BaseRegravacaoTest):
    def setUp(self):
        super().setUp()
        self.p = Parceiro.objects.create(nome="Parceiro Contagem", empresa_profissao="Despachante")
        self.c2 = Cliente.objects.create(nome="Cliente Dois", telefone="2")
        self.c3 = Cliente.objects.create(nome="Cliente Três", telefone="3")
        # c1 indicou 2 regravações, c2 uma, c3 uma cancelada; uma de OUTRO parceiro não conta
        self.a = self.registro(parceiro=self.p, placa="PAR1A23")
        self.b = self.registro(parceiro=self.p, placa="PAR2A23")
        self.c = self.registro(parceiro=self.p, placa="PAR3A23", cliente=self.c2)
        self.d = self.registro(parceiro=self.p, placa="PAR4A23", cliente=self.c3, cancelada=True)
        self.e = self.registro(parceiro=self.parceiro, placa="PAR5A23", cliente=self.c3)
        self.client.force_login(self.admin)

    def lancar(self, r, valor, data_receb=None):
        r.valor, r.data_concluida, r.tecnico = D(valor), self.dias(-2), self.tecnico
        r.recebimento_situacao, r.forma_pagamento, r.data_recebimento = "recebido", "pix", data_receb or self.dias(-1)
        r.save()
        regras.lancar(r, self.admin)

    def test_conta_indicacoes_e_clientes_indicados_sem_repetir_e_sem_cancelados(self):
        ctx = self.client.get(self.p.get_absolute_url()).context
        self.assertEqual(ctx["total_indicacoes"], 3)                      # a, b, c (d cancelada fica de fora)
        self.assertEqual(ctx["total_clientes"], 2)                         # cliente 1 e cliente 2
        self.assertEqual({c.nome: c.indicacoes for c in ctx["clientes_indicados"]}, {self.cliente.nome: 2, "Cliente Dois": 1})

    def test_lista_mostra_as_contagens(self):
        parceiro = [x for x in self.client.get(reverse("parceiro_lista")).context["object_list"] if x.pk == self.p.pk][0]
        self.assertEqual((parceiro.total_indicacoes, parceiro.total_clientes), (3, 2))

    def test_total_faturado_so_das_concluidas_e_recebidas(self):
        self.lancar(self.a, "400.00")
        self.lancar(self.c, "450.50")
        ctx = self.client.get(self.p.get_absolute_url()).context
        self.assertEqual(ctx["total_faturado"], D("850.50"))
        self.assertEqual(ctx["total_concluidas"], 2)
        self.assertContains(self.client.get(self.p.get_absolute_url()), "R$ 850,50")

    def test_filtro_por_periodo(self):
        self.lancar(self.a, "400.00")
        ontem = self.dias(-1).isoformat()
        futuro = self.dias(30).isoformat()
        self.assertEqual(self.client.get(self.p.get_absolute_url(), {"de": futuro}).context["total_indicacoes"], 0)
        self.assertEqual(self.client.get(self.p.get_absolute_url(), {"de": ontem}).context["total_indicacoes"], 3)
        self.assertEqual(self.client.get(self.p.get_absolute_url(), {"de": "lixo"}).status_code, 200)

    def test_valor_faturado_so_para_quem_tem_a_permissao(self):
        from contas.permissoes import ADMINISTRADOR, FUNCIONARIO
        from django.contrib.auth.models import Group, Permission
        self.lancar(self.a, "400.00")
        grupo = Group.objects.get(name=FUNCIONARIO)
        grupo.permissions.add(Permission.objects.get(codename="view_parceiro"))
        from django.test import override_settings
        ACESSO = {ADMINISTRADOR: "todos", FUNCIONARIO: ("clientes", "regravacoes")}
        with override_settings(ACESSO_POR_PERFIL=ACESSO):
            from django.contrib.auth import get_user_model
            self.client.force_login(get_user_model().objects.get(pk=self.func.pk))
            ctx = self.client.get(self.p.get_absolute_url()).context
            self.assertNotIn("total_faturado", ctx)
            self.assertNotContains(self.client.get(self.p.get_absolute_url()), "Total faturado")

    def test_cliente_indicado_fica_vinculado_ao_parceiro_pelo_registro(self):
        self.client.post(reverse("regravacao_novo"), self.dados_form(parceiro=self.p.pk, cliente=self.c2.pk, placa="VIN1A23"))
        self.assertEqual(self.client.get(self.p.get_absolute_url()).context["total_indicacoes"], 4)

    def test_parceiro_novo_volta_para_o_formulario_com_o_parceiro_escolhido(self):
        resposta = self.client.post(f"{reverse('parceiro_novo')}?next={reverse('regravacao_novo')}", {"nome": "Parceiro Criado no Form", "ativo": "on"})
        novo = Parceiro.objects.get(nome="Parceiro Criado no Form")
        self.assertRedirects(resposta, f"{reverse('regravacao_novo')}?parceiro={novo.pk}")
        pagina = self.client.get(f"{reverse('regravacao_novo')}?parceiro={novo.pk}")
        self.assertEqual(pagina.context["form"].initial["parceiro"], novo.pk)

    def test_retorno_so_aceita_enderecos_do_proprio_site(self):
        resposta = self.client.post(f"{reverse('parceiro_novo')}?next=https://exemplo.com/x", {"nome": "Outro", "ativo": "on"})
        self.assertNotIn("exemplo.com", resposta["Location"])

    def test_desativar_nao_apaga_e_sai_da_lista_de_escolha(self):
        self.client.post(reverse("parceiro_ativo", args=[self.p.pk]))
        self.p.refresh_from_db()
        self.assertFalse(self.p.ativo)
        self.assertEqual(self.a.__class__.objects.get(pk=self.a.pk).parceiro, self.p)             # os registros continuam ligados
        form = self.client.get(reverse("regravacao_novo")).context["form"]
        self.assertNotIn(self.p, form.fields["parceiro"].queryset)
        editar = self.client.get(reverse("regravacao_editar", args=[self.a.pk])).context["form"]
        self.assertIn(self.p, editar.fields["parceiro"].queryset)                                # mas o registro antigo o mantém

    def test_parceiro_ativo_inativo_e_busca(self):
        Parceiro.objects.create(nome="Inativo Antigo", ativo=False)
        nomes = lambda **q: [x.nome for x in self.client.get(reverse("parceiro_lista"), q).context["object_list"]]
        self.assertNotIn("Inativo Antigo", nomes())
        self.assertIn("Inativo Antigo", nomes(situacao="todos"))
        self.assertEqual(nomes(q="contagem"), ["Parceiro Contagem"])
