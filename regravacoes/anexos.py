"""
Validação e preparo dos anexos (PDF, JPEG, PNG, WebP). O conteúdo é conferido DE VERDADE (não só a extensão):
- PDF: abre com o pypdf, tem páginas, não é criptografado e não carrega JavaScript/ação automática.
- Imagem: Pillow abre, corrige a orientação, reduz e regrava em JPEG sem EXIF/GPS (vip_preparacao.fotos).
O limite de tamanho é configurável (REGRAVACAO_ANEXO_MAX_MB, padrão 10 MB).
"""
import os
from io import BytesIO

from django.core.exceptions import ValidationError
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from vip_preparacao import fotos

MENSAGEM_INVALIDO = "O arquivo enviado não é um PDF nem uma imagem válida. Envie PDF, JPEG, PNG ou WebP."
PERIGOSOS = (b"/JavaScript", b"/JS", b"/Launch", b"/OpenAction", b"/AA", b"/EmbeddedFile")


def limite_bytes():
    return int(float(os.environ.get("REGRAVACAO_ANEXO_MAX_MB", "10")) * 1024 * 1024)


def _validar_pdf(dados):
    if b"%%EOF" not in dados[-1024:]:
        raise ValidationError("O PDF parece estar incompleto ou corrompido.")
    if any(marca in dados for marca in PERIGOSOS):
        raise ValidationError("Este PDF contém scripts ou arquivos embutidos e não é aceito. Envie um PDF comum.")
    try:
        leitor = PdfReader(BytesIO(dados), strict=False)
        if leitor.is_encrypted:
            raise ValidationError("O PDF é protegido por senha. Envie uma versão sem senha.")
        if len(leitor.pages) < 1:
            raise ValidationError(MENSAGEM_INVALIDO)
    except ValidationError:
        raise
    except (PyPdfError, ValueError, KeyError, OSError, RecursionError):
        raise ValidationError(MENSAGEM_INVALIDO)


def processar(arquivo):
    """
    Devolve {conteudo, miniatura, content_type, nome_original} ou levanta ValidationError (mensagem em português).
    `miniatura` só existe para imagem.
    """
    limite = limite_bytes()
    if arquivo.size > limite:
        raise ValidationError(f"Arquivo muito grande. O tamanho máximo é {limite / 1024 / 1024:g} MB.")
    arquivo.seek(0)
    dados = arquivo.read()
    nome = os.path.basename(getattr(arquivo, "name", "") or "")[:150]
    if dados[:5] == b"%PDF-":
        _validar_pdf(dados)
        return {"conteudo": dados, "miniatura": None, "content_type": "application/pdf", "nome_original": nome}
    arquivo.seek(0)
    try:
        grande, mini, _ = fotos.processar(arquivo)
    except ValidationError:
        raise ValidationError(MENSAGEM_INVALIDO)
    return {"conteudo": grande, "miniatura": mini, "content_type": "image/jpeg", "nome_original": nome}
