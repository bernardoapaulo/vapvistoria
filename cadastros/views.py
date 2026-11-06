from django.contrib.auth.mixins import PermissionRequiredMixin
from django.db.models import Count
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.views import View

from agenda.models import Agendamento

from .crud import CriarCrud, DetalheCrud, EditarCrud, ExcluirCrud, ListaCrud
from .forms import AlunoForm, ClienteForm, VeiculoForm
from .models import Aluno, Cliente, Veiculo


class HistoricoServicosMixin:
    """Acrescenta ao detalhe o histórico de atendimentos (related_name="atendimentos") e os totais."""
    limite_historico = 50

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        atendimentos = self.object.atendimentos
        ctx["totais"] = atendimentos.totais()
        ctx["atendimentos"] = atendimentos.select_related(
            "tipo_servico", "veiculo", "aluno")[:self.limite_historico]
        return ctx


# ---------- Clientes ----------
class ClienteLista(ListaCrud):
    model = Cliente
    template_name = "cadastros/cliente_lista.html"
    campos_busca = ["nome", "telefone", "whatsapp", "cpf_cnpj", "email"]

    def get_queryset(self):
        return super().get_queryset().annotate(qtd_veiculos=Count("veiculos")).order_by("nome")


class ClienteDetalhe(HistoricoServicosMixin, DetalheCrud):
    model = Cliente
    template_name = "cadastros/cliente_detalhe.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["veiculos"] = self.object.veiculos.all()
        if self.request.user.has_perm("agenda.view_agendamento"):
            ctx["proximo_agendamento"] = (
                Agendamento.objects.com_detalhes().futuros()
                .filter(atendimento__cliente=self.object).order_by("inicio").first()
            )
        return ctx


class ClienteCriar(CriarCrud):
    model = Cliente
    form_class = ClienteForm
    extra_context = {"titulo": "Novo cliente", "url_voltar": reverse_lazy("cliente_lista")}


class ClienteEditar(EditarCrud):
    model = Cliente
    form_class = ClienteForm
    extra_context = {"titulo": "Editar cliente"}


class ClienteExcluir(ExcluirCrud):
    model = Cliente
    success_url = reverse_lazy("cliente_lista")


# ---------- Alunos ----------
class AlunoLista(ListaCrud):
    model = Aluno
    template_name = "cadastros/aluno_lista.html"
    campos_busca = ["nome", "celular", "email", "cpf"]


class AlunoDetalhe(HistoricoServicosMixin, DetalheCrud):
    model = Aluno
    template_name = "cadastros/aluno_detalhe.html"


class AlunoDocumento(PermissionRequiredMixin, View):
    """
    Entrega um documento do aluno somente para usuários logados com permissão
    de consulta. Os arquivos ficam fora de qualquer pasta pública (MEDIA_ROOT).
    """
    permission_required = "cadastros.view_aluno"

    def get(self, request, pk, campo):
        if campo not in dict(Aluno.DOCUMENTOS):
            raise Http404
        arquivo = getattr(get_object_or_404(Aluno, pk=pk), campo)
        if not arquivo:
            raise Http404("Documento não enviado.")
        try:
            resposta = FileResponse(arquivo.open("rb"))
        except FileNotFoundError:
            raise Http404("Arquivo não encontrado.")
        resposta["Cache-Control"] = "private, no-store"
        return resposta


class AlunoCriar(CriarCrud):
    model = Aluno
    form_class = AlunoForm
    extra_context = {"titulo": "Novo aluno", "url_voltar": reverse_lazy("aluno_lista")}


class AlunoEditar(EditarCrud):
    model = Aluno
    form_class = AlunoForm
    extra_context = {"titulo": "Editar aluno"}


class AlunoExcluir(ExcluirCrud):
    model = Aluno
    success_url = reverse_lazy("aluno_lista")


# ---------- Veículos ----------
class VeiculoLista(ListaCrud):
    model = Veiculo
    template_name = "cadastros/veiculo_lista.html"
    campos_busca = ["placa", "marca", "modelo", "proprietario__nome"]

    def get_queryset(self):
        return super().get_queryset().select_related("proprietario")


class VeiculoDetalhe(HistoricoServicosMixin, DetalheCrud):
    model = Veiculo
    template_name = "cadastros/veiculo_detalhe.html"


class VeiculoCriar(CriarCrud):
    model = Veiculo
    form_class = VeiculoForm
    extra_context = {"titulo": "Novo veículo", "url_voltar": reverse_lazy("veiculo_lista")}

    def get_initial(self):
        # Vindo da tela do cliente: /veiculos/novo/?cliente=ID
        inicial = super().get_initial()
        cliente_id = self.request.GET.get("cliente")
        if cliente_id and cliente_id.isdigit():
            inicial["proprietario"] = cliente_id
        return inicial


class VeiculoEditar(EditarCrud):
    model = Veiculo
    form_class = VeiculoForm
    extra_context = {"titulo": "Editar veículo"}


class VeiculoExcluir(ExcluirCrud):
    model = Veiculo
    success_url = reverse_lazy("veiculo_lista")
