import threading
import time
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, connection, transaction
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from regravacoes.documentos import emissao
from regravacoes.models import ConfiguracaoEmpresa, DocumentoEmitido, SequenciaDocumento

from .base import BaseRegravacaoTest, texto_do_pdf

Tipo = DocumentoEmitido.Tipo


class DeclaracaoTest(BaseRegravacaoTest):
    def emitir(self, r, tipo=Tipo.DECLARACAO):
        return emissao.emitir(r, tipo, self.admin)

    def test_bloqueada_sem_a_autorizacao_correspondente(self):
        r = self.registro(data_concluida=self.dias(-1), tecnico=self.tecnico, servico_motor=True, servico_chassi=True)
        self.anexar(r, "autorizacao_motor")                      # falta a do chassi
        with self.assertRaises(ValidationError) as erro:
            self.emitir(r)
        self.assertIn("Autorização de Chassi", " ".join(erro.exception.messages))
        self.assertIn("autorização do Detran em anexo", " ".join(erro.exception.messages))
        self.assertEqual(DocumentoEmitido.objects.count(), 0)

    def test_bloqueada_sem_dados_obrigatorios_e_sem_conclusao(self):
        r = self.registro(proprietario="", marca="", numero_motor="", servico_motor=True, servico_chassi=False,
                          chassi="", data_concluida=None)
        mensagens = " ".join(emissao.exigencias(r, Tipo.DECLARACAO))
        for esperado in ("concluída", "proprietário", "a marca", "número do motor"):
            self.assertIn(esperado, mensagens)
        r2 = self.registro(servico_chassi=True, chassi="123", data_concluida=self.dias(-1), tecnico=self.tecnico, placa="CHS1A23")
        self.assertIn("número do chassi", " ".join(emissao.exigencias(r2, Tipo.DECLARACAO)))

    def test_bloqueada_com_a_empresa_incompleta(self):
        cfg = ConfiguracaoEmpresa.obter()
        cfg.cnpj = ""
        cfg.save()
        mensagens = " ".join(emissao.exigencias(self.completa(), Tipo.DECLARACAO, cfg))
        self.assertIn("aba Empresa", mensagens)
        self.assertIn("CNPJ", mensagens)

    def test_texto_para_motor_chassi_e_ambos(self):
        casos = ((True, False, "Regravação de Motor"), (False, True, "Regravação de Chassi"), (True, True, "Regravação de Motor e Chassi"))
        for i, (motor, chassi, nome) in enumerate(casos):
            r = self.completa(servico_motor=motor, servico_chassi=chassi, placa=f"TXT{i}A23")
            documento, novo = self.emitir(r)
            texto = texto_do_pdf(documento.pdf)
            self.assertTrue(novo)
            self.assertIn("DECLARAÇÃO", texto)
            self.assertIn(nome, texto)
            self.assertIn("PASSOU", texto)
            self.assertIn("autorização do Detran em anexo", texto)
            self.assertIn("Empresa de Teste Ltda - ME", texto)               # dados vêm da configuração
            self.assertIn("11.222.333/0001-81", texto)
            self.assertIn("Fulano de Teste".upper(), texto)                  # proprietário, como consta no documento
            self.assertEqual("Regravação Chassi" in texto, chassi)
            self.assertEqual("Regravação Motor" in texto, motor and not chassi or motor)
            self.assertIn("Técnico de Teste", texto)
            self.assertIn("(Solicitante)", texto)

    def test_solicitante_o_mesmo_ou_o_cliente(self):
        igual = self.completa(proprietario_e_cliente=True, placa="IGU1A23")
        self.assertIn("O MESMO", texto_do_pdf(self.emitir(igual)[0].pdf))
        outro = self.completa(proprietario_e_cliente=False, placa="OUT1A23")
        texto = texto_do_pdf(self.emitir(outro)[0].pdf)
        self.assertIn(self.cliente.nome.upper(), texto)                       # solicitante = cliente indicado
        self.assertNotIn("O MESMO", texto)

    def test_nao_inclui_cpf_nem_telefone_do_cliente(self):
        self.cliente.cpf_cnpj, self.cliente.telefone = "529.982.247-25", "(11) 98888-7777"
        self.cliente.save()
        texto = texto_do_pdf(self.emitir(self.completa())[0].pdf)
        self.assertNotIn("529.982.247-25", texto)
        self.assertNotIn("98888", texto)

    def test_sem_qr_code_e_com_rodape_de_emissao(self):
        documento, _ = self.emitir(self.completa())
        self.assertNotIn(b"/Subtype /Image /Width 21", bytes(documento.pdf))
        texto = texto_do_pdf(documento.pdf)
        self.assertIn(f"Documento nº {documento.numero}", texto)
        self.assertIn("Rodapé de teste", texto)

    def test_numeracao_sequencial_por_ano_e_por_tipo(self):
        ano = timezone.localdate().year
        numeros = [self.emitir(self.completa(placa=f"SEQ{i}A23"))[0].numero for i in range(3)]
        self.assertEqual(numeros, [f"{ano}/0001", f"{ano}/0002", f"{ano}/0003"])
        r = self.registro(recebimento_situacao="recebido", forma_pagamento="pix", data_recebimento=self.dias(0), placa="REC1A23")
        self.assertEqual(self.emitir(r, Tipo.RECIBO)[0].numero, f"{ano}/0001")    # cada tipo tem a sua sequência
        pronta = self.completa(placa="NOV1A23")
        from datetime import date
        from unittest import mock
        with mock.patch.object(emissao.timezone, "localdate", return_value=date(ano + 1, 1, 5)):   # vira o ano
            self.assertEqual(self.emitir(pronta)[0].numero, f"{ano + 1}/0001")                    # recomeça a cada ano

    def test_banco_barra_numero_repetido(self):
        d, _ = self.emitir(self.completa())
        with self.assertRaises(IntegrityError), transaction.atomic():
            DocumentoEmitido.objects.create(registro=d.registro, tipo=d.tipo, ano=d.ano, sequencia=d.sequencia, pdf=b"x", hash_dados="x")

    def test_mesma_emissao_sem_mudanca_devolve_a_mesma_copia(self):
        r = self.completa()
        primeiro, novo1 = self.emitir(r)
        segundo, novo2 = self.emitir(r)
        self.assertEqual((novo1, novo2, primeiro.pk), (True, False, segundo.pk))
        self.assertEqual(DocumentoEmitido.objects.count(), 1)

    def test_mudou_o_dado_gera_nova_emissao_e_preserva_a_substituida(self):
        r = self.completa()
        antiga, _ = self.emitir(r)
        copia_original = bytes(antiga.pdf)
        r.cor = "preto"
        r.save()
        nova, novo = self.emitir(r)
        self.assertTrue(novo)
        self.assertNotEqual(nova.numero, antiga.numero)
        antiga.refresh_from_db()
        self.assertEqual(antiga.substituido_por.get(), nova)
        self.assertEqual(nova.substitui, antiga)
        self.assertEqual(bytes(antiga.pdf), copia_original)                # a cópia emitida nunca é recalculada
        self.assertTrue(antiga.substituido and not nova.substituido)
        self.assertIn(f"substitui o documento nº {antiga.numero}", texto_do_pdf(nova.pdf))
        self.assertEqual(DocumentoEmitido.objects.count(), 2)              # nada é apagado

    def test_mudar_a_empresa_tambem_gera_nova_versao(self):
        r = self.completa()
        antiga, _ = self.emitir(r)
        cfg = ConfiguracaoEmpresa.obter()
        cfg.endereco = "Outro endereço, 2"
        cfg.save()
        self.assertTrue(self.emitir(r)[1])
        self.assertTrue(antiga.__class__.objects.get(pk=antiga.pk).substituido)

    def test_tecnico_desativado_nao_quebra_documento_emitido(self):
        r = self.completa()
        documento, _ = self.emitir(r)
        self.tecnico.ativo = False
        self.tecnico.save()
        self.assertIn("Técnico de Teste", texto_do_pdf(DocumentoEmitido.objects.get(pk=documento.pk).pdf))
        self.assertEqual(self.emitir(r)[0].pk, documento.pk)               # a emissão continua válida


class RecibroTest(BaseRegravacaoTest):
    def test_bloqueado_sem_recebimento(self):
        r = self.registro()
        with self.assertRaises(ValidationError) as erro:
            emissao.emitir(r, Tipo.RECIBO, self.admin)
        self.assertIn("quando o recebimento estiver como Recebido", " ".join(erro.exception.messages))

    def test_bloqueado_sem_valor_ou_sem_responsavel(self):
        r = self.registro(recebimento_situacao="recebido", forma_pagamento="pix", data_recebimento=self.dias(0), valor=None)
        self.assertIn("Informe o valor", " ".join(emissao.exigencias(r, Tipo.RECIBO)))
        cfg = ConfiguracaoEmpresa.obter()
        cfg.responsavel_recibo_nome = ""
        cfg.save()
        self.assertIn("responsável que assina o recibo", " ".join(emissao.exigencias(r, Tipo.RECIBO, cfg)))

    def test_conteudo_com_valor_por_extenso(self):
        casos = {"1234.56": "mil, duzentos e trinta e quatro reais e cinquenta e seis centavos", "1.00": "um real",
                 "0.50": "cinquenta centavos", "2000000.00": "dois milhões de reais"}
        for i, (valor, extenso) in enumerate(casos.items()):
            r = self.registro(valor=Decimal(valor), recebimento_situacao="recebido", forma_pagamento="pix",
                              data_recebimento=self.dias(0), placa=f"EXT{i}A23")
            documento, _ = emissao.emitir(r, Tipo.RECIBO, self.admin)
            texto = texto_do_pdf(documento.pdf).replace("\n", " ")
            self.assertIn("RECIBO DE PAGAMENTO", texto)
            self.assertIn(extenso, texto)
            self.assertIn(self.cliente.nome, texto)
            self.assertIn("Pix", texto)
            self.assertIn("Responsável Teste", texto)
            self.assertIn(r.placa, texto)

    def test_so_emite_com_recebido_e_nao_depende_da_declaracao(self):
        r = self.registro(recebimento_situacao="recebido", forma_pagamento="dinheiro", data_recebimento=self.dias(-2))
        documento, novo = emissao.emitir(r, Tipo.RECIBO, self.admin)          # sem autorização nem conclusão: o recibo sai
        self.assertTrue(novo)
        self.assertEqual(documento.tipo, Tipo.RECIBO)


class TelasDeDocumentoTest(BaseRegravacaoTest):
    def test_emitir_e_baixar_pelo_site_registra_historico(self):
        r = self.completa()
        self.client.force_login(self.admin)
        resposta = self.client.post(reverse("documento_emitir", args=[r.pk, "declaracao"]))
        documento = DocumentoEmitido.objects.get()
        self.assertRedirects(resposta, reverse("documento_baixar", args=[documento.pk]), fetch_redirect_response=False)
        pdf = self.client.get(reverse("documento_baixar", args=[documento.pk]))
        self.assertEqual((pdf.status_code, pdf["Content-Type"]), (200, "application/pdf"))
        self.assertTrue(pdf.content.startswith(b"%PDF-"))
        self.assertIn("no-store", pdf["Cache-Control"])
        textos = " | ".join(h.valor_novo for h in r.historico.filter(tipo="documento"))
        self.assertIn("emitida", textos)
        self.assertIn("baixada", textos)                                       # emissões e downloads ficam registrados

    def test_emitir_sem_requisitos_mostra_o_que_falta(self):
        r = self.registro()
        self.client.force_login(self.admin)
        resposta = self.client.post(reverse("documento_emitir", args=[r.pk, "declaracao"]), follow=True)
        self.assertContains(resposta, "A regravação precisa estar concluída")
        self.assertEqual(DocumentoEmitido.objects.count(), 0)

    def test_emissao_so_por_post_e_tipo_valido(self):
        r = self.completa()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("documento_emitir", args=[r.pk, "declaracao"])).status_code, 405)
        self.assertEqual(self.client.post(reverse("documento_emitir", args=[r.pk, "contrato"])).status_code, 404)

    def test_detalhe_lista_versoes_e_marca_substituido(self):
        r = self.completa()
        emissao.emitir(r, Tipo.DECLARACAO, self.admin)
        r.cor = "preto"
        r.save()
        emissao.emitir(r, Tipo.DECLARACAO, self.admin)
        self.client.force_login(self.admin)
        html = self.client.get(r.get_absolute_url()).content.decode()
        self.assertIn("Substituído", html)
        self.assertIn("Vigente", html)
        self.assertIn("substitui", html)


class NumeracaoConcorrenteTest(TransactionTestCase):
    """Acessos simultâneos pedem número ao mesmo tempo: nenhum repete, e a sequência fecha sem buracos."""

    def test_threads_simultaneas_nao_repetem_numero(self):
        resultados, erros = [], []

        def pedir():
            for _ in range(6):
                for tentativa in range(60):
                    try:
                        resultados.append(emissao.proximo_numero(Tipo.DECLARACAO, 2099))
                        break
                    except OperationalError:           # SQLite serializa escritas: tenta de novo
                        time.sleep(0.02)
                else:
                    erros.append("sem sucesso")
            connection.close()

        threads = [threading.Thread(target=pedir) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(erros, [])
        self.assertEqual(len(resultados), 24)
        self.assertEqual(len(set(resultados)), 24)                           # nenhum repetido
        self.assertEqual(sorted(resultados), list(range(1, 25)))             # sem buracos
        self.assertEqual(SequenciaDocumento.objects.get(tipo=Tipo.DECLARACAO, ano=2099).ultimo, 24)
