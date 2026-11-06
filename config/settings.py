"""
Configurações do projeto VAP Vistoria.

Valores sensíveis (SECRET_KEY, banco de dados, DEBUG) vêm de variáveis de
ambiente, lidas do arquivo .env (que NÃO vai para o git).
"""
import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

# A Vercel define VERCEL=1 no build e na execução. Lá o disco é somente leitura e não guarda nada
# entre execuções, então o banco precisa ser externo (Postgres) e os envios de arquivo são temporários.
NA_VERCEL = bool(os.environ.get("VERCEL"))

SECRET_KEY = os.environ.get("SECRET_KEY", "")
DEBUG = os.environ.get("DEBUG", "False").lower() in ("1", "true", "sim")
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
# Domínio próprio na Vercel: acrescente-o em ALLOWED_HOSTS e em CSRF_TRUSTED_ORIGINS (https://seudominio.com.br).
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]
if NA_VERCEL:
    ALLOWED_HOSTS.append(".vercel.app")
    CSRF_TRUSTED_ORIGINS.append("https://*.vercel.app")

if not SECRET_KEY:
    if DEBUG:
        # Apenas para desenvolvimento local; em produção a variável é obrigatória.
        SECRET_KEY = "chave-insegura-somente-desenvolvimento"
    else:
        # Diagnóstico: só os NOMES das variáveis (nunca os valores), para ver se a SECRET_KEY chegou ao build.
        parecidas = sorted(k for k in os.environ if any(t in k.upper() for t in ("SECRET", "DATABASE", "POSTGRES", "DEBUG")))
        raise RuntimeError(
            "Defina SECRET_KEY: no arquivo .env (veja .env.example) ou, na Vercel, em Settings > Environment Variables "
            f"(marque Production e Preview e faça Redeploy). Variáveis parecidas vistas agora: {parecidas or 'nenhuma'}."
        )

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Apps do projeto
    "contas",
    "cadastros",
    "servicos",
    "atendimentos",
    "agenda",
    "dashboard",
    "financeiro",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Banco: SQLite por padrão; defina DATABASE_URL (ex.: postgres://...) para trocar.
if NA_VERCEL and not os.environ.get("DATABASE_URL"):
    raise RuntimeError("Na Vercel o SQLite não funciona (disco somente leitura). Crie um banco Postgres e defina DATABASE_URL.")
DATABASES = {
    "default": dj_database_url.parse(
        os.environ.get("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=0 if NA_VERCEL else 600,   # função sem servidor: não deixar conexões abertas
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Documentos enviados (fotos, certidões...). NÃO são servidos publicamente:
# o acesso é feito pela view protegida "aluno_documento".
MEDIA_ROOT = BASE_DIR / "media"

# Comprovantes de despesas: fora de static/media, só servidos pela view protegida.
ARQUIVOS_PRIVADOS_ROOT = BASE_DIR / "arquivos_privados"
if NA_VERCEL:
    # Único lugar gravável na Vercel; os arquivos somem quando a função é reciclada (use um armazenamento
    # externo, como S3 ou Vercel Blob, se isto virar um sistema de produção).
    MEDIA_ROOT = Path("/tmp/vap/media")
    ARQUIVOS_PRIVADOS_ROOT = Path("/tmp/vap/arquivos_privados")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Autenticação
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "inicio"
LOGOUT_REDIRECT_URL = "login"

# Itens por página nas listagens
ITENS_POR_PAGINA = 15

# Segurança em produção (só na Vercel, que sempre serve por HTTPS)
if NA_VERCEL and not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
