"""
Emissão da Declaração e do Recibo: confere as exigências (mensagens claras do que falta), numera sem repetir
(sequência por tipo e ano, com trava de linha e restrição única no banco) e guarda o PDF emitido como cópia fiel.

Se os dados mudarem depois, uma nova emissão gera um documento NOVO (número novo) que "substitui" o anterior; o anterior
fica marcado como substituído e nunca é apagado. Se nada mudou, o botão apenas baixa a cópia já emitida.
"""
import hashlib
import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from financeiro.dinheiro import reais
from vip_preparacao.models import Cor

from .. import regras
from ..extenso import valor_por_extenso
from ..models import ConfiguracaoEmpresa, DocumentoEmitido, RegistroRegravacao, SequenciaDocumento
from . import pdf
from . import texto_declaracao as decl

Tipo = DocumentoEmitido.Tipo


# ---------- Exigências ----------
def exigencias(r, tipo, cfg=None):
    """Lista (em português) do que falta para emitir; vazia = pode emitir."""
    cfg = cfg or ConfiguracaoEmpresa.obter()
    faltam = []
    empresa = cfg.faltando_para_documentos()
    if empresa:
        faltam.append(f"Preencha na aba Empresa: {', '.join(empresa)}.")
    if tipo == Tipo.DECLARACAO:
        if r.status != RegistroRegravacao.Status.CONCLUIDA:
            faltam.append("A regravação precisa estar concluída (data do serviço concluído e técnico responsável).")
        for anexo in r.anexos_pendentes:
            faltam.append(f"Anexe a {dict(r.anexos.model.Tipo.choices)[anexo]}: a declaração afirma que o serviço foi "
                          "feito conforme a autorização do Detran em anexo.")
        for rotulo, valor in (("o proprietário do veículo", r.nome_proprietario), ("a marca", r.marca),
                              ("o modelo", r.modelo), ("o ano/modelo", r.ano_modelo), ("a cor", r.cor_texto),
                              ("a placa", r.placa)):
            if not valor:
                faltam.append(f"Preencha {rotulo}.")
        if r.servico_chassi and len(r.chassi) != 17:
            faltam.append("Informe o número do chassi (17 caracteres), necessário para a regravação de chassi.")
        if r.servico_motor and not r.numero_motor:
            faltam.append("Informe o número do motor, necessário para a regravação de motor.")
    else:
        if r.recebimento_situacao != RegistroRegravacao.Situacao.RECEBIDO:
            faltam.append("O recibo só pode ser emitido quando o recebimento estiver como Recebido.")
        if not r.valor or r.valor <= 0:
            faltam.append("Informe o valor (maior que zero).")
        if not cfg.responsavel_recibo_nome:
            faltam.append("Informe, na aba Empresa, o responsável que assina o recibo.")
    return faltam


# ---------- Dados dos documentos ----------
def _empresa(cfg):
    return {"razao_social": cfg.razao_social, "cnpj": cfg.cnpj, "endereco": cfg.endereco, "telefones": cfg.telefones,
            "cidade": cfg.cidade, "rodape": cfg.rodape}


def dados_declaracao(r, cfg):
    servico = decl.NOME_SERVICO[(r.servico_motor, r.servico_chassi)]
    return {
        "empresa": _empresa(cfg), "servico": servico, "proprietario": r.nome_proprietario.upper(),
        "veiculo": r.veiculo_texto.upper(), "ano": r.ano_modelo, "cor": r.cor_texto.upper(), "placa": r.placa,
        "chassi": r.chassi if r.servico_chassi else "", "motor": r.numero_motor if r.servico_motor else "",
        "data_servico": f"{r.data_concluida:%d/%m/%Y}",
        "solicitante": (decl.SOLICITANTE_IGUAL_AO_PROPRIETARIO if r.proprietario_e_cliente else r.cliente.nome.upper()),
        "tecnico": {"nome": r.tecnico.nome, "funcao": r.tecnico.funcao, "credencial": r.tecnico.credencial},
    }


def dados_recibo(r, cfg):
    servico = decl.NOME_SERVICO[(r.servico_motor, r.servico_chassi)]
    return {
        "empresa": _empresa(cfg), "cliente": r.cliente.nome, "valor": reais(r.valor), "extenso": valor_por_extenso(r.valor),
        "servico": servico, "veiculo": r.veiculo_texto or "—", "placa": r.placa, "forma": r.get_forma_pagamento_display(),
        "data": f"{r.data_recebimento:%d/%m/%Y}",
        "responsavel": {"nome": cfg.responsavel_recibo_nome, "funcao": cfg.responsavel_recibo_funcao},
    }


def _hash(dados, cfg):
    bruto = dict(dados, logo_sha=hashlib.sha256(bytes(cfg.logo or b"")).hexdigest())
    return hashlib.sha256(json.dumps(bruto, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


# ---------- Numeração ----------
def proximo_numero(tipo, ano):
    """Próximo número do tipo/ano. A trava de linha serializa quem pede ao mesmo tempo; a restrição única do banco
    (tipo, ano, sequência) é a segunda barreira."""
    for tentativa in range(3):
        try:
            with transaction.atomic():
                sequencia, _ = SequenciaDocumento.objects.select_for_update().get_or_create(tipo=tipo, ano=ano)
                sequencia.ultimo += 1
                sequencia.save(update_fields=["ultimo"])
                return sequencia.ultimo
        except IntegrityError:           # duas primeiras requisições do ano criando a linha ao mesmo tempo
            if tentativa == 2:
                raise
    raise RuntimeError("inalcançável")


# ---------- Emissão ----------
@transaction.atomic
def emitir(registro, tipo, usuario):
    """Devolve (documento, emitido_agora). Se nada mudou desde a última emissão, devolve a mesma cópia (False)."""
    r = (RegistroRegravacao.objects.select_for_update().select_related("cliente", "tecnico", "parceiro")
         .get(pk=registro.pk))
    cfg = ConfiguracaoEmpresa.obter()
    faltam = exigencias(r, tipo, cfg)
    if faltam:
        raise ValidationError(faltam)
    dados = dados_declaracao(r, cfg) if tipo == Tipo.DECLARACAO else dados_recibo(r, cfg)
    h = _hash(dados, cfg)
    ativo = r.documentos.filter(tipo=tipo, substituido_por__isnull=True).order_by("-emitido_em", "-id").first()
    if ativo and ativo.hash_dados == h:
        return ativo, False

    agora = timezone.now()
    ano = timezone.localdate().year
    sequencia = proximo_numero(tipo, ano)
    numero = f"{ano}/{sequencia:04d}"
    dados["logo"] = bytes(cfg.logo) if cfg.logo else None
    gerar = pdf.gerar_declaracao if tipo == Tipo.DECLARACAO else pdf.gerar_recibo
    conteudo = gerar(dados, numero, timezone.localtime(agora), substitui=ativo.numero if ativo else None)
    documento = DocumentoEmitido.objects.create(
        registro=r, tipo=tipo, ano=ano, sequencia=sequencia, pdf=conteudo, hash_dados=h, emitido_por=usuario,
        emitido_em=agora, substitui=ativo)
    regras.registrar_documento(
        r, f"{documento.get_tipo_display()} nº {documento.numero} emitida"
           + (f" (substitui nº {ativo.numero})" if ativo else ""), usuario)
    return documento, True


def registrar_download(documento, usuario):
    regras.registrar_documento(
        documento.registro, f"{documento.get_tipo_display()} nº {documento.numero} baixada"
        + (" (versão substituída)" if documento.substituido else ""), usuario)
