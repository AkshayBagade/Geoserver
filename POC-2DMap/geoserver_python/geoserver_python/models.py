from django.db import models
from django.contrib.gis.db import models as gis_models

# GIS model using Django's GIS capabilities
class GISPointModel(gis_models.Model):
    name = models.CharField(max_length=100)
    geom = gis_models.PointField()
    grading = models.DecimalField(max_digits=10,decimal_places=5,default=0.0,)
    bottom_of_pile = models.DecimalField(max_digits=10,decimal_places=5,default=0.0,)

    class Meta:
        verbose_name = "GIS Model"
        verbose_name_plural = "GIS Models"

    def __str__(self):
        return f"Point({self.geom.x}, {self.geom.y}, {self.grading})"

# GIS model using Django's GIS capabilities
class GISDelunaryTriangleModel(gis_models.Model):
    name = models.CharField(max_length=100)
    geom = gis_models.PolygonField()
    grading = models.DecimalField(max_digits=10,decimal_places=5,default=0.0,)

    class Meta:
        verbose_name = "GIS Model"
        verbose_name_plural = "GIS Models"

    def __str__(self):
        return f"Point({self.geom.x}, {self.geom.y}, {self.grading})"

class GISContour(gis_models.Model):
    grading = models.DecimalField(max_digits=10, decimal_places=5, default=0.0)
    geom = gis_models.LineStringField()

    class Meta:
        verbose_name = "GIS Model"
        verbose_name_plural = "GIS Models"

    def __str__(self):
        return f"Contour Level: {self.grading}"