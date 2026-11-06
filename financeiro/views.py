"""
Telas do Financeiro. TUDO exige `financeiro.ver_financeiro` (somente Administrador), além da
permissão da própria ação; a única exceção é o registro de recebimento pela tela do atendimento
(atendimentos.views.AtendimentoReceber, permissão `financeiro.add_recebimento`).
Cálculos ficam em services.py e as regras de gravação em regras.py.
"""
import mimetypes
import os
from datetime import datetime

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.functional import cached_property
from django.views import View
from django.views.generic import FormView, ListView, TemplateView

from cadastros.crud import CriarCrud, DetalheCrud, EditarCrud, ExcluirCrud, ListaCrud
from cadastros.models import Cliente
from dashboard import periodos
from dashboard.exportacao import numero_br, resposta_csv, texto_seguro
from dashboard.graficos import por_categoria

from . import graficos, regras, services
from .forms import (
    CategoriaDespesaForm, DespesaForm, EstornoForm, FiltroPeriodoForm, PagarDespesaForm, RecebimentoEdicaoForm,
    RecebimentoForm,
)
from .models import CategoriaDespesa, Despesa, FechamentoMes, FormaPagamento, Recebimento, RegistroAuditoria

Entidade = RegistroAuditoria.Entidade


# ---------- Base de permissões ----------
class ModuloFinanceiro(PermissionRequiredMixin):
    permission_required = ["financeiro.ver_financeiro"]


class PermissaoFinanceiro:
    """Para as views genéricas de CRUD: exige a permissão da ação E a de acesso ao módulo."""

    def get_permission_required(self):
        return [*super().get_permission_required(), "financeiro.ver_financeiro"]


class GeraRecorrentes:
    """Ao abrir a tela, garante que as despesas dos próximos meses existam (idempotente; ver regras.gerar_recorrentes)."""

    def get(self, request, *args, **kwargs):
        regras.gerar_recorrentes()
        return super().get(request, *args, **kwargs)


def auditoria_de(entidade, objeto_id):
    return RegistroAuditoria.objects.filter(entidade=entidade, objeto_id=objeto_id).select_related("usuario")


def _filtros(form_class, request):
    """Valida os filtros do GET; campo inválido é ignorado (nunca quebra a tela)."""
    form = form_class(request.GET or None)
    form.is_valid()
    return form, getattr(form, "cleaned_data", {})


class _DataInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class FiltroReceberForm(forms.Form):
    cliente = forms.ModelChoiceField(queryset=Cliente.objects.only("id", "nome").order_by("nome"), required=False, empty_label="Todos")
    de = forms.DateField(required=False, widget=_DataInput())
    ate = forms.DateField(required=False, widget=_DataInput())
    faixa = forms.ChoiceField(required=False, choices=[("", "Todas")] + [
        ("a_vencer", "A vencer"), ("1_30", "1 a 30 dias"), ("31_60", "31 a 60 dias"), ("mais_60", "Mais de 60 dias")])


class FiltroPagarForm(forms.Form):
    categoria = forms.ModelChoiceField(queryset=CategoriaDespesa.objects.all(), required=False, empty_label="Todas")
    faixa = forms.ChoiceField(required=False, choices=[("", "Todas")] + [
        ("vencidas", "Vencidas"), ("hoje", "Vencem hoje"), ("7_dias", "Próximos 7 dias"),
        ("30_dias", "8 a 30 dias"), ("depois", "Mais adiante")])


class FiltroRecebimentoForm(forms.Form):
    forma = forms.ChoiceField(required=False, choices=[("", "Todas")] + FormaPagamento.choices)
    situacao = forms.ChoiceField(required=False, choices=[("", "Válidos"), ("estornados", "Estornados"), ("todos", "Todos")])
    cliente = forms.ModelChoiceField(queryset=Cliente.objects.only("id", "nome").order_by("nome"), required=False, empty_label="Todos")
    de = forms.DateField(required=False, widget=_DataInput())
    ate = forms.DateField(required=False, widget=_DataInput())


class FiltroDespesaForm(forms.Form):
    situacao = forms.ChoiceField(required=False, choices=[
        ("", "Todas"), ("em_aberto", "Em aberto"), ("vencidas", "Vencidas"), ("pagas", "Pagas")])
    categoria = forms.ModelChoiceField(queryset=CategoriaDespesa.objects.all(), required=False, empty_label="Todas")
    de = forms.DateField(required=False, widget=_DataInput())
    ate = forms.DateField(required=False, widget=_DataInput())


# ---------- Finance Dashboard ----------
class FinanceiroDashboard(ModuloFinanceiro, GeraRecorrentes, TemplateView):
    template_name = "financeiro/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        form = FiltroPeriodoForm(self.request.GET or None)
        periodo = form.periodo_escolhido()
        p = services.painel(periodo)
        ctx.update({
            "form": form, "periodo": periodo, "p": p,
            "graficos": {
                "entradas_saidas": graficos.entradas_e_saidas(p["serie"]),
                "resultado": graficos.resultado_mensal(p["serie"]),
                "despesas": graficos.despesas_por_categoria(p["despesas_categoria"]),
                "formas": graficos.formas_de_pagamento(p["formas"]),
                "receita": por_categoria(p["receita_categoria"], formato="moeda"),
                "margem": graficos.margem_por_servico(p["margem_servico"]),
            },
            "meses_fechados": sorted(regras.meses_fechados(), reverse=True),
        })
        return ctx


# ---------- Contas a receber ----------
class ContasReceber(ModuloFinanceiro, ListView):
    template_name = "financeiro/contas_receber.html"
    paginate_by = 15
    context_object_name = "atendimentos"

    def get_queryset(self):
        self.form, d = _filtros(FiltroReceberForm, self.request)
        self.hoje = timezone.localdate()
        base = services.a_receber_base(d.get("cliente") and d["cliente"].pk, d.get("de"), d.get("ate"))
        self.base = base.select_related("cliente", "tipo_servico")
        return services.filtrar_faixa_receber(self.base, d.get("faixa"), self.hoje).order_by("data_atendimento", "id")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        parametros = self.request.GET.copy()
        parametros.pop("page", None)
        faixas = services.faixas_a_receber(self.base, self.hoje)
        ctx.update({
            "form": self.form, "hoje": self.hoje, "faixas": faixas,
            "total": sum((f["valor"] for f in faixas), 0), "querystring": parametros.urlencode(),
            "formas": FormaPagamento.choices,
        })
        return ctx


# ---------- Contas a pagar ----------
class ContasPagar(ModuloFinanceiro, GeraRecorrentes, ListView):
    template_name = "financeiro/contas_pagar.html"
    paginate_by = 15
    context_object_name = "despesas"

    def get_queryset(self):
        self.form, d = _filtros(FiltroPagarForm, self.request)
        self.hoje = timezone.localdate()
        self.base = services.a_pagar_base(d.get("categoria") and d["categoria"].pk)
        return services.filtrar_faixa_pagar(self.base, d.get("faixa"), self.hoje).order_by("vencimento", "id")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        parametros = self.request.GET.copy()
        parametros.pop("page", None)
        faixas = services.faixas_a_pagar(self.base, self.hoje)
        ctx.update({
            "form": self.form, "hoje": self.hoje, "faixas": faixas,
            "total": sum((f["valor"] for f in faixas), 0), "querystring": parametros.urlencode(),
            "formas": FormaPagamento.choices,
        })
        return ctx


# ---------- Fluxo de caixa ----------
class FluxoCaixa(ModuloFinanceiro, TemplateView):
    template_name = "financeiro/fluxo_caixa.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        form = FiltroPeriodoForm(self.request.GET or None)
        periodo = form.periodo_escolhido()
        agrupar = "mes" if self.request.GET.get("agrupar") == "mes" else "dia"
        ctx.update({
            "form": form, "periodo": periodo, "agrupar": agrupar,
            "fluxo": services.fluxo_de_caixa(periodo, agrupar),
            "projecao": services.projecao_30_dias(),
        })
        return ctx


# ---------- Recebimentos ----------
class RecebimentoLista(PermissaoFinanceiro, ListaCrud):
    model = Recebimento
    template_name = "financeiro/recebimento_lista.html"
    campos_busca = ["atendimento__cliente__nome", "atendimento__tipo_servico__nome", "observacao"]

    def get_queryset(self):
        qs = super().get_queryset().select_related("atendimento__cliente", "atendimento__tipo_servico", "criado_por")
        self.form, d = _filtros(FiltroRecebimentoForm, self.request)
        situacao = d.get("situacao")
        if situacao == "estornados":
            qs = qs.estornados()
        elif situacao != "todos":
            qs = qs.validos()
        if d.get("forma"):
            qs = qs.filter(forma=d["forma"])
        if d.get("cliente"):
            qs = qs.filter(atendimento__cliente=d["cliente"])
        if d.get("de"):
            qs = qs.filter(data__gte=d["de"])
        if d.get("ate"):
            qs = qs.filter(data__lte=d["ate"])
        self.filtrado = qs
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update({
            "form": self.form,
            "total": self.filtrado.validos().aggregate(t=Sum("valor"))["t"] or 0,
        })
        return ctx


class RecebimentoDetalhe(PermissaoFinanceiro, DetalheCrud):
    model = Recebimento
    template_name = "financeiro/recebimento_detalhe.html"

    def get_queryset(self):
        return super().get_queryset().select_related(
            "atendimento__cliente", "atendimento__tipo_servico", "criado_por", "alterado_por", "estornado_por")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["auditoria"] = auditoria_de(Entidade.RECEBIMENTO, self.object.pk)
        ctx["pode_estornar"] = self.request.user.has_perm("financeiro.estornar_recebimento") and not self.object.estornado
        ctx["pode_editar"] = self.request.user.has_perm("financeiro.change_recebimento") and not self.object.estornado
        return ctx


class RecebimentoCriar(ModuloFinanceiro, FormView):
    """Registro pela área financeira: escolhe o atendimento (a regra é a mesma da tela do atendimento)."""
    permission_required = ["financeiro.ver_financeiro", "financeiro.add_recebimento"]
    template_name = "form_generico.html"
    form_class = RecebimentoForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["usuario"] = self.request.user
        return kwargs

    def get_initial(self):
        inicial = super().get_initial()
        if self.request.GET.get("atendimento", "").isdigit():
            inicial["atendimento"] = self.request.GET["atendimento"]
        return inicial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update({"titulo": "Novo recebimento", "url_voltar": reverse("recebimento_lista")})
        return ctx

    def form_valid(self, form):
        recebimento = form.salvar()
        if recebimento is None:
            return self.form_invalid(form)
        messages.success(self.request, "Recebimento registrado.")
        return redirect(recebimento)

    def form_invalid(self, form):
        messages.error(self.request, "Não foi possível salvar. Corrija os campos destacados.")
        return super().form_invalid(form)


class RecebimentoEditar(ModuloFinanceiro, FormView):
    permission_required = ["financeiro.ver_financeiro", "financeiro.change_recebimento"]
    template_name = "form_generico.html"
    form_class = RecebimentoEdicaoForm

    @cached_property
    def object(self):
        return get_object_or_404(Recebimento.objects.select_related("atendimento__cliente"), pk=self.kwargs["pk"])

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update(recebimento=self.object, usuario=self.request.user)
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update({"titulo": f"Editar recebimento #{self.object.pk}", "object": self.object})
        return ctx

    def form_valid(self, form):
        if form.salvar() is None:
            return self.form_invalid(form)
        messages.success(self.request, "Recebimento atualizado.")
        return redirect(self.object)


class RecebimentoEstornar(ModuloFinanceiro, FormView):
    """Estorno com motivo obrigatório. O recebimento continua registrado e some do caixa."""
    permission_required = ["financeiro.ver_financeiro", "financeiro.estornar_recebimento"]
    template_name = "financeiro/estornar.html"
    form_class = EstornoForm

    @cached_property
    def object(self):
        return get_object_or_404(Recebimento.objects.select_related("atendimento__cliente"), pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["object"] = self.object
        return ctx

    def form_valid(self, form):
        try:
            regras.estornar_recebimento(self.object, form.cleaned_data["motivo"], self.request.user)
        except ValidationError as erro:
            form.add_error(None, erro)
            return self.form_invalid(form)
        messages.success(self.request, "Recebimento estornado.")
        return redirect(self.object)


# ---------- Despesas ----------
class DespesaLista(PermissaoFinanceiro, GeraRecorrentes, ListaCrud):
    model = Despesa
    template_name = "financeiro/despesa_lista.html"
    campos_busca = ["descricao", "fornecedor", "categoria__nome"]

    def get_queryset(self):
        qs = super().get_queryset().select_related("categoria", "tipo_servico")
        self.form, d = _filtros(FiltroDespesaForm, self.request)
        hoje = timezone.localdate()
        situacao = d.get("situacao")
        if situacao == "em_aberto":
            qs = qs.em_aberto()
        elif situacao == "vencidas":
            qs = qs.em_aberto().filter(vencimento__lt=hoje)
        elif situacao == "pagas":
            qs = qs.pagas()
        if d.get("categoria"):
            qs = qs.filter(categoria=d["categoria"])
        if d.get("de"):
            qs = qs.filter(vencimento__gte=d["de"])
        if d.get("ate"):
            qs = qs.filter(vencimento__lte=d["ate"])
        self.filtrado = qs
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update({"form": self.form, "total": self.filtrado.aggregate(t=Sum("valor"))["t"] or 0,
                    "formas": FormaPagamento.choices})
        return ctx


class DespesaDetalhe(PermissaoFinanceiro, DetalheCrud):
    model = Despesa
    template_name = "financeiro/despesa_detalhe.html"

    def get_queryset(self):
        return super().get_queryset().select_related("categoria", "tipo_servico", "criado_por", "alterado_por", "origem")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update({"auditoria": auditoria_de(Entidade.DESPESA, self.object.pk), "formas": FormaPagamento.choices})
        return ctx


class _FormularioDespesa:
    form_class = DespesaForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["usuario"] = self.request.user
        return kwargs


class DespesaCriar(PermissaoFinanceiro, _FormularioDespesa, CriarCrud):
    model = Despesa
    extra_context = {"titulo": "Nova despesa", "url_voltar": reverse_lazy("despesa_lista")}
    mensagem_sucesso = "Despesa registrada."


class DespesaEditar(PermissaoFinanceiro, _FormularioDespesa, EditarCrud):
    model = Despesa
    extra_context = {"titulo": "Editar despesa"}


class DespesaExcluir(PermissaoFinanceiro, ExcluirCrud):
    model = Despesa
    success_url = reverse_lazy("despesa_lista")

    def form_valid(self, form):
        try:
            regras.excluir_despesa(self.object, self.request.user)
        except ValidationError as erro:
            messages.error(self.request, "; ".join(erro.messages))
            return self.render_to_response(self.get_context_data(form=form))
        messages.success(self.request, "Despesa excluída.")
        return redirect(self.success_url)


class DespesaPagar(ModuloFinanceiro, View):
    """Botão "Marcar como paga" (só POST)."""
    permission_required = ["financeiro.ver_financeiro", "financeiro.change_despesa"]
    http_method_names = ["post"]

    def post(self, request, pk):
        despesa = get_object_or_404(Despesa, pk=pk)
        form = PagarDespesaForm(request.POST)
        if form.is_valid():
            try:
                regras.pagar_despesa(despesa, form.cleaned_data["data"], form.cleaned_data["forma"], request.user)
                messages.success(request, "Despesa marcada como paga.")
            except ValidationError as erro:
                messages.error(request, "; ".join(erro.messages))
        else:
            for erros in form.errors.values():
                messages.error(request, erros[0])
        return redirect(request.POST.get("voltar") if (request.POST.get("voltar") or "").startswith("/financeiro/") else despesa)


class DespesaComprovante(ModuloFinanceiro, View):
    """Entrega o comprovante só a quem pode ver o Financeiro; o arquivo fica fora de pastas públicas."""
    permission_required = ["financeiro.ver_financeiro", "financeiro.view_despesa"]

    def get(self, request, pk):
        despesa = get_object_or_404(Despesa, pk=pk)
        if not despesa.comprovante:
            raise Http404("Esta despesa não tem comprovante.")
        try:
            arquivo = despesa.comprovante.open("rb")
        except FileNotFoundError:
            raise Http404("Arquivo não encontrado.")
        tipo = mimetypes.guess_type(despesa.comprovante.name)[0] or "application/octet-stream"
        resposta = FileResponse(arquivo, content_type=tipo, as_attachment=False,
                                filename=os.path.basename(despesa.comprovante.name))
        resposta["X-Content-Type-Options"] = "nosniff"
        resposta["Cache-Control"] = "private, no-store"
        return resposta


# ---------- Categorias de despesa ----------
class CategoriaLista(PermissaoFinanceiro, ListaCrud):
    model = CategoriaDespesa
    template_name = "financeiro/categoria_lista.html"
    campos_busca = ["nome"]


class CategoriaCriar(PermissaoFinanceiro, CriarCrud):
    model = CategoriaDespesa
    form_class = CategoriaDespesaForm
    extra_context = {"titulo": "Nova categoria de despesa", "url_voltar": reverse_lazy("categoria_despesa_lista")}


class CategoriaEditar(PermissaoFinanceiro, EditarCrud):
    model = CategoriaDespesa
    form_class = CategoriaDespesaForm
    extra_context = {"titulo": "Editar categoria de despesa"}


class CategoriaExcluir(PermissaoFinanceiro, ExcluirCrud):
    model = CategoriaDespesa
    success_url = reverse_lazy("categoria_despesa_lista")


# ---------- Relatório mensal ----------
def _mes_do_pedido(request):
    """?mes=AAAA-MM (campo "month" do navegador); inválido ou ausente = mês atual."""
    try:
        d = datetime.strptime(request.GET.get("mes", ""), "%Y-%m").date()
        if 2000 <= d.year <= 2100:
            return d
    except ValueError:
        pass
    return timezone.localdate().replace(day=1)


class RelatorioMensal(ModuloFinanceiro, TemplateView):
    template_name = "financeiro/relatorio.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        mes = _mes_do_pedido(self.request)
        ctx.update({
            "mes": mes, "r": services.relatorio_mensal(mes.year, mes.month),
            "fechado": regras.mes_fechado(mes), "gerado_em": timezone.localtime(),
        })
        return ctx


class RelatorioCsv(ModuloFinanceiro, View):
    def get(self, request):
        mes = _mes_do_pedido(request)
        r = services.relatorio_mensal(mes.year, mes.month)
        resposta, w = resposta_csv(f"resultado_{mes:%Y-%m}.csv")
        w.writerow(["Resultado do mês", f"{mes:%m/%Y}", "Regime de caixa"])
        w.writerow([])
        w.writerow(["Receitas por categoria de serviço", "Valor"])
        for rotulo, valor in r["receitas"]:
            w.writerow([rotulo, numero_br(valor)])
        w.writerow(["Total recebido", numero_br(r["recebido"])])
        w.writerow([])
        w.writerow(["Despesas pagas por categoria", "Valor"])
        for nome, valor in r["despesas"]:
            w.writerow([texto_seguro(nome), numero_br(valor)])
        w.writerow(["Total de despesas pagas", numero_br(r["pago"])])
        w.writerow(["  das quais diretas (de serviços)", numero_br(r["despesas_diretas"])])
        w.writerow(["  das quais gerais", numero_br(r["despesas_gerais_pagas"])])
        w.writerow([])
        w.writerow(["Resultado (recebido - despesas pagas)", numero_br(r["resultado"])])
        w.writerow(["Margem (%)", "" if r["margem"] is None else f"{r['margem']:.1f}".replace(".", ",")])
        w.writerow([])
        w.writerow(["Lucro por serviço (competência)", "Receita", "Despesas diretas", "Lucro", "Margem (%)"])
        for l in r["margem_servico"]:
            w.writerow([texto_seguro(l["nome"]), numero_br(l["receita"]), numero_br(l["despesas"]), numero_br(l["lucro"]),
                        "" if l["margem"] is None else f"{l['margem']:.1f}".replace(".", ",")])
        return resposta


# ---------- Fechamento de mês ----------
class Meses(ModuloFinanceiro, TemplateView):
    template_name = "financeiro/meses.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        atual = timezone.localdate().replace(day=1)
        registros = {f.mes: f for f in FechamentoMes.objects.select_related("fechado_por", "reaberto_por")}
        linhas = []
        for i in range(24):
            mes = periodos.primeiro_dia_meses_atras(atual, i)
            f = registros.get(mes)
            linhas.append({
                "mes": mes, "registro": f, "fechado": bool(f and f.fechado), "reaberto": bool(f and not f.fechado),
                "pode_fechar": mes < atual,
            })
        ctx.update({
            "linhas": linhas, "pode_fechar": self.request.user.has_perm("financeiro.fechar_mes"),
            "historico": RegistroAuditoria.objects.filter(entidade=Entidade.MES).select_related("usuario").order_by("-data_hora")[:15],
        })
        return ctx


class MesAlterar(ModuloFinanceiro, View):
    """Fecha ou reabre um mês (POST com mes=AAAA-MM)."""
    permission_required = ["financeiro.ver_financeiro", "financeiro.fechar_mes"]
    http_method_names = ["post"]
    acao = "fechar"

    def post(self, request):
        try:
            mes = datetime.strptime(request.POST.get("mes", ""), "%Y-%m").date()
        except ValueError:
            messages.error(request, "Mês inválido.")
            return redirect("meses")
        try:
            if self.acao == "fechar":
                regras.fechar_mes(mes, request.user)
                messages.success(request, f"Mês {mes:%m/%Y} fechado.")
            else:
                regras.reabrir_mes(mes, request.user)
                messages.success(request, f"Mês {mes:%m/%Y} reaberto.")
        except ValidationError as erro:
            messages.error(request, "; ".join(erro.messages))
        return redirect("meses")
