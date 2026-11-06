"""Validadores reutilizáveis: CPF/CNPJ e placa de veículo."""
import re
import uuid

from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible

PLACA_ANTIGA = re.compile(r"^[A-Z]{3}[0-9]{4}$")          # ABC1234
PLACA_MERCOSUL = re.compile(r"^[A-Z]{3}[0-9][A-Z][0-9]{2}$")  # ABC1D23


def somente_digitos(valor):
    return re.sub(r"\D", "", valor or "")


def _cpf_valido(cpf):
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for tamanho in (9, 10):
        soma = sum(int(cpf[i]) * (tamanho + 1 - i) for i in range(tamanho))
        digito = (soma * 10 % 11) % 10
        if digito != int(cpf[tamanho]):
            return False
    return True


def _cnpj_valido(cnpj):
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False
    for tamanho in (12, 13):
        pesos = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        if tamanho == 13:
            pesos = [6] + pesos
        soma = sum(int(cnpj[i]) * pesos[i] for i in range(tamanho))
        digito = 0 if soma % 11 < 2 else 11 - soma % 11
        if digito != int(cnpj[tamanho]):
            return False
    return True


def validar_cpf_cnpj(valor):
    """Aceita CPF (11 dígitos) ou CNPJ (14 dígitos), com ou sem máscara."""
    digitos = somente_digitos(valor)
    if len(digitos) == 11 and _cpf_valido(digitos):
        return
    if len(digitos) == 14 and _cnpj_valido(digitos):
        return
    raise ValidationError("CPF ou CNPJ inválido. Confira os números digitados.")


def validar_cpf(valor):
    """Aceita somente CPF (11 dígitos), com ou sem máscara."""
    digitos = somente_digitos(valor)
    if not _cpf_valido(digitos):
        raise ValidationError("CPF inválido. Confira os números digitados.")


def formatar_cpf(valor):
    d = somente_digitos(valor)
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if len(d) == 11 else valor


def validar_cep(valor):
    if len(somente_digitos(valor)) != 8:
        raise ValidationError("CEP inválido. Informe 8 números, por exemplo 01001-000.")


def formatar_cep(valor):
    d = somente_digitos(valor)
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else valor


TAMANHO_MAXIMO_ARQUIVO = 5 * 1024 * 1024  # 5 MB


@deconstructible
class ValidadorArquivo:
    """Confere extensão e tamanho de um arquivo enviado."""

    def __init__(self, extensoes):
        self.extensoes = tuple(extensoes)

    def __call__(self, arquivo):
        ext = arquivo.name.rsplit(".", 1)[-1].lower() if "." in arquivo.name else ""
        if ext not in self.extensoes:
            nomes = ", ".join(e.upper() for e in self.extensoes)
            raise ValidationError(f"Formato não permitido. Envie um arquivo {nomes}.")
        if arquivo.size > TAMANHO_MAXIMO_ARQUIVO:
            raise ValidationError("Arquivo muito grande. O tamanho máximo é 5 MB.")

    def __eq__(self, outro):
        return isinstance(outro, ValidadorArquivo) and self.extensoes == outro.extensoes


validar_documento = ValidadorArquivo(("pdf", "jpg", "jpeg", "png"))
validar_foto = ValidadorArquivo(("jpg", "jpeg", "png"))


@deconstructible
class CaminhoUpload:
    """Gera nome aleatório para o arquivo (não expõe nome original nem dados do aluno)."""

    def __init__(self, pasta):
        self.pasta = pasta

    def __call__(self, instancia, nome_arquivo):
        ext = nome_arquivo.rsplit(".", 1)[-1].lower() if "." in nome_arquivo else "bin"
        return f"alunos/{self.pasta}/{uuid.uuid4().hex}.{ext}"

    def __eq__(self, outro):
        return isinstance(outro, CaminhoUpload) and self.pasta == outro.pasta


def normalizar_placa(valor):
    return re.sub(r"[^A-Za-z0-9]", "", valor or "").upper()


def validar_placa(valor):
    placa = normalizar_placa(valor)
    if not (PLACA_ANTIGA.match(placa) or PLACA_MERCOSUL.match(placa)):
        raise ValidationError(
            "Placa inválida. Use o formato antigo (ABC1234) ou Mercosul (ABC1D23)."
        )


def mascarar_cpf_cnpj(valor):
    """Oculta parte do documento (LGPD): ***.456.789-** ou **.***.678/0001-**."""
    d = somente_digitos(valor)
    if len(d) == 11:
        return f"***.{d[3:6]}.{d[6:9]}-**"
    if len(d) == 14:
        return f"**.***.{d[5:8]}/{d[8:12]}-**"
    return ""
