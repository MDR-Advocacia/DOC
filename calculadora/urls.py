from django.urls import path

from . import views


urlpatterns = [
    path('', views.lista_calculos, name='calculadora_lista'),
    path('novo/', views.novo_calculo, name='calculadora_novo'),
    path('<int:calculo_id>/', views.detalhe_calculo, name='calculadora_detalhe'),
]
