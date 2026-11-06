import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from cadastros.models import Aluno
from cadastros.validators import validar_cep, validar_cpf
from contas.permissoes import ADMINISTRADOR

MEDIA_TESTE = tempfile.mkdtemp()
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


def dados_aluno(**extra):
    dados = {
        "nome": "Aluna Teste", "cpf": "529.982.247-25", "email": "", "data_nascimento": "2000-05-10",
        "sexo": "F", "celular": "(11) 98888-0000", "endereco": "Rua A, 1", "cep": "01001000",
        "observacoes": "", "data_cadastro": "2026-01-01",
    }
    dados.update(extra)
    return dados


class ValidadoresAlunoTest(TestCase):
    def test_cpf(self):
        validar_cpf("529.982.247-25")
        with self.assertRaises(ValidationError):
            validar_cpf("111.111.111-11")
        with self.assertRaises(ValidationError):
            validar_cpf("11.222.333/0001-81")  # CNPJ não vale como CPF

    def test_cep(self):
        validar_cep("01001-000")
        with self.assertRaises(ValidationError):
            validar_cep("123")


@override_settings(MEDIA_ROOT=MEDIA_TESTE)
class AlunoTelasTest(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_TESTE, ignore_errors=True)

    def setUp(self):
        user = get_user_model().objects.create_user("adm", password="x")
        user.groups.add(Group.objects.get(name=ADMINISTRADOR))
        self.client.force_login(user)

    def test_cadastro_completo_formata_cpf_e_cep(self):
        resp = self.client.post(reverse("aluno_novo"), dados_aluno(cpf="52998224725"))
        self.assertEqual(resp.status_code, 302)
        aluno = Aluno.objects.get()
        self.assertEqual(aluno.cpf, "529.982.247-25")
        self.assertEqual(aluno.cep, "01001-000")
        self.assertEqual(aluno.get_sexo_display(), "Feminino")

    def test_cpf_duplicado_e_invalido(self):
        self.client.post(reverse("aluno_novo"), dados_aluno())
        resp = self.client.post(reverse("aluno_novo"), dados_aluno(cpf="529.982.24725", nome="Outra"))
        self.assertContains(resp, "Já existe um aluno cadastrado com este CPF")
        resp = self.client.post(reverse("aluno_novo"), dados_aluno(cpf="123"))
        self.assertContains(resp, "CPF inválido")

    def test_campos_obrigatorios(self):
        resp = self.client.post(reverse("aluno_novo"), {})
        for msg in ["Informe o nome do aluno", "Informe o CPF", "Informe a data de nascimento",
                    "Selecione feminino ou masculino", "Informe o celular", "Informe o endereço", "Informe o CEP"]:
            self.assertContains(resp, msg)

    def test_upload_de_documento_e_acesso_protegido(self):
        foto = SimpleUploadedFile("minha foto.png", PNG, content_type="image/png")
        pdf = SimpleUploadedFile("antecedentes.pdf", b"%PDF-1.4 teste", content_type="application/pdf")
        self.client.post(reverse("aluno_novo"), dados_aluno(foto=foto, antecedentes_criminais=pdf))
        aluno = Aluno.objects.get()
        self.assertTrue(aluno.foto and aluno.antecedentes_criminais)
        self.assertNotIn("minha", aluno.foto.name)  # nome original não é mantido

        url = reverse("aluno_documento", args=[aluno.pk, "foto"])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(b"".join(resp.streaming_content), PNG)

        self.client.logout()
        self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}")

    def test_documento_inexistente_ou_campo_invalido_da_404(self):
        self.client.post(reverse("aluno_novo"), dados_aluno())
        aluno = Aluno.objects.get()
        self.assertEqual(self.client.get(reverse("aluno_documento", args=[aluno.pk, "foto"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("aluno_documento", args=[aluno.pk, "cpf"])).status_code, 404)

    def test_rejeita_extensao_e_tamanho_invalidos(self):
        exe = SimpleUploadedFile("virus.exe", b"x")
        resp = self.client.post(reverse("aluno_novo"), dados_aluno(certidao_negativa=exe))
        self.assertContains(resp, "Formato não permitido")
        grande = SimpleUploadedFile("grande.pdf", b"0" * (5 * 1024 * 1024 + 1))
        resp = self.client.post(reverse("aluno_novo"), dados_aluno(certidao_negativa=grande))
        self.assertContains(resp, "Arquivo muito grande")
        self.assertEqual(Aluno.objects.count(), 0)

    def test_remover_e_excluir_apagam_arquivos(self):
        self.client.post(reverse("aluno_novo"), dados_aluno(
            foto=SimpleUploadedFile("f.png", PNG), certidao_negativa=SimpleUploadedFile("c.pdf", b"%PDF")))
        aluno = Aluno.objects.get()
        caminho_foto = aluno.foto.path
        # remover só a certidão
        self.client.post(reverse("aluno_editar", args=[aluno.pk]),
                         dados_aluno(remover_certidao_negativa="on"))
        aluno.refresh_from_db()
        self.assertFalse(aluno.certidao_negativa)
        self.assertTrue(aluno.foto)  # foto continua
        # excluir o aluno apaga os arquivos do disco
        self.client.post(reverse("aluno_excluir", args=[aluno.pk]))
        import os
        self.assertFalse(os.path.exists(caminho_foto))

    def test_detalhe_mostra_cpf_mascarado_e_pendencias(self):
        self.client.post(reverse("aluno_novo"), dados_aluno())
        aluno = Aluno.objects.get()
        resp = self.client.get(reverse("aluno_detalhe", args=[aluno.pk]))
        self.assertContains(resp, "***.982.247-**")
        self.assertNotContains(resp, "529.982.247-25")
        self.assertContains(resp, "Pendente")
