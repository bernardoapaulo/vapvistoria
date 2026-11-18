"""
TEXTO DA DECLARAÇÃO DE SERVIÇO: é aqui que o texto fica. Para ajustar a redação, mude só este arquivo.

Os dados da empresa (razão social, CNPJ, endereço, telefones, cidade) NÃO ficam aqui: vêm da tela Empresa.
Marcações aceitas nos textos: <b>negrito</b>. Os valores variáveis já chegam protegidos (não use < ou > neles).
"""

TITULO = "DECLARAÇÃO"

# Nome do serviço conforme o que foi marcado (motor, chassi ou os dois)
NOME_SERVICO = {
    (True, False): "Regravação de Motor",
    (False, True): "Regravação de Chassi",
    (True, True): "Regravação de Motor e Chassi",
}

PARAGRAFO = (
    "A empresa {razao_social}, inscrita no CNPJ {cnpj}, estabelecida {endereco}, tel {telefones}, "
    "devidamente autorizada pelo Detran, declara para os devidos fins que o veículo abaixo informado "
    "<b>PASSOU</b> pelo processo de <b>{servico}</b> de acordo com autorização do Detran em anexo."
)

# Rótulos do quadro de dados (a ordem das linhas está em documentos/pdf.py -> linhas_declaracao)
ROTULOS = {
    "proprietario": "Proprietário:",
    "veiculo": "Marca / Modelo:",
    "ano": "Ano / Modelo:",
    "cor": "Cor:",
    "placa": "Placa:",
    "chassi": "Regravação Chassi:",
    "motor": "Regravação Motor:",
    "data": "Data do serviço:",
    "solicitante": "Solicitante:",
}

SOLICITANTE_IGUAL_AO_PROPRIETARIO = "O MESMO"
LEGENDA_SOLICITANTE = "(Solicitante)"
