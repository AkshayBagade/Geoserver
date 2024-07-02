"""
URL configuration for geoserver_python project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from .views import upload_points,publish_layer_geoserver,update_style_to_layer,create_contour_layer,upload_points_v1

urlpatterns = [
    path('admin/', admin.site.urls),
    path('upload_points_layer_postgis/',upload_points, name='json'),
    path('upload_points_layer_postgis_v1/',upload_points_v1, name='json'),
    path('publish_layer/', publish_layer_geoserver, name='publish_layer_geoserver'),
    path('update_style_to_layer/',update_style_to_layer,name='update_style_to_layer'),
    path('create_contour_layer/',create_contour_layer, name='json'),
]
