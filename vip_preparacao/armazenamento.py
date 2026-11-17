"""
Armazenamento das fotos, escolhido por variável de ambiente (nada de código muda ao trocar).

- FOTOS_STORAGE=local (padrão): pasta privada `arquivos_privados/vip/` (ARQUIVOS_PRIVADOS_ROOT), fora de static/media.
- FOTOS_STORAGE=s3: bucket compatível com S3 (Cloudflare R2, AWS S3...). Variáveis:
    FOTOS_S3_BUCKET, FOTOS_S3_ENDPOINT (vazio na AWS), FOTOS_S3_ACCESS_KEY, FOTOS_S3_SECRET_KEY, FOTOS_S3_REGION
  Requer `pip install django-storages[s3]`. O bucket deve ser PRIVADO: as fotos só saem pela view com login.

Em hospedagem com disco temporário (Vercel, Render sem disco persistente), use s3: arquivos locais se perdem.
"""
import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage


def armazenamento_fotos():
    if os.environ.get("FOTOS_STORAGE", "local").lower() == "s3":
        from storages.backends.s3 import S3Storage  # import tardio: só é preciso em produção

        return S3Storage(
            bucket_name=os.environ["FOTOS_S3_BUCKET"],
            endpoint_url=os.environ.get("FOTOS_S3_ENDPOINT") or None,
            access_key=os.environ["FOTOS_S3_ACCESS_KEY"],
            secret_key=os.environ["FOTOS_S3_SECRET_KEY"],
            region_name=os.environ.get("FOTOS_S3_REGION") or None,
            default_acl=None,
            querystring_auth=True,
            file_overwrite=False,
        )
    return FileSystemStorage(location=settings.ARQUIVOS_PRIVADOS_ROOT)
