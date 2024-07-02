from django.db import models
from django.contrib.gis.db import models as gis_models

# GIS model using Django's GIS capabilities
class GISPointModel(gis_models.Model):
    name = models.CharField(max_length=100)
    geom = gis_models.PointField()
    grading = models.CharField(max_length=100,default=0.0)

    class Meta:
        verbose_name = "GIS Model"
        verbose_name_plural = "GIS Models"