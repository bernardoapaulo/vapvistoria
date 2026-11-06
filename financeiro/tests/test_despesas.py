import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from financeiro import regras
from financeiro.forms import DespesaForm
from financeiro.models import CategoriaDespesa, Despesa, RegistroAuditoria

from .base import BaseFinanceiroTest, d


def dados_despesa(categoria, **extra):
    dados = {"descricao": "Conta de teste", "categoria": categoria.pk, "valor": "100.00",
             "vencimento": "2025-05-10", "fornecedor": "Fornecedor X"}
    dados.update(extra)
    return dados


class CategoriasPadraoTest(BaseFinanceiroTest):
    def test_categorias_padrao_ja_existem(self):
        nomes = set(CategoriaDespesa.objects.values_list("nome", flat=True))
        for esperado in ("Aluguel", "Água/Luz/Internet", "Salários e encargos", "Impostos e taxas", "Material de limpeza",
                         "Peças e reparos", "Combustível", "Equipamentos", "Marketing", "Manutenção",
                         "Instrutores/cursos", "Outros"):
            self.assertIn(esperado, nomes)

    def test_administrador_edita_categorias(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("categoria_despesa_novo"), {"nome": "Seguros", "ativa": "on"})
        self.assertTrue(CategoriaDespesa.objects.filter(nome="Seguros").exists())
        resp = self.client.post(reverse("categoria_despesa_novo"), {"nome": "Seguros", "ativa": "on"})
        self.assertContains(resp, "Já existe uma categoria com este nome")

    def test_categoria_com_despesas_nao_pode_ser_excluida(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("categoria_despesa_excluir", args=[self.cat["Aluguel"].pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(CategoriaDespesa.objects.filter(pk=self.cat["Aluguel"].pk).exists())


class ValidacaoDespesaTest(BaseFinanceiroTest):
    def _form(self, **extra):
        return DespesaForm(dados_despesa(self.cat["Outros"], **extra), usuario=self.admin)

    def test_valor_zero_negativo_ou_invalido(self):
        for valor, trecho in (("0", "maior que zero"), ("-10", "maior que zero"), ("abc", "valor válido")):
            form = self._form(valor=valor)
            self.assertFalse(form.is_valid())
            self.assertIn(trecho, form.errors["valor"][0])

    def test_campos_obrigatorios_em_portugues(self):
        form = DespesaForm({}, usuario=self.admin)
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["descricao"][0], "Informe a descrição.")
        self.assertEqual(form.errors["categoria"][0], "Escolha a categoria.")
        self.assertEqual(form.errors["valor"][0], "Informe o valor.")

    def test_paga_exige_forma_e_nao_pode_ser_no_futuro(self):
        self.assertIn("forma de pagamento", " ".join(self._form(data_pagamento="2025-05-10").non_field_errors()))
        amanha = (timezone.localdate() + timedelta(days=1)).isoformat()
        form = self._form(data_pagamento=amanha, forma_pagamento="pix")
        self.assertIn("no futuro", " ".join(form.non_field_errors()))

    def test_criar_pela_tela_grava_auditoria_e_quem_criou(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("despesa_novo"), dados_despesa(self.cat["Outros"], tipo_servico=self.limpeza.pk))
        despesa = Despesa.objects.get(descricao="Conta de teste")
        self.assertRedirects(resp, despesa.get_absolute_url())
        self.assertEqual((despesa.criado_por, despesa.alterado_por, despesa.tipo_servico), (self.admin, self.admin, self.limpeza))
        self.assertTrue(RegistroAuditoria.objects.filter(entidade="despesa", objeto_id=despesa.pk, acao="criado").exists())

    def test_alteracao_de_valor_entra_na_auditoria(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("despesa_editar", args=[self.d5.pk]), dados_despesa(
            self.cat["Outros"], descricao=self.d5.descricao, valor="175.50", vencimento="2025-04-20"))
        self.recarregar(self.d5)
        self.assertEqual(self.d5.valor, Decimal("175.50"))
        registro = RegistroAuditoria.objects.get(entidade="despesa", objeto_id=self.d5.pk, acao="alterado")
        self.assertIn("valor: R$ 150,00 → R$ 175,50", registro.descricao)

    def test_marcar_como_paga(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("despesa_pagar", args=[self.d3.pk]), {"forma": "pix", "data": "2025-04-01"})
        self.assertEqual(resp.status_code, 302)
        self.recarregar(self.d3)
        self.assertEqual((self.d3.data_pagamento, self.d3.forma_pagamento), (date(2025, 4, 1), "pix"))
        with self.assertRaises(ValidationError):  # já paga
            regras.pagar_despesa(self.d3, d(2, 4), "pix", self.admin)
        self.assertTrue(RegistroAuditoria.objects.filter(entidade="despesa", objeto_id=self.d3.pk, acao="pago").exists())

    def test_marcar_como_paga_exige_forma(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("despesa_pagar", args=[self.d3.pk]), {"data": "2025-04-01"})
        self.recarregar(self.d3)
        self.assertIsNone(self.d3.data_pagamento)

    def test_exclusao_so_com_permissao_e_fica_na_auditoria(self):
        self.client.force_login(self.admin)
        url = reverse("despesa_excluir", args=[self.d5.pk])
        self.assertContains(self.client.get(url), "Tem certeza")
        self.client.post(url)
        self.assertFalse(Despesa.objects.filter(pk=self.d5.pk).exists())
        self.assertTrue(RegistroAuditoria.objects.filter(entidade="despesa", objeto_id=self.d5.pk, acao="excluido").exists())
        self.client.force_login(self.func)
        self.assertEqual(self.client.post(reverse("despesa_excluir", args=[self.d6.pk])).status_code, 403)
        self.assertTrue(Despesa.objects.filter(pk=self.d6.pk).exists())


class RecorrenciaTest(BaseFinanceiroTest):
    def _modelo(self):
        return self.despesa("Aluguel", 900, d(31, 1), d(31, 1), recorrente=True, descricao="Aluguel mensal")

    def test_gera_os_proximos_meses_no_mesmo_dia(self):
        modelo = self._modelo()
        criadas = regras.gerar_recorrentes(hoje=d(31, 1), meses_a_frente=2)
        self.assertEqual(criadas, 2)
        vencimentos = sorted(modelo.recorrencias.values_list("vencimento", flat=True))
        self.assertEqual(vencimentos, [d(28, 2), d(31, 3)])  # dia 31 vira 28 em fevereiro
        filha = modelo.recorrencias.first()
        self.assertEqual((filha.descricao, filha.valor, filha.categoria, filha.data_pagamento, filha.recorrente),
                         ("Aluguel mensal", Decimal("900.00"), self.cat["Aluguel"], None, False))

    def test_rodar_de_novo_nao_duplica(self):
        modelo = self._modelo()
        regras.gerar_recorrentes(hoje=d(31, 1), meses_a_frente=2)
        self.assertEqual(regras.gerar_recorrentes(hoje=d(31, 1), meses_a_frente=2), 0)
        self.assertEqual(modelo.recorrencias.count(), 2)
        # um mês depois gera só o mês novo
        self.assertEqual(regras.gerar_recorrentes(hoje=d(28, 2), meses_a_frente=2), 1)
        self.assertEqual(modelo.recorrencias.count(), 3)

    def test_mes_com_despesa_editada_e_pulado(self):
        modelo = self._modelo()
        regras.gerar_recorrentes(hoje=d(31, 1), meses_a_frente=1)
        fev = modelo.recorrencias.get()
        fev.vencimento = d(10, 2)  # o usuário mudou o dia: continua sendo a de fevereiro
        fev.save()
        self.assertEqual(regras.gerar_recorrentes(hoje=d(31, 1), meses_a_frente=1), 0)

    def test_nao_gera_em_mes_fechado(self):
        self._modelo()
        regras.fechar_mes(d(1, 2), self.admin)
        regras.gerar_recorrentes(hoje=d(31, 1), meses_a_frente=1)
        self.assertEqual(Despesa.objects.filter(origem__isnull=False).count(), 0)

    def test_banco_barra_duplicata_da_mesma_recorrencia(self):
        from django.db import IntegrityError, transaction
        modelo = self._modelo()
        regras.gerar_recorrentes(hoje=d(31, 1), meses_a_frente=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Despesa.objects.create(descricao="x", categoria=modelo.categoria, valor=1, vencimento=d(28, 2), origem=modelo)

    def test_comando_de_gerenciamento_gera_e_nao_duplica(self):
        from django.core.management import call_command
        self.despesa("Aluguel", 900, timezone.localdate(), timezone.localdate(), recorrente=True)
        call_command("gerar_despesas_recorrentes", "--meses", "2", stdout=mock.MagicMock())
        total = Despesa.objects.filter(origem__isnull=False).count()
        self.assertEqual(total, 2)
        call_command("gerar_despesas_recorrentes", "--meses", "2", stdout=mock.MagicMock())
        self.assertEqual(Despesa.objects.filter(origem__isnull=False).count(), total)

    def test_abrir_contas_a_pagar_gera_as_recorrentes(self):
        self.despesa("Aluguel", 900, timezone.localdate(), timezone.localdate(), recorrente=True)
        self.client.force_login(self.admin)
        self.client.get(reverse("contas_pagar"))
        self.assertEqual(Despesa.objects.filter(origem__isnull=False).count(), 2)
        self.client.get(reverse("contas_pagar"))
        self.assertEqual(Despesa.objects.filter(origem__isnull=False).count(), 2)


class ComprovanteTest(BaseFinanceiroTest):
    def setUp(self):
        super().setUp()
        self.pasta = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.pasta, ignore_errors=True)
        patcher = mock.patch.object(Despesa._meta.get_field("comprovante"), "storage", FileSystemStorage(location=self.pasta))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _enviar(self, nome, conteudo):
        form = DespesaForm(dados_despesa(self.cat["Outros"]), {"comprovante": SimpleUploadedFile(nome, conteudo)}, usuario=self.admin)
        return form

    def test_aceita_pdf_e_imagens(self):
        for nome, conteudo in (("nota.pdf", b"%PDF-1.4 teste"), ("foto.PNG", b"\x89PNG\r\n\x1a\n...."), ("foto.jpg", b"\xff\xd8\xff\xe0....")):
            self.assertTrue(self._enviar(nome, conteudo).is_valid(), nome)

    def test_recusa_tipo_nao_permitido_e_conteudo_falso(self):
        self.assertIn("Tipo de arquivo não permitido", self._enviar("virus.exe", b"MZ....").errors["comprovante"][0])
        self.assertIn("não corresponde", self._enviar("falso.pdf", b"isto nao e pdf").errors["comprovante"][0])
        self.assertIn("não corresponde", self._enviar("falso.png", b"%PDF-1.4").errors["comprovante"][0])

    def test_recusa_arquivo_grande(self):
        grande = b"%PDF" + b"0" * (5 * 1024 * 1024)
        self.assertIn("maior que 5 MB", self._enviar("grande.pdf", grande).errors["comprovante"][0])

    def test_arquivo_fica_fora_de_pastas_publicas_e_so_sai_pela_view(self):
        from django.conf import settings
        self.client.force_login(self.admin)
        arquivo = SimpleUploadedFile("nota.pdf", b"%PDF-1.4 conteudo")
        self.client.post(reverse("despesa_novo"), {**dados_despesa(self.cat["Outros"]), "comprovante": arquivo})
        despesa = Despesa.objects.get(descricao="Conta de teste")
        self.assertTrue(despesa.comprovante.name.startswith("comprovantes/"))
        self.assertNotIn("nota", despesa.comprovante.name)  # nome original não é exposto
        self.assertTrue(despesa.comprovante.path.startswith(self.pasta))
        self.assertFalse(str(settings.ARQUIVOS_PRIVADOS_ROOT).startswith(str(settings.STATICFILES_DIRS[0])))
        self.assertNotEqual(str(settings.ARQUIVOS_PRIVADOS_ROOT), str(settings.MEDIA_ROOT))

        url = reverse("despesa_comprovante", args=[despesa.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(b"".join(resp.streaming_content), b"%PDF-1.4 conteudo")
        self.assertEqual(resp["X-Content-Type-Options"], "nosniff")
        self.assertEqual(resp["Content-Type"], "application/pdf")

        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)  # anônimo vai para o login
        self.client.force_login(self.func)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_excluir_despesa_remove_o_arquivo(self):
        import os
        self.client.force_login(self.admin)
        arquivo = SimpleUploadedFile("nota.pdf", b"%PDF-1.4 conteudo")
        self.client.post(reverse("despesa_novo"), {**dados_despesa(self.cat["Outros"]), "comprovante": arquivo})
        despesa = Despesa.objects.get(descricao="Conta de teste")
        caminho = despesa.comprovante.path
        self.assertTrue(os.path.exists(caminho))
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("despesa_excluir", args=[despesa.pk]))
        self.assertFalse(os.path.exists(caminho))
