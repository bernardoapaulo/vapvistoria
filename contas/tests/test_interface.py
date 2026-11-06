"""Etapa 6 (interface): o novo layout responde, os arquivos locais existem e as páginas de erro funcionam."""
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from contas.permissoes import ADMINISTRADOR, FUNCIONARIO

ARQUIVOS_ESTATICOS = [
    "css/tokens.css", "css/base.css", "css/modulos.css", "css/impressao.css",
    "img/logo-vap.png", "img/logo-vap-clara.png", "img/favicon.ico", "img/favicon.png", "img/apple-touch-icon.png",
    "icons/sprite.svg", "icons/LICENSE-lucide.txt",
    "vendor/chartjs/chart.umd.min.js", "vendor/fullcalendar/index.global.min.js", "vendor/fullcalendar/pt-br.global.min.js",
    "vendor/fonts/inter-latin-wght-normal.woff2", "vendor/fonts/inter-latin-ext-wght-normal.woff2",
    "vendor/fonts/barlow-condensed-latin-600-normal.woff2", "vendor/fonts/barlow-condensed-latin-700-normal.woff2",
    "vendor/fonts/LICENSE-inter.txt", "vendor/fonts/LICENSE-barlow-condensed.txt",
]


class InterfaceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        Usuario = get_user_model()
        cls.admin = Usuario.objects.create_user("admin", password="x")
        cls.admin.groups.add(Group.objects.get(name=ADMINISTRADOR))
        cls.func = Usuario.objects.create_user("func", password="x")
        cls.func.groups.add(Group.objects.get(name=FUNCIONARIO))

    # --- login ---
    def test_login_usa_a_identidade_visual_e_nada_externo(self):
        resp = self.client.get(reverse("login"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("<title>Entrar · VAP Vistoria</title>", html)
        self.assertIn('alt="VAP Vistoria"', html)
        self.assertIn('name="theme-color"', html)
        self.assertIn("css/tokens.css", html)
        self.assertNotIn("https://", html)   # nenhuma fonte, script ou imagem de terceiros

    def test_login_com_senha_errada_mostra_erro_claro(self):
        resp = self.client.post(reverse("login"), {"username": "func", "password": "errada"})
        self.assertContains(resp, "Usuário ou senha incorretos")
        self.assertContains(resp, 'role="alert"')

    # --- páginas principais com o novo layout ---
    def _paginas(self, nomes):
        for nome in nomes:
            resp = self.client.get(reverse(nome))
            self.assertEqual(resp.status_code, 200, nome)
            html = resp.content.decode()
            self.assertIn("Pular para o conteúdo", html, nome)
            self.assertIn('aria-label="Menu lateral"', html, nome)
            self.assertRegex(html, r"<title>[^<]+ · VAP Vistoria</title>", nome)
            self.assertNotIn('style="', html, nome)       # sem estilos soltos nos templates
            self.assertNotIn("https://", html, nome)      # tudo local (LGPD e funciona sem internet)

    def test_administrador_ve_as_telas_principais(self):
        self.client.force_login(self.admin)
        self._paginas(["inicio", "dashboard", "atendimento_lista", "agenda_calendario", "financeiro",
                       "cliente_lista", "aluno_lista", "veiculo_lista", "servico_lista"])

    def test_funcionario_ve_menu_sem_financeiro(self):
        self.client.force_login(self.func)
        self._paginas(["inicio", "atendimento_lista", "agenda_calendario", "cliente_lista"])
        html = self.client.get(reverse("inicio")).content.decode()
        self.assertNotIn(reverse("financeiro"), html)
        self.assertIn("Funcionário", html)
        self.assertIn('aria-current="page"', html)

    def test_icones_decorativos_ficam_escondidos_de_leitores_de_tela(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("inicio")).content.decode()
        self.assertGreater(html.count('class="icone" aria-hidden="true"'), 5)
        self.assertNotIn('class="icone">', html)

    # --- páginas de erro ---
    def test_403_com_identidade_e_caminho_de_volta(self):
        self.client.force_login(self.func)
        resp = self.client.get(reverse("financeiro"))
        self.assertContains(resp, "Acesso negado", status_code=403)
        self.assertContains(resp, "Voltar ao início", status_code=403)

    def test_404_e_pagina_propria(self):
        resp = self.client.get("/isto-nao-existe/")
        self.assertContains(resp, "Página não encontrada", status_code=404)
        self.assertContains(resp, "Voltar ao início", status_code=404)
        self.assertContains(resp, 'alt="VAP Vistoria"', status_code=404)

    def test_500_nao_depende_de_menu_nem_de_usuario(self):
        html = render_to_string("500.html")
        self.assertIn("Algo deu errado", html)
        self.assertIn("Voltar ao início", html)
        self.assertNotIn("menu__nav", html)

    # --- arquivos locais ---
    def test_arquivos_estaticos_existem(self):
        for caminho in ARQUIVOS_ESTATICOS:
            self.assertIsNotNone(finders.find(caminho), caminho)

    def test_todo_icone_usado_nos_templates_existe_no_sprite(self):
        sprite = (settings.BASE_DIR / "static" / "icons" / "sprite.svg").read_text(encoding="utf-8")
        usados = set()
        for arquivo in (settings.BASE_DIR / "templates").rglob("*.html"):
            usados |= set(re.findall(r'partials/icone\.html" with nome="([\w-]+)"', arquivo.read_text(encoding="utf-8")))
        self.assertGreater(len(usados), 10)
        for nome in usados:
            self.assertIn(f'id="{nome}"', sprite, nome)

    def test_css_organizado_e_sem_excessos(self):
        css = settings.BASE_DIR / "static" / "css"
        tokens = (css / "tokens.css").read_text(encoding="utf-8")
        for arquivo in ("base.css", "modulos.css", "impressao.css"):
            texto = (css / arquivo).read_text(encoding="utf-8")
            # cores fixas ficam só no arquivo de tokens (exceto branco/transparências pontuais)
            self.assertNotRegex(re.sub(r"#fff\b|#FFF\b|#F2F2F2", "", texto), r"#[0-9A-Fa-f]{6}\b", arquivo)
        todo = "".join((css / a).read_text(encoding="utf-8") for a in ("base.css", "modulos.css", "impressao.css"))
        self.assertEqual(todo.count("!important"), 1)   # só o [hidden]
        self.assertIn("prefers-reduced-motion", todo)
        self.assertIn("@media print", tokens)           # a impressão troca os tokens para fundo branco
        self.assertIn("font-display: swap", tokens)
