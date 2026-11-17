"""
Processamento das fotos: valida de verdade (abre a imagem com Pillow), corrige a orientação, reduz, recomprime
e remove os metadados (EXIF, inclusive GPS). Aceita JPEG, PNG, WebP e HEIC/HEIF (fotos do iPhone).

Sempre devolve JPEG: ao regravar a imagem sem passar o EXIF, nenhum metadado de localização sobrevive.
"""
import os
from io import BytesIO

from django.core.exceptions import ValidationError
from PIL import Image, ImageOps, UnidentifiedImageError

try:  # HEIC/HEIF (iPhone). Se o pacote faltar, os outros formatos continuam funcionando.
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover
    pass

LADO_MAXIMO = 1920
LADO_MINIATURA = 320
QUALIDADE = 82
MAX_PIXELS = 80_000_000   # barra "bombas" de descompressão (arquivo pequeno que vira imagem gigante)
FORMATOS = {"JPEG", "MPO", "PNG", "WEBP", "HEIF", "HEIC", "AVIF"}   # MPO é o JPEG de várias imagens de alguns celulares

MENSAGEM_INVALIDA = "O arquivo enviado não é uma imagem válida. Envie uma foto JPEG, PNG, WebP ou HEIC."


def limite_bytes():
    return int(float(os.environ.get("VIP_FOTO_MAX_MB", "10")) * 1024 * 1024)


def _jpeg(imagem, lado, qualidade):
    copia = imagem.copy()
    copia.thumbnail((lado, lado), Image.Resampling.LANCZOS)
    saida = BytesIO()
    copia.save(saida, "JPEG", quality=qualidade, optimize=True)   # sem exif=: metadados descartados
    return saida.getvalue(), copia.size


def processar(arquivo):
    """Valida e converte. Devolve (jpeg_grande, jpeg_miniatura, (largura, altura)) ou levanta ValidationError."""
    limite = limite_bytes()
    if arquivo.size > limite:
        raise ValidationError(f"Foto muito grande. O tamanho máximo é {limite / 1024 / 1024:g} MB.")
    try:
        arquivo.seek(0)
        imagem = Image.open(arquivo)
        if imagem.format not in FORMATOS:
            raise ValidationError(MENSAGEM_INVALIDA)
        if imagem.width * imagem.height > MAX_PIXELS:
            raise ValidationError("Imagem com dimensões grandes demais.")
        imagem.load()
    except ValidationError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        raise ValidationError(MENSAGEM_INVALIDA)

    imagem = ImageOps.exif_transpose(imagem)   # corrige a orientação ANTES de descartar o EXIF
    if imagem.mode in ("RGBA", "LA", "P"):
        imagem = imagem.convert("RGBA")
        fundo = Image.new("RGB", imagem.size, (255, 255, 255))
        fundo.paste(imagem, mask=imagem.getchannel("A"))
        imagem = fundo
    else:
        imagem = imagem.convert("RGB")

    grande, tamanho = _jpeg(imagem, LADO_MAXIMO, QUALIDADE)
    mini, _ = _jpeg(imagem, LADO_MINIATURA, 75)
    return grande, mini, tamanho
